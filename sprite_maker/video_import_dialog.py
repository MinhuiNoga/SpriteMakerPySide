from __future__ import annotations

from pathlib import Path
from typing import List, Optional
import zipfile

import cv2
from PySide6.QtCore import QByteArray, QBuffer, QEvent, QIODevice, QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QIcon, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .video_ops import ExtractedVideoFrame, VideoMetadata, cv_frame_to_qimage, extract_video_frames, read_video_metadata


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}


def format_seconds(value: float) -> str:
    minutes = int(value // 60)
    seconds = value - minutes * 60
    return f"{minutes:02d}:{seconds:06.3f}"


class TimeRangeSlider(QWidget):
    rangeChanged = Signal(float, float)
    rangeCommitted = Signal(float, float)
    playheadChanged = Signal(float)
    dragStarted = Signal()
    dragFinished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.minimum = 0.0
        self.maximum = 1.0
        self.start_value = 0.0
        self.end_value = 1.0
        self.playhead_value = 0.0
        self._drag_handle: Optional[str] = None
        self._handle_radius = 10
        self.setMinimumHeight(58)
        self.setMouseTracking(True)

    def setDuration(self, duration: float) -> None:
        self.minimum = 0.0
        self.maximum = max(0.001, duration)
        self.start_value = max(self.minimum, min(self.start_value, self.maximum))
        self.end_value = max(self.start_value, min(self.end_value, self.maximum))
        if self.end_value <= self.start_value:
            self.end_value = self.maximum
        self.update()

    def setRangeValues(self, start: float, end: float, emit_signal: bool = False) -> None:
        start = max(self.minimum, min(float(start), self.maximum))
        end = max(self.minimum, min(float(end), self.maximum))
        if start > end:
            start, end = end, start
        self.start_value = start
        self.end_value = end
        self.playhead_value = max(start, min(self.playhead_value, end))
        self.update()
        if emit_signal:
            self.rangeChanged.emit(self.start_value, self.end_value)

    def setPlayhead(self, value: float) -> None:
        self.playhead_value = max(self.start_value, min(float(value), self.end_value))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = self._track_rect()
        center_y = track.center().y()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#6b7280"))
        painter.drawRoundedRect(track, 3, 3)

        selected = QRectF(
            self._value_to_x(self.start_value),
            track.top(),
            max(1.0, self._value_to_x(self.end_value) - self._value_to_x(self.start_value)),
            track.height(),
        )
        painter.setBrush(QColor("#38bdf8"))
        painter.drawRoundedRect(selected, 3, 3)

        playhead_x = self._value_to_x(self.playhead_value)
        painter.setPen(QPen(QColor("#facc15"), 2))
        painter.drawLine(QPointF(playhead_x, track.top() - 8), QPointF(playhead_x, track.bottom() + 8))
        painter.setBrush(QColor("#facc15"))
        painter.setPen(QPen(QColor("#111827"), 2))
        painter.drawEllipse(QPointF(playhead_x, center_y), max(6, self._handle_radius - 2), max(6, self._handle_radius - 2))

        for value, color in ((self.start_value, QColor("#22c55e")), (self.end_value, QColor("#ef4444"))):
            x = self._value_to_x(value)
            painter.setPen(QPen(QColor("#111827"), 2))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, center_y), self._handle_radius, self._handle_radius)

        painter.setPen(QColor("#e5e7eb"))
        painter.drawText(
            0,
            16,
            self.width(),
            18,
            Qt.AlignmentFlag.AlignCenter,
            f"{format_seconds(self.start_value)}  -  {format_seconds(self.end_value)}",
        )
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        start_distance = abs(event.position().x() - self._value_to_x(self.start_value))
        end_distance = abs(event.position().x() - self._value_to_x(self.end_value))
        playhead_distance = abs(event.position().x() - self._value_to_x(self.playhead_value))
        if start_distance <= self._handle_radius + 4 or end_distance <= self._handle_radius + 4:
            self._drag_handle = "start" if start_distance <= end_distance else "end"
        elif playhead_distance <= self._handle_radius + 8:
            self._drag_handle = "playhead"
        else:
            self._drag_handle = "start" if start_distance <= end_distance else "end"
        self.dragStarted.emit()
        self._move_handle(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_handle:
            self._move_handle(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        handle = self._drag_handle
        self._drag_handle = None
        if handle in {"start", "end"}:
            self.rangeCommitted.emit(self.start_value, self.end_value)
        elif handle == "playhead":
            self.playheadChanged.emit(self.playhead_value)
        if handle:
            self.dragFinished.emit()

    def _move_handle(self, x: float) -> None:
        value = self._x_to_value(x)
        if self._drag_handle == "start":
            self.start_value = min(value, self.end_value)
            self.playhead_value = max(self.start_value, self.playhead_value)
        elif self._drag_handle == "end":
            self.end_value = max(value, self.start_value)
            self.playhead_value = min(self.playhead_value, self.end_value)
        elif self._drag_handle == "playhead":
            self.playhead_value = max(self.start_value, min(value, self.end_value))
            self.update()
            return
        self.update()
        self.rangeChanged.emit(self.start_value, self.end_value)

    def _track_rect(self) -> QRectF:
        margin = self._handle_radius + 10
        return QRectF(margin, 32, max(1, self.width() - margin * 2), 7)

    def _value_to_x(self, value: float) -> float:
        track = self._track_rect()
        ratio = 0.0 if self.maximum <= self.minimum else (value - self.minimum) / (self.maximum - self.minimum)
        return track.left() + ratio * track.width()

    def _x_to_value(self, x: float) -> float:
        track = self._track_rect()
        ratio = (x - track.left()) / max(1.0, track.width())
        ratio = max(0.0, min(1.0, ratio))
        return self.minimum + ratio * (self.maximum - self.minimum)


class FramePickerList(QListWidget):
    rangeSelectionChanged = Signal()
    zoomRequested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setMovement(QListWidget.Movement.Static)
        self._press_row = -1
        self._range_mode = False
        self._target_state = Qt.CheckState.Checked
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._begin_range_mode)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            self._press_row = self.row(item) if item else -1
            self._range_mode = False
            if self._press_row >= 0:
                self._long_press_timer.start(360)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._range_mode and self._press_row >= 0:
            item = self.itemAt(event.position().toPoint())
            if item:
                self._apply_range(self.row(item))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._long_press_timer.stop()
        if self._range_mode:
            self._range_mode = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _begin_range_mode(self) -> None:
        if self._press_row < 0 or self._press_row >= self.count():
            return
        item = self.item(self._press_row)
        self._target_state = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
        self._range_mode = True
        self._apply_range(self._press_row)

    def _apply_range(self, row: int) -> None:
        start = min(self._press_row, row)
        end = max(self._press_row, row)
        self.blockSignals(True)
        for index in range(start, end + 1):
            self.item(index).setCheckState(self._target_state)
        self.blockSignals(False)
        self.rangeSelectionChanged.emit()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 16 if event.angleDelta().y() > 0 else -16
            self.zoomRequested.emit(delta)
            event.accept()
            return
        super().wheelEvent(event)


class ZoomImageLabel(QLabel):
    zoomChanged = Signal()

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.source_image: Optional[QImage] = None
        self.zoom = 1.0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#111827; color:#e5e7eb;")

    def setImage(self, image: QImage) -> None:
        self.source_image = image.copy()
        self.refreshPixmap()

    def refreshPixmap(self) -> None:
        if self.source_image is None or self.source_image.isNull():
            return
        base_size = self.size()
        pixmap = QPixmap.fromImage(self.source_image).scaled(
            max(1, round(base_size.width() * self.zoom)),
            max(1, round(base_size.height() * self.zoom)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.setPixmap(pixmap)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 0.12 if event.angleDelta().y() > 0 else -0.12
            self.zoom = max(0.2, min(5.0, self.zoom + step))
            self.refreshPixmap()
            self.zoomChanged.emit()
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refreshPixmap()


class VideoExtractSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(list)
    failed = Signal(str)


class VideoExtractWorker(QRunnable):
    def __init__(self, path: Path, start: float, end: float, target_fps: float) -> None:
        super().__init__()
        self.path = path
        self.start = start
        self.end = end
        self.target_fps = target_fps
        self.signals = VideoExtractSignals()

    @Slot()
    def run(self) -> None:
        try:
            frames = extract_video_frames(self.path, self.start, self.end, self.target_fps)
            total = max(1, len(frames))
            for index in range(total):
                self.signals.progress.emit(index + 1, total)
            self.signals.finished.emit(frames)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class VideoImportDialog(QDialog):
    def __init__(self, parent=None, show_switch_button: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("匯入影片")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setSizeGripEnabled(True)
        self.resize(1280, 820)
        self.thread_pool = QThreadPool.globalInstance()
        self.video_path: Optional[Path] = None
        self.metadata: Optional[VideoMetadata] = None
        self.frames: List[ExtractedVideoFrame] = []
        self.import_images: List[QImage] = []
        self.worker: Optional[VideoExtractWorker] = None
        self.preview_capture = None
        self.current_video_image: Optional[QImage] = None
        self.switch_to_editor = False
        self._syncing_range = False
        self.preview_playing = False
        self.animation_index = 0
        self._pending_seek_value = 0.0
        self._slider_dragging = False
        self._resume_video_after_slider_drag = False

        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self.advance_video_preview)
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.timeout.connect(self.apply_pending_seek)
        self.frame_animation_timer = QTimer(self)
        self.frame_animation_timer.timeout.connect(self.advance_frame_animation)

        self.pages = QStackedWidget()
        self.video_page = self._build_video_page()
        self.frame_page = self._build_frame_page()
        self.pages.addWidget(self.video_page)
        self.pages.addWidget(self.frame_page)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

        self.select_all_button = QPushButton("全選")
        self.select_all_button.clicked.connect(lambda: self.set_all_checked(True))
        self.select_none_button = QPushButton("全不選")
        self.select_none_button.clicked.connect(lambda: self.set_all_checked(False))
        self.invert_button = QPushButton("反選")
        self.invert_button.clicked.connect(self.invert_selection)
        self.save_png_button = QPushButton("儲存 PNG")
        self.save_png_button.clicked.connect(self.save_selected_pngs)
        self.import_editor_button = QPushButton("匯入編輯器")
        self.import_editor_button.clicked.connect(self.accept_for_import)
        self.switch_editor_button = QPushButton("切換到編輯模式")
        self.switch_editor_button.clicked.connect(self.accept_for_editor_switch)
        self.switch_editor_button.setVisible(show_switch_button)
        self.close_button = QPushButton("關閉")
        self.close_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        for button in (self.select_all_button, self.select_none_button, self.invert_button):
            button_row.addWidget(button)
        button_row.addStretch(1)
        button_row.addWidget(self.save_png_button)
        button_row.addWidget(self.import_editor_button)
        button_row.addWidget(self.switch_editor_button)
        button_row.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.pages, 1)
        layout.addWidget(self.progress)
        layout.addLayout(button_row)
        self.update_page_buttons()
        self.enable_video_drop()

    def enable_video_drop(self) -> None:
        for widget in [self, *self.findChildren(QWidget)]:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self.dropped_video_path(event) is not None:
                event.acceptProposedAction()
                return True
        if event.type() == QEvent.Type.Drop:
            path = self.dropped_video_path(event)
            if path is not None:
                event.acceptProposedAction()
                QTimer.singleShot(0, lambda p=path: self.load_dropped_video(p))
                return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.dropped_video_path(event) is not None:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self.dropped_video_path(event) is not None:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        path = self.dropped_video_path(event)
        if path is not None:
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda p=path: self.load_dropped_video(p))
            return
        super().dropEvent(event)

    def dropped_video_path(self, event) -> Optional[Path]:
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                return path
        return None

    def load_dropped_video(self, path: Path) -> None:
        self.stop_frame_animation()
        self.frames = []
        self.import_images = []
        self.frame_list.clear()
        self.frame_preview.setText("尚未擷取 frame")
        self.animation_preview.setText("已勾選 frame 的動畫預覽")
        self.animation_info.setText("尚未播放")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.pages.setCurrentWidget(self.video_page)
        self.update_page_buttons()
        self.load_video(path)

    def _build_video_page(self) -> QWidget:
        page = QWidget()
        self.path_label = QLabel("尚未選擇影片")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        browse_button = QPushButton("選擇影片")
        browse_button.clicked.connect(self.choose_video)

        self.info_label = QLabel("選擇影片後會在這裡顯示資訊")
        self.info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.video_preview = ZoomImageLabel("選擇影片後會自動循環播放選定時間段")
        self.video_preview.setMinimumSize(720, 420)
        self.video_preview.setStyleSheet("background:#111827; color:#e5e7eb;")

        self.range_slider = TimeRangeSlider()
        self.range_slider.rangeChanged.connect(self.on_range_slider_changed)
        self.range_slider.rangeCommitted.connect(self.on_range_slider_committed)
        self.range_slider.playheadChanged.connect(self.on_playhead_dragged)
        self.range_slider.dragStarted.connect(self.begin_range_slider_drag)
        self.range_slider.dragFinished.connect(self.finish_range_slider_drag)

        self.video_play_button = QPushButton("暫停")
        self.video_play_button.clicked.connect(self.toggle_video_playback)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0.0, 86400.0)
        self.start_spin.setDecimals(3)
        self.start_spin.setSingleStep(0.1)
        self.start_spin.setSuffix(" 秒")
        self.start_spin.valueChanged.connect(self.on_time_spin_changed)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.0, 86400.0)
        self.end_spin.setDecimals(3)
        self.end_spin.setSingleStep(0.1)
        self.end_spin.setSuffix(" 秒")
        self.end_spin.valueChanged.connect(self.on_time_spin_changed)

        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0.1, 120.0)
        self.fps_spin.setDecimals(2)
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setValue(12.0)
        self.fps_spin.setSuffix(" FPS")

        self.thumb_size = QSpinBox()
        self.thumb_size.setRange(48, 240)
        self.thumb_size.setValue(96)
        self.thumb_size.setSingleStep(16)
        self.thumb_size.valueChanged.connect(self.refresh_frame_list)

        extract_button = QPushButton("擷取 frame")
        extract_button.clicked.connect(self.extract_preview)

        settings = QFormLayout()
        settings.addRow("開始時間", self.start_spin)
        settings.addRow("結束時間", self.end_spin)
        settings.addRow("目標 FPS", self.fps_spin)
        settings.addRow("下一頁縮圖大小", self.thumb_size)
        settings.addRow("", extract_button)

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_label, 1)
        path_row.addWidget(browse_button)
        play_row = QHBoxLayout()
        play_row.addWidget(self.video_play_button)
        play_row.addStretch(1)

        layout = QVBoxLayout(page)
        layout.addLayout(path_row)
        layout.addWidget(self.info_label)
        layout.addWidget(self.video_preview, 1)
        layout.addWidget(self.range_slider)
        layout.addLayout(play_row)
        layout.addLayout(settings)
        return page

    def _build_frame_page(self) -> QWidget:
        page = QWidget()
        title = QLabel("選擇要保留的 frame")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        back_button = QPushButton("返回影片設定")
        back_button.clicked.connect(self.show_video_page)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(back_button)

        self.frame_list = FramePickerList()
        self.frame_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.frame_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.frame_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.frame_list.currentRowChanged.connect(self.update_frame_preview)
        self.frame_list.itemChanged.connect(self.on_frame_check_changed)
        self.frame_list.rangeSelectionChanged.connect(self.on_frame_check_changed)
        self.frame_list.zoomRequested.connect(self.zoom_frame_list)

        self.frame_preview = ZoomImageLabel("尚未擷取 frame")
        self.frame_preview.setMinimumSize(360, 300)
        self.frame_preview.setStyleSheet("background:#2d2d2d; color:#f4f4f4;")

        self.animation_preview = ZoomImageLabel("已勾選 frame 的動畫預覽")
        self.animation_preview.setMinimumSize(360, 220)
        self.animation_preview.setStyleSheet("background:#111827; color:#e5e7eb;")
        self.animation_info = QLabel("尚未播放")
        self.animation_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.animation_play_button = QPushButton("播放")
        self.animation_play_button.clicked.connect(self.toggle_frame_animation)
        self.animation_fps_spin = QDoubleSpinBox()
        self.animation_fps_spin.setRange(0.1, 60.0)
        self.animation_fps_spin.setValue(24.0)
        self.animation_fps_spin.setDecimals(2)
        self.animation_fps_spin.setSuffix(" FPS")
        self.animation_fps_spin.valueChanged.connect(self.update_animation_timer_interval)
        self.animation_loop = QCheckBox("循環播放")
        self.animation_loop.setChecked(True)
        self.animation_progress = QSlider(Qt.Orientation.Horizontal)
        self.animation_progress.setRange(0, 0)
        self.animation_progress.sliderMoved.connect(self.seek_frame_animation)

        animation_controls = QHBoxLayout()
        animation_controls.addWidget(self.animation_play_button)
        animation_controls.addWidget(self.animation_fps_spin)
        animation_controls.addWidget(self.animation_loop)
        animation_controls.addStretch(1)

        animation_panel = QWidget()
        animation_layout = QVBoxLayout(animation_panel)
        animation_layout.addWidget(QLabel("動畫預覽"))
        animation_layout.addWidget(self.animation_preview, 1)
        animation_layout.addWidget(self.animation_progress)
        animation_layout.addLayout(animation_controls)
        animation_layout.addWidget(self.animation_info)

        single_panel = QWidget()
        single_layout = QVBoxLayout(single_panel)
        single_layout.addWidget(QLabel("單張預覽"))
        single_layout.addWidget(self.frame_preview, 1)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.addWidget(animation_panel)
        top_splitter.addWidget(single_panel)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top_splitter)
        splitter.addWidget(self.frame_list)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(page)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)
        return page

    def show_video_page(self) -> None:
        self.stop_frame_animation()
        self.pages.setCurrentWidget(self.video_page)
        self.start_video_preview()
        self.update_page_buttons()

    def show_frame_page(self) -> None:
        self.stop_video_preview()
        self.stop_frame_animation()
        self.pages.setCurrentWidget(self.frame_page)
        self.update_page_buttons()
        self.show_animation_frame(0)

    def update_page_buttons(self) -> None:
        on_frame_page = self.pages.currentWidget() is self.frame_page
        for button in (self.select_all_button, self.select_none_button, self.invert_button, self.save_png_button, self.import_editor_button):
            button.setVisible(on_frame_page)

    def choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇影片",
            str(Path.home()),
            "Videos (*.mp4 *.mov *.avi *.webm *.mkv);;All Files (*.*)",
        )
        if not path:
            return
        self.load_video(Path(path))

    def load_video(self, path: Path) -> bool:
        try:
            self.metadata = read_video_metadata(path)
        except ValueError as exc:
            QMessageBox.warning(self, "無法讀取影片", str(exc))
            return False
        self.video_path = path
        self.path_label.setText(str(self.video_path))
        duration = max(0.001, self.metadata.duration)
        self.range_slider.setDuration(duration)
        self.range_slider.setRangeValues(0.0, duration)
        self._syncing_range = True
        self.start_spin.setMaximum(max(1.0, duration))
        self.end_spin.setMaximum(max(1.0, duration))
        self.start_spin.setValue(0.0)
        self.end_spin.setValue(duration)
        self._syncing_range = False
        self.fps_spin.setValue(12.0)
        self.info_label.setText(
            f"{self.metadata.width} x {self.metadata.height} / "
            f"{self.metadata.fps:.2f} FPS / {self.metadata.frame_count} frames / "
            f"{self.metadata.duration:.3f} 秒"
        )
        self.start_video_preview()
        return True

    def start_video_preview(self) -> None:
        self.stop_video_preview()
        if self.video_path is None:
            return
        self.preview_capture = cv2.VideoCapture(str(self.video_path))
        if not self.preview_capture.isOpened():
            self.preview_capture = None
            self.video_preview.setText("無法播放影片預覽")
            return
        self.seek_preview_to_start(immediate=True)
        interval = 33
        if self.metadata and self.metadata.fps > 0:
            interval = max(15, min(100, round(1000 / self.metadata.fps)))
        self.play_timer.start(interval)
        self.preview_playing = True
        self.update_video_play_button()

    def stop_video_preview(self) -> None:
        self.play_timer.stop()
        self.seek_timer.stop()
        self.preview_playing = False
        self.update_video_play_button()
        if self.preview_capture is not None:
            self.preview_capture.release()
            self.preview_capture = None

    def preview_interval_ms(self) -> int:
        if self.metadata and self.metadata.fps > 0:
            return max(15, min(100, round(1000 / self.metadata.fps)))
        return 33

    def begin_range_slider_drag(self) -> None:
        self._slider_dragging = True
        self._resume_video_after_slider_drag = self.preview_playing or self.play_timer.isActive()
        self.seek_timer.stop()
        self.play_timer.stop()
        if self._resume_video_after_slider_drag:
            self.preview_playing = False
            self.update_video_play_button()

    def finish_range_slider_drag(self) -> None:
        resume_playback = self._resume_video_after_slider_drag
        self._slider_dragging = False
        self._resume_video_after_slider_drag = False
        if resume_playback and self.preview_capture is not None:
            self.play_timer.start(self.preview_interval_ms())
            self.preview_playing = True
        self.update_video_play_button()

    def seek_preview_to_start(self, immediate: bool = False) -> None:
        if immediate:
            self.seek_preview_to(self.range_slider.start_value)
        else:
            self.schedule_preview_seek(self.range_slider.start_value)

    def schedule_preview_seek(self, value: float) -> None:
        self._pending_seek_value = max(self.range_slider.start_value, min(float(value), self.range_slider.end_value))
        self.range_slider.setPlayhead(self._pending_seek_value)
        if self._slider_dragging:
            return
        self.seek_timer.start(45)

    def apply_pending_seek(self) -> None:
        self.seek_preview_to(self._pending_seek_value)

    def seek_preview_to(self, value: float) -> None:
        value = max(self.range_slider.start_value, min(float(value), self.range_slider.end_value))
        was_playing = self.preview_playing
        self.play_timer.stop()
        if self.preview_capture is not None:
            self.preview_capture.set(cv2.CAP_PROP_POS_MSEC, value * 1000.0)
            ok, frame = self.preview_capture.read()
            if not ok or frame is None:
                self.preview_capture.release()
                self.preview_capture = cv2.VideoCapture(str(self.video_path)) if self.video_path else None
                if self.preview_capture is not None and self.preview_capture.isOpened():
                    self.preview_capture.set(cv2.CAP_PROP_POS_MSEC, value * 1000.0)
                    ok, frame = self.preview_capture.read()
            if ok and frame is not None:
                self.current_video_image = cv_frame_to_qimage(frame)
                self.show_video_image()
                self.preview_capture.set(cv2.CAP_PROP_POS_MSEC, value * 1000.0)
        self.range_slider.setPlayhead(value)
        if was_playing and self.preview_capture is not None:
            interval = 33
            if self.metadata and self.metadata.fps > 0:
                interval = max(15, min(100, round(1000 / self.metadata.fps)))
            self.play_timer.start(interval)

    def toggle_video_playback(self) -> None:
        if self.video_path is None:
            return
        if self.preview_capture is None:
            self.start_video_preview()
            return
        if self.preview_playing:
            self.play_timer.stop()
            self.preview_playing = False
        else:
            self.play_timer.start(self.preview_interval_ms())
            self.preview_playing = True
        self.update_video_play_button()

    def update_video_play_button(self) -> None:
        if hasattr(self, "video_play_button"):
            self.video_play_button.setText("暫停" if self.preview_playing else "播放")

    def on_playhead_dragged(self, value: float) -> None:
        if self._slider_dragging:
            self.seek_preview_to(value)
        else:
            self.schedule_preview_seek(value)

    def advance_video_preview(self) -> None:
        if self.preview_capture is None:
            return
        current_time = float(self.preview_capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        if current_time < self.range_slider.start_value - 0.001 or current_time > self.range_slider.end_value + 0.001:
            self.seek_preview_to(self.range_slider.start_value)

        ok, frame = self.preview_capture.read()
        if not ok or frame is None:
            self.seek_preview_to(self.range_slider.start_value)
            ok, frame = self.preview_capture.read()
            if not ok or frame is None:
                return

        timestamp = float(self.preview_capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        if timestamp > self.range_slider.end_value + 0.001:
            self.seek_preview_to(self.range_slider.start_value)
            ok, frame = self.preview_capture.read()
            if not ok or frame is None:
                return
            timestamp = float(self.preview_capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0

        self.range_slider.setPlayhead(timestamp)
        self.current_video_image = cv_frame_to_qimage(frame)
        self.show_video_image()

    def show_video_image(self) -> None:
        if self.current_video_image is None:
            return
        self.video_preview.setImage(self.current_video_image)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.show_video_image()
        current_row = self.frame_list.currentRow()
        if current_row >= 0:
            self.update_frame_preview(current_row)
        self.show_animation_frame(self.animation_index)

    def on_range_slider_changed(self, start: float, end: float) -> None:
        if self._syncing_range:
            return
        self._syncing_range = True
        self.start_spin.setValue(start)
        self.end_spin.setValue(end)
        self._syncing_range = False

    def on_range_slider_committed(self, start: float, end: float) -> None:
        if self._slider_dragging:
            self.seek_preview_to(start)
        else:
            self.schedule_preview_seek(start)

    def on_time_spin_changed(self) -> None:
        if self._syncing_range:
            return
        start = self.start_spin.value()
        end = self.end_spin.value()
        sender = self.sender()
        if start > end:
            if sender is self.start_spin:
                end = start
            else:
                start = end
        self._syncing_range = True
        self.start_spin.setValue(start)
        self.end_spin.setValue(end)
        self.range_slider.setRangeValues(start, end)
        self._syncing_range = False
        self.schedule_preview_seek(start)

    def extract_preview(self) -> None:
        if self.video_path is None:
            QMessageBox.information(self, "尚未選擇影片", "請先選擇影片檔。")
            return
        start = self.start_spin.value()
        end = self.end_spin.value()
        if end <= start:
            QMessageBox.warning(self, "時間區間錯誤", "結束時間必須大於開始時間。")
            return
        self.frame_list.clear()
        self.frame_preview.setText("正在擷取...")
        self.animation_preview.setText("已勾選 frame 的動畫預覽")
        self.animation_info.setText("尚未播放")
        self.progress.setRange(0, 0)
        self.worker = VideoExtractWorker(self.video_path, start, end, self.fps_spin.value())
        self.worker.signals.progress.connect(self.on_extract_progress)
        self.worker.signals.finished.connect(self.on_extract_finished)
        self.worker.signals.failed.connect(self.on_extract_failed)
        self.thread_pool.start(self.worker)

    def on_extract_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def on_extract_finished(self, frames: list) -> None:
        self.frames = list(frames)
        self.progress.setRange(0, max(1, len(self.frames)))
        self.progress.setValue(len(self.frames))
        self.refresh_frame_list()
        if self.frames:
            self.frame_list.setCurrentRow(0)
            self.show_frame_page()
        else:
            self.frame_preview.setText("沒有擷取到 frame")

    def on_extract_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.frame_preview.setText("擷取失敗")
        QMessageBox.warning(self, "擷取失敗", message)

    def refresh_frame_list(self) -> None:
        checked = {self.frame_list.item(row).data(Qt.ItemDataRole.UserRole): self.frame_list.item(row).checkState() for row in range(self.frame_list.count())}
        self.frame_list.clear()
        size = self.thumb_size.value()
        self.frame_list.setIconSize(QPixmap(size, size).size())
        for index, frame in enumerate(self.frames):
            pixmap = QPixmap.fromImage(frame.image).scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            item = QListWidgetItem(QIcon(pixmap), str(index + 1))
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(checked.get(index, Qt.CheckState.Checked))
            self.frame_list.addItem(item)

    def update_frame_preview(self, row: int) -> None:
        if row < 0 or row >= len(self.frames):
            return
        frame = self.frames[row]
        self.frame_preview.setImage(frame.image)
        self.frame_preview.setToolTip(f"Frame {row + 1} / {frame.timestamp:.3f}s / source #{frame.source_index}")

    def on_frame_check_changed(self, *args) -> None:
        selected = self.selected_frames()
        if not selected:
            self.stop_frame_animation()
            self.animation_preview.setText("沒有已勾選 frame")
            self.animation_info.setText("0 frames")
            self.animation_progress.setRange(0, 0)
            return
        self.animation_index = min(self.animation_index, len(selected) - 1)
        self.show_animation_frame(self.animation_index)

    def toggle_frame_animation(self) -> None:
        selected = self.selected_frames()
        if not selected:
            QMessageBox.information(self, "沒有選擇 frame", "請先勾選至少一個 frame。")
            return
        if self.frame_animation_timer.isActive():
            self.stop_frame_animation()
        else:
            self.update_animation_timer_interval()
            self.frame_animation_timer.start()
            self.animation_play_button.setText("暫停")
            self.show_animation_frame(self.animation_index)

    def stop_frame_animation(self) -> None:
        self.frame_animation_timer.stop()
        if hasattr(self, "animation_play_button"):
            self.animation_play_button.setText("播放")

    def update_animation_timer_interval(self) -> None:
        if not hasattr(self, "animation_fps_spin"):
            return
        interval = max(16, round(1000 / max(0.1, self.animation_fps_spin.value())))
        self.frame_animation_timer.setInterval(interval)

    def seek_frame_animation(self, value: int) -> None:
        self.animation_index = max(0, value)
        self.show_animation_frame(self.animation_index)

    def advance_frame_animation(self) -> None:
        selected = self.selected_frames()
        if not selected:
            self.stop_frame_animation()
            return
        self.animation_index += 1
        if self.animation_index >= len(selected):
            if self.animation_loop.isChecked():
                self.animation_index = 0
            else:
                self.animation_index = len(selected) - 1
                self.stop_frame_animation()
        self.show_animation_frame(self.animation_index)

    def show_animation_frame(self, index: int) -> None:
        if not hasattr(self, "animation_preview"):
            return
        selected = self.selected_frames()
        if not selected:
            self.animation_preview.setText("沒有已勾選 frame")
            self.animation_info.setText("0 frames")
            return
        self.animation_index = max(0, min(index, len(selected) - 1))
        frame = selected[self.animation_index]
        self.animation_preview.setImage(frame.image)
        self.animation_progress.blockSignals(True)
        self.animation_progress.setRange(0, max(0, len(selected) - 1))
        self.animation_progress.setValue(self.animation_index)
        self.animation_progress.blockSignals(False)
        self.animation_info.setText(
            f"{self.animation_index + 1}/{len(selected)}  "
            f"time={frame.timestamp:.3f}s  source=#{frame.source_index}  "
            f"speed={self.animation_fps_spin.value():.2f} FPS"
        )

    def zoom_frame_list(self, delta: int) -> None:
        self.thumb_size.setValue(max(self.thumb_size.minimum(), min(self.thumb_size.maximum(), self.thumb_size.value() + delta)))

    def selected_frames(self) -> List[ExtractedVideoFrame]:
        selected: List[ExtractedVideoFrame] = []
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            index = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked and index is not None:
                selected.append(self.frames[index])
        return selected

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.frame_list.count()):
            self.frame_list.item(row).setCheckState(state)

    def invert_selection(self) -> None:
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def save_selected_pngs(self) -> None:
        selected = self.selected_frames()
        if not selected:
            QMessageBox.information(self, "沒有選擇 frame", "請先勾選至少一個 frame。")
            return
        directory = QFileDialog.getExistingDirectory(self, "選擇儲存資料夾", str(Path.home()))
        if not directory:
            return
        output_dir = Path(directory)
        zip_path = output_dir / "matted_frames.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for index, frame in enumerate(selected, 1):
                    png_data = QByteArray()
                    buffer = QBuffer(png_data)
                    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                        raise OSError("Cannot create PNG buffer.")
                    if not frame.image.save(buffer, "PNG"):
                        buffer.close()
                        raise OSError(f"Cannot encode matte_{index:05d}.png.")
                    buffer.close()
                    archive.writestr(f"matte_{index:05d}.png", bytes(png_data))
        except OSError as exc:
            QMessageBox.warning(self, "儲存失敗", str(exc))
            return
        QMessageBox.information(self, "儲存完成", f"已儲存 {len(selected)} 張 PNG 到 {zip_path.name}。")

    def accept_for_import(self) -> None:
        selected = self.selected_frames()
        if not selected:
            QMessageBox.information(self, "沒有選擇 frame", "請先勾選至少一個 frame。")
            return
        self.import_images = [frame.image.copy() for frame in selected]
        self.accept()

    def accept_for_editor_switch(self) -> None:
        self.switch_to_editor = True
        self.import_images = []
        self.accept()

    def accept(self) -> None:
        self.stop_video_preview()
        self.stop_frame_animation()
        super().accept()

    def reject(self) -> None:
        self.stop_video_preview()
        self.stop_frame_animation()
        super().reject()

    def closeEvent(self, event) -> None:
        self.stop_video_preview()
        self.stop_frame_animation()
        super().closeEvent(event)
