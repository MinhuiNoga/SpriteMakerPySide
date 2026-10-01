from __future__ import annotations

from copy import copy
from typing import Callable, List, Optional

import numpy as np
import cv2
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QListWidget, QMessageBox, QPushButton, QScrollArea, QSlider,
    QSpinBox, QVBoxLayout, QWidget,
)

from .image_ops import qimage_to_array
from .models import Frame
from .widgets import CanvasWidget


def detect_foot_anchor(image: QImage, side: int = 0) -> Optional[QPoint]:
    """Estimate a contact point from the lower silhouette, not semantic anatomy.

    side: 0 = screen-left foot, 1 = screen-right foot, 2 = midpoint.
    Small disconnected specks and faint alpha fringes are excluded.
    """
    if image.isNull():
        return None
    mask = (qimage_to_array(image)[:, :, 3] >= 32).astype(np.uint8)
    if not mask.any() or mask.mean() > 0.95:
        return None
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    largest = int(stats[1:, cv2.CC_STAT_AREA].max())
    valid = np.flatnonzero(stats[:, cv2.CC_STAT_AREA] >= max(4, largest * 0.02))
    valid = valid[valid != 0]
    if not len(valid):
        return None
    clean = np.isin(labels, valid)
    rows = np.flatnonzero(clean.any(axis=1))
    top, bottom = int(rows[0]), int(rows[-1])
    band_top = top + int((bottom - top) * 0.72)
    lower = clean[band_top:bottom + 1]
    columns = np.flatnonzero(lower.any(axis=0))
    left, right = int(columns[0]), int(columns[-1])
    middle = (left + right) // 2

    def contact(x0: int, x1: int) -> Optional[QPoint]:
        part = lower[:, x0:x1 + 1]
        ys = np.flatnonzero(part.any(axis=1))
        if not len(ys):
            return None
        y = int(ys[-1])
        # Median of a short sole strip is less sensitive to a single edge pixel.
        xs = np.flatnonzero(part[max(0, y - max(1, (bottom - top) // 150)):y + 1].any(axis=0))
        return QPoint(x0 + int(round(float(np.median(xs)))), band_top + y)

    a, b = contact(left, middle), contact(middle + 1, right)
    if side == 2 and a is not None and b is not None:
        return QPoint(round((a.x() + b.x()) / 2), max(a.y(), b.y()))
    return (a if side == 0 else b) or a or b


class AlignmentCanvas(CanvasWidget):
    """Read-only image surface; clicks belong only to the alignment session."""

    def __init__(self, picked: Callable[[QPoint], None]) -> None:
        super().__init__()
        self.picked = picked
        self.reference: Optional[Frame] = None
        self.target: Optional[QPointF] = None  # Relative to the output center.
        self.anchor: Optional[QPoint] = None  # Current source-image coordinate.
        self.overlay_opacity = 0.35
        self.overlay_visible = True
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.frame is None:
            return
        self.sync_image_rect_to_workspace()
        point = self._event_to_image_pos(event)
        if point is not None:
            self.picked(point)

    def mouseMoveEvent(self, event) -> None:
        pass

    def snapped_center(self, frame: Frame) -> QPointF:
        cx, cy = frame.export_center
        size = self.export_size or QSize(frame.width, frame.height)
        return QPointF(round(cx - size.width() / 2) + size.width() / 2,
                       round(cy - size.height() / 2) + size.height() / 2)

    def sync_image_rect_to_workspace(self) -> None:
        if self.frame is None:
            self._image_rect = QRectF()
            return
        center = self.snapped_center(self.frame)
        self._image_rect = QRectF(self.width() / 2 - center.x() * self.zoom,
                                 self.height() / 2 - center.y() * self.zoom,
                                 self.frame.width * self.zoom, self.frame.height * self.zoom)

    def mouseReleaseEvent(self, event) -> None:
        pass

    def keyPressEvent(self, event) -> None:
        QWidget.keyPressEvent(self, event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.frame is None:
            return
        painter = QPainter(self)
        center = self.export_center_view_position()
        if self.reference is not None and self.overlay_visible:
            reference_center = self.snapped_center(self.reference)
            rx, ry = reference_center.x(), reference_center.y()
            painter.setOpacity(self.overlay_opacity)
            painter.drawImage(QRectF(
                center.x() - rx * self.zoom, center.y() - ry * self.zoom,
                self.reference.width * self.zoom, self.reference.height * self.zoom,
            ), self.reference.composite())
            painter.setOpacity(1)
        if self.target is not None:
            target = center + self.target * self.zoom
            painter.setPen(QPen(QColor("#ffcf40"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(0, target.y()), QPointF(self.width(), target.y()))
            painter.drawLine(QPointF(target.x(), 0), QPointF(target.x(), self.height()))
            painter.drawEllipse(target, 6, 6)
        if self.anchor is not None:
            point = self._image_to_view_point(self.anchor)
            painter.setPen(QPen(QColor("#00e5ff"), 2))
            painter.drawLine(point + QPointF(-9, 0), point + QPointF(9, 0))
            painter.drawLine(point + QPointF(0, -9), point + QPointF(0, 9))
        if self.export_size is not None:
            painter.setPen(QPen(QColor("#101010"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(center.x() - self.export_size.width() * self.zoom / 2,
                                    center.y() - self.export_size.height() * self.zoom / 2,
                                    self.export_size.width() * self.zoom, self.export_size.height() * self.zoom))
        painter.end()


class FootAlignmentDialog(QDialog):
    """Stage output-center edits without mutating source frames or layer pixels."""

    def __init__(self, frames: List[Frame], output_size: QSize, current_index: int = 0, parent=None, session: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("腳底對齊 — 手動錨點與逐格微調")
        self.resize(1150, 800)
        self.output_size = QSize(output_size)
        # Layers are shared read-only. Only these shallow copies' centers change.
        self.frames = [copy(frame) for frame in frames]
        self.original_centers = [frame.alignment_origin or (
            round(frame.export_center[0] - output_size.width() / 2) + output_size.width() / 2,
            round(frame.export_center[1] - output_size.height() / 2) + output_size.height() / 2,
        ) for frame in frames]
        self.anchors = {i: QPoint(*frame.alignment_anchor) for i, frame in enumerate(frames) if frame.alignment_anchor is not None}
        self.bounds = {}
        self.reference_index: Optional[int] = None
        self.picking_reference = False
        self._playing = False

        self.canvas = AlignmentCanvas(self.pick_anchor)
        self.canvas.set_export_size(self.output_size)
        self.canvas.zoom_changed.connect(self.resize_canvas)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)

        self.frame_list = QListWidget()
        self.frame_list.setMaximumWidth(260)
        for i, frame in enumerate(frames):
            self.frame_list.addItem(f"{i + 1:03d}  {frame.name}")
        self.frame_list.currentRowChanged.connect(self.select_frame)

        self.reference_button = QPushButton("設此格為參考，再點腳底")
        self.reference_button.clicked.connect(self.begin_reference)
        self.auto_side = QComboBox()
        self.auto_side.addItems(["畫面左腳", "畫面右腳", "雙腳中央"])
        self.auto_current = QPushButton("自動描點並對齊目前格")
        self.auto_all = QPushButton("自動描點並對齊全部影格")
        self.auto_current.clicked.connect(lambda: self.auto_anchor(False))
        self.auto_all.clicked.connect(lambda: self.auto_anchor(True))
        self.keep_anchors = QCheckBox("全部描點時保留已有錨點")
        self.keep_anchors.setChecked(True)
        self.reference_label = QLabel("尚未設定參考錨點")
        self.reference_label.setWordWrap(True)
        self.axis = QComboBox()
        self.axis.addItems(["水平＋垂直對齊", "只對齊高度（保留水平位置）"])
        self.overlay = QCheckBox("顯示參考疊圖")
        self.overlay.setChecked(True)
        self.overlay.toggled.connect(self.update_overlay)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(35)
        self.opacity.valueChanged.connect(self.update_overlay)
        self.dx = QSpinBox()
        self.dy = QSpinBox()
        for spin in (self.dx, self.dy):
            spin.setRange(-100000, 100000)
            spin.setSuffix(" px")
            spin.valueChanged.connect(self.apply_nudge)
        self.dx.setToolTip("相對本次編輯階段首次對齊的位置；正值向右，套用後重新開窗仍保留累計數值")
        self.dy.setToolTip("相對本次編輯階段首次對齊的位置；正值向下，套用後重新開窗仍保留累計數值")
        form = QFormLayout()
        form.addRow("對齊方式", self.axis)
        form.addRow("疊圖透明度", self.opacity)
        form.addRow("水平位移 →", self.dx)
        form.addRow("垂直位移 ↓", self.dy)

        self.reset = QPushButton("重設目前格")
        self.reset.clicked.connect(self.reset_current)
        self.previous = QPushButton("上一格")
        self.next = QPushButton("下一格")
        self.previous.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))
        navigation = QHBoxLayout()
        navigation.addWidget(self.previous)
        navigation.addWidget(self.next)
        self.play = QPushButton("播放預覽")
        self.play.setCheckable(True)
        self.play.toggled.connect(self.toggle_play)
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(12)
        self.fps.setSuffix(" FPS")
        self.fps.valueChanged.connect(lambda: self.timer.setInterval(round(1000 / self.fps.value())))
        self.timer = QTimer(self)
        self.timer.setInterval(83)
        self.timer.timeout.connect(lambda: self.frame_list.setCurrentRow((self.index + 1) % len(self.frames)))
        playback = QHBoxLayout()
        playback.addWidget(self.play)
        playback.addWidget(self.fps)
        self.zoom = QSpinBox()
        self.zoom.setRange(10, 800)
        self.zoom.setValue(50)
        self.zoom.setSuffix(" %")
        self.zoom.valueChanged.connect(lambda value: self.canvas.set_zoom(value / 100))
        form.addRow("縮放（Ctrl＋滾輪）", self.zoom)

        sidebar = QVBoxLayout()
        sidebar.addWidget(self.reference_button)
        sidebar.addWidget(self.reference_label)
        sidebar.addWidget(self.auto_side)
        sidebar.addWidget(self.auto_current)
        sidebar.addWidget(self.auto_all)
        sidebar.addWidget(self.keep_anchors)
        sidebar.addWidget(self.overlay)
        sidebar.addLayout(form)
        sidebar.addWidget(self.reset)
        sidebar.addWidget(self.frame_list, 1)
        sidebar.addLayout(navigation)
        sidebar.addLayout(playback)
        body = QHBoxLayout()
        body.addLayout(sidebar)
        body.addWidget(self.scroll, 1)
        instructions = QLabel(
            "① 手動設定參考腳底，或直接自動描點　② 逐格檢查／微調　③ 播放檢查後套用\n"
            "黃色＝參考基準；青色＝目前錨點。自動描點依透明輪廓估算，披風／武器可能影響結果；跑步／跳躍請保留自然抬腳。"
        )
        instructions.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.clipping_label = QLabel()
        self.clipping_label.setWordWrap(True)
        self.clipping_label.setStyleSheet("color: #dd8800")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setText("套用所有調整")
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(instructions)
        layout.addLayout(body, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.clipping_label)
        layout.addWidget(self.buttons)
        self.canvas.set_zoom(0.5)
        self.frame_list.setCurrentRow(max(0, min(current_index, len(frames) - 1)))
        if session:
            self.canvas.reference = session.get("reference")
            self.canvas.target = session.get("target")
            self.reference_label.setText(session.get("label", "尚未設定參考錨點"))
            self.axis.setCurrentIndex(session.get("axis", 0))
            self.auto_side.setCurrentIndex(session.get("auto_side", 0))
            self.keep_anchors.setChecked(session.get("keep_anchors", True))
            self.overlay.setChecked(session.get("overlay", True))
            self.opacity.setValue(session.get("opacity", 35))
            self.zoom.setValue(session.get("zoom", 50))
            self.fps.setValue(session.get("fps", 12))
            self.select_frame(self.index)
        QTimer.singleShot(0, self.resize_canvas)

    def session_snapshot(self) -> dict:
        return dict(reference=self.canvas.reference, target=self.canvas.target,
                    label=self.reference_label.text(), axis=self.axis.currentIndex(),
                    auto_side=self.auto_side.currentIndex(), keep_anchors=self.keep_anchors.isChecked(),
                    overlay=self.overlay.isChecked(), opacity=self.opacity.value(),
                    zoom=self.zoom.value(), fps=self.fps.value())

    def auto_anchor(self, all_frames: bool = False) -> None:
        if self.index < 0 or self._playing:
            return
        selected = self.index
        side = self.auto_side.currentIndex()
        if self.canvas.target is None or self.picking_reference:
            point = detect_foot_anchor(self.frames[selected].composite(), side)
            if point is None:
                self.status.setText("目前格無法估算腳底。請先去除不透明背景，或改用手動描點。")
                return
            self.picking_reference = True
            self.pick_anchor(point)
            if not all_frames:
                return
        skipped, changed = [], 0
        for index in (range(len(self.frames)) if all_frames else [selected]):
            if all_frames and self.keep_anchors.isChecked() and index in self.anchors:
                continue
            point = detect_foot_anchor(self.frames[index].composite(), side)
            if point is None:
                skipped.append(index + 1)
                continue
            self.frame_list.setCurrentRow(index)
            self.pick_anchor(point)
            changed += 1
        self.frame_list.setCurrentRow(selected)
        self.status.setText(f"自動描點完成：{changed} 格；仍可手動點選修正。" +
                            (f" 無法估算並保留原狀：{', '.join(map(str, skipped))}。" if skipped else ""))

    @property
    def index(self) -> int:
        return self.frame_list.currentRow()

    def resize_canvas(self, *args) -> None:
        viewport = self.scroll.viewport().size()
        hint = self.canvas.sizeHint()
        self.canvas.resize(max(viewport.width(), hint.width()), max(viewport.height(), hint.height()))
        self.canvas.sync_image_rect_to_workspace()
        self.zoom.blockSignals(True)
        self.zoom.setValue(round(self.canvas.zoom * 100))
        self.zoom.blockSignals(False)
        self.canvas.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "zoom"):
            self.resize_canvas()

    def select_frame(self, index: int) -> None:
        if index < 0 or index >= len(self.frames):
            return
        self.picking_reference = False
        self.canvas.set_frame(self.frames[index])
        self.canvas.anchor = self.anchors.get(index)
        self.sync_controls()
        self.status.setText("點選此格的對應腳底錨點，或用 X／Y 數值微調。" if self.canvas.target is not None else "先按「設此格為參考」，再在畫布點選腳底。")
        self.resize_canvas()

    def begin_reference(self) -> None:
        if self.index < 0:
            return
        self.play.setChecked(False)
        self.picking_reference = True
        self.status.setText("請在目前格點選支撐腳接地位置；新參考只影響後續點選，不重算之前的調整。")

    def pick_anchor(self, point: QPoint) -> None:
        if self.index < 0 or self._playing:
            return
        frame = self.frames[self.index]
        if not frame.composite().rect().contains(point):
            return
        if self.content_bounds(self.index) is None:
            self.status.setText("此格完全透明，無法設定腳底錨點。")
            return
        if self.picking_reference:
            self.reference_index = self.index
            self.canvas.reference = frame.clone()
            center = self.canvas.snapped_center(frame)
            self.canvas.target = QPointF(point) - center
            self.picking_reference = False
            self.reference_label.setText(f"參考：第 {self.index + 1} 格（固定快照）\n腳底：({point.x()}, {point.y()})")
            self.status.setText("參考已設定。切換其他格，再點對應腳底；可隨時重新設定參考。")
        elif self.canvas.target is not None:
            target = self.canvas.target
            # Quantize to integer source origins, exactly as PNG/sheet export does.
            cx = point.x() - target.x()
            cy = point.y() - target.y()
            if self.axis.currentIndex() == 0:
                frame.export_center_x = round(cx - self.output_size.width() / 2) + self.output_size.width() / 2
            frame.export_center_y = round(cy - self.output_size.height() / 2) + self.output_size.height() / 2
            self.status.setText(f"第 {self.index + 1} 格已暫存對齊；可微調或切換下一格。")
        else:
            self.status.setText("請先按「設此格為參考」，再點選參考脚底。")
            return
        self.anchors[self.index] = QPoint(point)
        frame.alignment_anchor = (point.x(), point.y())
        frame.alignment_origin = self.original_centers[self.index]
        self.canvas.anchor = QPoint(point)
        self.sync_controls()
        self.resize_canvas()

    def sync_controls(self) -> None:
        ox, oy = self.original_centers[self.index]
        cx, cy = self.frames[self.index].export_center
        dx = round(ox - self.output_size.width() / 2) - round(cx - self.output_size.width() / 2)
        dy = round(oy - self.output_size.height() / 2) - round(cy - self.output_size.height() / 2)
        for spin, value in ((self.dx, dx), (self.dy, dy)):
            spin.blockSignals(True)
            spin.setValue(round(value))
            spin.blockSignals(False)
        self.previous.setEnabled(self.index > 0 and not self._playing)
        self.next.setEnabled(self.index < len(self.frames) - 1 and not self._playing)
        self.update_clipping()

    def apply_nudge(self, *args) -> None:
        if self.index < 0:
            return
        ox, oy = self.original_centers[self.index]
        self.frames[self.index].export_center_x = round(ox - self.output_size.width() / 2) + self.output_size.width() / 2 - self.dx.value()
        self.frames[self.index].export_center_y = round(oy - self.output_size.height() / 2) + self.output_size.height() / 2 - self.dy.value()
        self.frames[self.index].alignment_origin = self.original_centers[self.index]
        self.update_clipping()
        self.resize_canvas()

    def reset_current(self) -> None:
        if self.index < 0:
            return
        frame = self.frames[self.index]
        frame.export_center_x, frame.export_center_y = self.original_centers[self.index]
        self.anchors.pop(self.index, None)
        frame.alignment_anchor = None
        self.canvas.anchor = None
        self.sync_controls()
        self.resize_canvas()

    def update_overlay(self, *args) -> None:
        self.canvas.overlay_visible = self.overlay.isChecked()
        self.canvas.overlay_opacity = self.opacity.value() / 100
        self.canvas.update()

    def step(self, delta: int) -> None:
        self.frame_list.setCurrentRow(max(0, min(len(self.frames) - 1, self.index + delta)))

    def toggle_play(self, enabled: bool) -> None:
        self._playing = enabled
        self.picking_reference = False
        self.play.setText("停止預覽" if enabled else "播放預覽")
        for control in (self.reference_button, self.dx, self.dy, self.axis, self.reset, self.auto_current, self.auto_all, self.auto_side, self.keep_anchors):
            control.setEnabled(not enabled)
        self.timer.start() if enabled else self.timer.stop()
        if self.index >= 0:
            self.sync_controls()

    def content_bounds(self, index: int) -> Optional[QRect]:
        if index not in self.bounds:
            alpha = qimage_to_array(self.frames[index].composite())[:, :, 3]
            ys, xs = np.nonzero(alpha)
            self.bounds[index] = None if not len(xs) else QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        return self.bounds[index]

    def is_clipped(self, index: int) -> bool:
        bounds = self.content_bounds(index)
        if bounds is None:
            return False
        cx, cy = self.frames[index].export_center
        rect = QRect(round(cx - self.output_size.width() / 2), round(cy - self.output_size.height() / 2), self.output_size.width(), self.output_size.height())
        return not rect.contains(bounds)

    def update_clipping(self) -> None:
        self.clipping_label.setText(
            "⚠ 目前格有可見像素超出輸出框（可能包含刀尖／帽子）。原像素仍保留；請返回編輯器加大輸出 W／H 後匯出。"
            if self.is_clipped(self.index) else ""
        )

    def accept(self) -> None:
        self.play.setChecked(False)
        clipped = [str(i + 1) for i in range(len(self.frames)) if self.is_clipped(i)]
        if clipped:
            result = QMessageBox.warning(
                self, "輸出框範圍不足",
                "以下影格有可見像素超出輸出框：" + ", ".join(clipped) +
                "\n對齊不會刪除原始像素。套用後請加大輸出 W／H，否則匯出時會裁切。\n仍要套用對齊嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        super().accept()

    def done(self, result: int) -> None:
        self.timer.stop()
        super().done(result)
