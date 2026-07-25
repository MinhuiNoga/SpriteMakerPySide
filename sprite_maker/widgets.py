from __future__ import annotations

import math
from typing import List, Optional

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QMouseEvent, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QListWidget, QWidget

from .image_ops import erase_color, flood_fill, qcolor_to_rgba, qimage_to_array
from .models import Frame


class FrameStripWidget(QListWidget):
    frames_reordered = Signal(object, int)

    def __init__(self) -> None:
        super().__init__()
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_row = -1
        self._drag_rows: List[int] = []
        self._drop_row = -1
        self._is_dragging = False
        self._pulse = 0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self.setMouseTracking(True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self._drag_row = self.row(self.itemAt(event.pos()))
            self._drop_row = self._drag_row
            self._is_dragging = False
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            selected_rows = sorted(index.row() for index in self.selectedIndexes())
            self._drag_rows = selected_rows if self._drag_row in selected_rows else [self._drag_row]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start_pos is not None and self._drag_row >= 0:
            distance = (event.pos() - self._drag_start_pos).manhattanLength()
            if distance > 8:
                self._is_dragging = True
                self._pulse_timer.start(90)
                self._drop_row = self._row_from_position(event.pos())
                self.viewport().update()
                return
        if self._is_dragging:
            self._drop_row = self._row_from_position(event.pos())
            self.viewport().update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            rows = [row for row in self._drag_rows if row >= 0]
            drop_row = self._drop_row
            self._reset_drag()
            if rows and drop_row >= 0:
                self.frames_reordered.emit(rows, drop_row)
            return
        self._reset_drag()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if not self._is_dragging:
            self._drop_row = -1
            self.viewport().update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._is_dragging or self._drop_row < 0:
            return
        painter = QPainter(self.viewport())
        color = QColor(76, 175, 80, 180 + (self._pulse % 2) * 60)
        painter.setPen(QPen(color, 4))
        rect = self._drop_indicator_rect(self._drop_row)
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        painter.fillRect(rect.adjusted(-3, 0, 3, 0), QColor(76, 175, 80, 60))
        painter.end()

    def _tick_pulse(self) -> None:
        self._pulse = (self._pulse + 1) % 2
        self.viewport().update()

    def _row_from_position(self, pos: QPoint) -> int:
        item = self.itemAt(pos)
        if item is None:
            return self.count()
        row = self.row(item)
        rect = self.visualItemRect(item)
        if self.viewMode() == QListWidget.ViewMode.IconMode:
            return row + (1 if pos.x() > rect.center().x() else 0)
        return row + (1 if pos.y() > rect.center().y() else 0)

    def _drop_indicator_rect(self, row: int):
        if self.count() == 0:
            return QRectF(8, 8, 4, max(40, self.viewport().height() - 16)).toRect()
        if row >= self.count():
            rect = self.visualItemRect(self.item(self.count() - 1))
            return QRectF(rect.right() + 8, rect.top(), 4, rect.height()).toRect()
        rect = self.visualItemRect(self.item(row))
        return QRectF(rect.left() - 5, rect.top(), 4, rect.height()).toRect()

    def _reset_drag(self) -> None:
        self._drag_start_pos = None
        self._drag_row = -1
        self._drag_rows = []
        self._drop_row = -1
        self._is_dragging = False
        self._pulse_timer.stop()
        self.viewport().update()


class CanvasWidget(QWidget):
    editing_started = Signal()
    image_changed = Signal()
    frame_erase_requested = Signal(int, int)
    universal_erase_requested = Signal(int, int)
    color_sampled = Signal(QColor)
    status_changed = Signal(str)
    zoom_changed = Signal(float)
    workspace_expansion_requested = Signal(int, int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.frame: Optional[Frame] = None
        self.tool = "pen"
        self.brush_size = 8
        self.tolerance = 15
        self.color = QColor("#ff0000")
        self.pixel_blend_enabled = False
        self.pixel_blend_strength = 0.75
        self.pixel_blend_edge_width = 2
        self.pixel_blend_sample_radius = 5
        self.pixel_blend_sample_visible_layers = True
        self.pixel_blend_include_transparent = False
        self._brush_source_array: Optional[np.ndarray] = None
        self._brush_fallback_source_array: Optional[np.ndarray] = None
        self._brush_base_layer_array: Optional[np.ndarray] = None
        self._brush_stroke_mask: Optional[np.ndarray] = None
        self._brush_edge_factor: Optional[np.ndarray] = None
        self._brush_blended_mask: Optional[np.ndarray] = None
        self.zoom = 1.0
        self.show_axes = False
        self.bg_color = QColor("#808080")
        self.show_checker_bg = True
        self.export_size: Optional[QSize] = None
        self.debug_overlay_image: Optional[QImage] = None
        self._drawing = False
        self._last_pos: Optional[QPoint] = None
        self._hover_pos: Optional[QPoint] = None
        self._image_rect = QRectF()
        self._selecting = False
        self._selection_start: Optional[QPoint] = None
        self.selection_rect: Optional[QRect] = None
        self.lasso_points: List[QPoint] = []
        self.clipboard_image: Optional[QImage] = None
        self.floating_image: Optional[QImage] = None
        self.batch_selection_frames: List[Frame] = []
        self.batch_floating_images: List[tuple[Frame, QImage]] = []
        self.floating_pos = QPointF(0, 0)
        self.floating_rotation = 0.0
        self.floating_flip_x = False
        self.floating_flip_y = False
        self.floating_scale_x = 1.0
        self.floating_scale_y = 1.0
        self.smooth_selection_transform = True
        self._dragging_floating = False
        self._floating_drag_offset = QPointF(0, 0)
        self._rotating_floating = False
        self._rotation_start_angle = 0.0
        self._rotation_start_center = QPointF(0, 0)
        self._rotation_start_vector = QPointF(1, 0)
        self._rotation_workspace_offset = QPointF(0, 0)
        self._resizing_floating = False
        self._resize_handle = ""
        self._resize_start_scale = (1.0, 1.0)
        self._resize_start_distance = QPointF(1.0, 1.0)
        self._resize_start_inverse = QTransform()
        self._resize_workspace_offset = QPointF(0, 0)
        self.setMinimumSize(760, 520)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._update_cursor()

    def set_frame(self, frame: Optional[Frame]) -> None:
        self.frame = frame
        self._drawing = False
        self._last_pos = None
        self._clear_brush_stroke_state()
        self._dragging_floating = False
        self._resizing_floating = False
        self._rotating_floating = False
        self._resize_workspace_offset = QPointF(0, 0)
        self._rotation_workspace_offset = QPointF(0, 0)
        self.floating_image = None
        self.batch_floating_images = []
        self.selection_rect = None
        self.lasso_points = []
        self.debug_overlay_image = None
        self.updateGeometry()
        self.update()

    def set_batch_selection_frames(self, frames: List[Frame]) -> None:
        unique_frames: List[Frame] = []
        seen = set()
        for frame in frames:
            identity = id(frame)
            if identity not in seen:
                seen.add(identity)
                unique_frames.append(frame)
        self.batch_selection_frames = unique_frames

    def selection_target_frames(self) -> List[Frame]:
        if not self.frame:
            return []
        targets = list(self.batch_selection_frames)
        if not any(frame is self.frame for frame in targets):
            targets.insert(0, self.frame)
        return targets

    def shift_workspace_coordinates(self, dx: int, dy: int) -> None:
        if self.selection_rect is not None:
            self.selection_rect.translate(dx, dy)
        if self.lasso_points:
            self.lasso_points = [QPoint(point.x() + dx, point.y() + dy) for point in self.lasso_points]
        if self.floating_image is not None:
            self.floating_pos += QPointF(dx, dy)
        if hasattr(self, "clipboard_pos"):
            self.clipboard_pos += QPoint(dx, dy)
        if self._selection_start is not None:
            self._selection_start += QPoint(dx, dy)
        if self._last_pos is not None:
            self._last_pos += QPoint(dx, dy)
        if self._hover_pos is not None:
            self._hover_pos += QPoint(dx, dy)
        if self._resizing_floating:
            self._resize_workspace_offset += QPointF(dx, dy)
        if self._rotating_floating:
            self._rotation_workspace_offset += QPointF(dx, dy)
        self._expand_brush_stroke_state(dx, dy)
        self.sync_image_rect_to_workspace()
        self.updateGeometry()
        self.update()

    def set_tool(self, tool: str) -> None:
        if tool not in {"select", "lasso"}:
            self.commit_floating_selection()
        if tool != self.tool:
            self._clear_brush_stroke_state()
        self.tool = tool
        self._update_cursor()
        self.status_changed.emit(f"工具：{tool}")

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.1, min(8.0, zoom))
        self.updateGeometry()
        self.zoom_changed.emit(self.zoom)
        self.update()

    def set_export_size(self, size: Optional[QSize]) -> None:
        self.export_size = size
        self.updateGeometry()
        self.update()

    def set_debug_overlay(self, image: Optional[QImage]) -> None:
        self.debug_overlay_image = image.copy() if image is not None and not image.isNull() else None
        self.update()

    def sizeHint(self):
        if not self.frame:
            return super().sizeHint()
        center_x, center_y = self.frame.export_center
        horizontal_extent = max(center_x, self.frame.width - center_x)
        vertical_extent = max(center_y, self.frame.height - center_y)
        if self.export_size is not None:
            horizontal_extent = max(horizontal_extent, self.export_size.width() / 2)
            vertical_extent = max(vertical_extent, self.export_size.height() / 2)
        return QSize(int(horizontal_extent * 2 * self.zoom + 220), int(vertical_extent * 2 * self.zoom + 220))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if getattr(self, "show_checker_bg", False):
            self._paint_checker(painter)
        else:
            painter.fillRect(self.rect(), self.bg_color)

        if not self.frame:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "請匯入 PNG/JPG 開始")
            painter.end()
            return

        image = self.frame.composite()
        draw_w = image.width() * self.zoom
        draw_h = image.height() * self.zoom
        export_w = self.export_size.width() * self.zoom if self.export_size else draw_w
        export_h = self.export_size.height() * self.zoom if self.export_size else draw_h
        export_center_x, export_center_y = self.frame.export_center
        self.sync_image_rect_to_workspace()
        output_rect = QRectF(
            self._image_rect.left() + export_center_x * self.zoom - export_w / 2,
            self._image_rect.top() + export_center_y * self.zoom - export_h / 2,
            export_w,
            export_h,
        )

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.save()
        painter.setPen(QPen(QColor("#050505"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(output_rect)
        painter.restore()
        painter.drawImage(self._image_rect, image)
        if self.debug_overlay_image is not None and not self.debug_overlay_image.isNull():
            painter.drawImage(self._image_rect, self.debug_overlay_image)
        self._paint_floating_selection(painter)
        self._paint_selection_overlay(painter)
        self._paint_brush_preview(painter)

        if self.show_axes:
            painter.setPen(QPen(QColor(255, 255, 255, 160), 1, Qt.PenStyle.DashLine))
            cx = self._image_rect.left() + export_center_x * self.zoom
            cy = self._image_rect.top() + export_center_y * self.zoom
            painter.drawLine(QPointF(cx, self._image_rect.top()), QPointF(cx, self._image_rect.bottom()))
            painter.drawLine(QPointF(self._image_rect.left(), cy), QPointF(self._image_rect.right(), cy))

        painter.setPen(QPen(QColor("#222"), 1))
        painter.drawRect(self._image_rect)
        painter.end()

    def export_center_view_position(self) -> QPointF:
        if self.frame is None:
            return QPointF(self.width() / 2, self.height() / 2)
        center_x, center_y = self.frame.export_center
        left = self.width() / 2.0 - center_x * self.zoom
        top = self.height() / 2.0 - center_y * self.zoom
        return QPointF(left + center_x * self.zoom, top + center_y * self.zoom)

    def sync_image_rect_to_workspace(self) -> None:
        if self.frame is None:
            self._image_rect = QRectF()
            return
        center_x, center_y = self.frame.export_center
        self._image_rect = QRectF(
            self.width() / 2.0 - center_x * self.zoom,
            self.height() / 2.0 - center_y * self.zoom,
            self.frame.width * self.zoom,
            self.frame.height * self.zoom,
        )

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 0.15 if event.angleDelta().y() > 0 else -0.15
            self.set_zoom(self.zoom + delta)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.frame:
            return
        self.setFocus()
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            pos = self._event_to_image_pos(event)
            if pos is not None:
                self._sample_color(pos)
            return
        resize_handle = self._resize_handle_hit(event.position())
        if resize_handle:
            if self.floating_image is None and (self.selection_rect or self.lasso_points):
                self.cut_selection()
            if self.floating_image is not None:
                self._resizing_floating = True
                self._resize_handle = resize_handle
                self._resize_start_scale = (self.floating_scale_x, self.floating_scale_y)
                self._resize_start_inverse = self._floating_transform().inverted()[0]
                self._resize_workspace_offset = QPointF(0, 0)
                local = self._resize_start_inverse.map(self._view_to_image_point(event.position()))
                center = QPointF(self.floating_image.width() / 2, self.floating_image.height() / 2)
                self._resize_start_distance = QPointF(max(1.0, abs(local.x() - center.x())), max(1.0, abs(local.y() - center.y())))
                self.status_changed.emit("拖曳縮放控制點")
            return
        if self._rotation_handle_hit(event.position()):
            if self.floating_image is None and (self.selection_rect or self.lasso_points):
                self.cut_selection()
            if self.floating_image is not None:
                self._rotating_floating = True
                center = self._floating_center_image()
                mouse = self._view_to_image_point(event.position())
                self._rotation_start_angle = self.floating_rotation
                self._rotation_start_center = QPointF(center)
                self._rotation_start_vector = mouse - center
                self._rotation_workspace_offset = QPointF(0, 0)
                self.status_changed.emit("拖曳旋轉控制點")
            return
        if self.tool in {"select", "lasso"} and (
            self.floating_image is not None or self.has_active_selection()
        ):
            selection_pos = self._event_to_image_pos(event)
            point_is_inside = (
                selection_pos is not None
                and (
                    self._point_in_floating(selection_pos)
                    if self.floating_image is not None
                    else self._point_in_selection(selection_pos)
                )
            )
            if not point_is_inside:
                self.finish_active_selection()
                return
        allow_expansion = self.floating_image is not None or self.tool in {"pen", "eraser", "fill", "select", "lasso"}
        pos = self._event_to_image_pos(event, allow_expansion=allow_expansion)
        if pos is None:
            return

        if self.floating_image is not None and self._point_in_floating(pos):
            self._dragging_floating = True
            self._floating_drag_offset = QPointF(pos) - self.floating_pos
            self.status_changed.emit("拖曳浮動選取")
            return

        if self.tool in {"select", "lasso"} and self._point_in_selection(pos):
            if self.cut_selection():
                self._dragging_floating = True
                self._floating_drag_offset = QPointF(pos) - self.floating_pos
                self.status_changed.emit("拖曳選取內容")
            return

        if self.tool in {"pen", "eraser"}:
            self.commit_floating_selection()
            self.editing_started.emit()
            self._drawing = True
            self._last_pos = pos
            self._begin_brush_stroke()
            self._draw_line(pos, pos)
        elif self.tool == "fill":
            self.commit_floating_selection()
            self.editing_started.emit()
            layer = self.frame.active_layer
            if len(self.lasso_points) >= 3 and self._point_in_selection(pos):
                self._fill_lasso_selection(layer.image)
                self._finish_edit("已填滿繩索選取")
            else:
                layer.image = flood_fill(
                    layer.image,
                    pos.x(),
                    pos.y(),
                    self.color,
                    self.tolerance,
                    self.selection_mask_image(),
                )
                self._finish_edit("已填色")
        elif self.tool == "wand":
            self.commit_floating_selection()
            self.editing_started.emit()
            layer = self.frame.active_layer
            layer.image = erase_color(
                layer.image,
                qcolor_to_rgba(self.color),
                self.tolerance,
                contiguous=True,
                start_x=pos.x(),
                start_y=pos.y(),
            )
            self._finish_edit("已擦除相鄰色域")
        elif self.tool == "global_wand":
            self.commit_floating_selection()
            self.frame_erase_requested.emit(pos.x(), pos.y())
        elif self.tool == "universal_wand":
            self.commit_floating_selection()
            self.universal_erase_requested.emit(pos.x(), pos.y())
        elif self.tool == "select":
            self._selecting = True
            self._selection_start = pos
            self.selection_rect = QRect(pos, pos)
            self.lasso_points = []
            self.update()
        elif self.tool == "lasso":
            self._selecting = True
            self.selection_rect = None
            self.lasso_points = [pos]
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        allow_expansion = self._drawing or self._dragging_floating or self._selecting
        self._hover_pos = self._event_to_image_pos(event, allow_expansion=allow_expansion)
        self._update_cursor()
        if self._resizing_floating and self.floating_image is not None:
            mouse = self._view_to_image_point(event.position()) - self._resize_workspace_offset
            local = self._resize_start_inverse.map(mouse)
            center = QPointF(self.floating_image.width() / 2, self.floating_image.height() / 2)
            dx = max(1.0, abs(local.x() - center.x()))
            dy = max(1.0, abs(local.y() - center.y()))
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                start_radius = math.hypot(
                    self._resize_start_distance.x(),
                    self._resize_start_distance.y(),
                )
                current_radius = math.hypot(dx, dy)
                ratio = current_radius / max(1.0, start_radius)
                sx = max(0.05, self._resize_start_scale[0] * ratio)
                sy = max(0.05, self._resize_start_scale[1] * ratio)
            else:
                sx = max(0.05, self._resize_start_scale[0] * dx / self._resize_start_distance.x())
                sy = max(0.05, self._resize_start_scale[1] * dy / self._resize_start_distance.y())
            self.floating_scale_x = sx
            self.floating_scale_y = sy
            self.ensure_floating_within_workspace()
            self.status_changed.emit(f"浮動選取縮放：{self.floating_scale_x:.2f} x {self.floating_scale_y:.2f}")
            self.update()
            return
        if self._rotating_floating and self.floating_image is not None:
            mouse = self._view_to_image_point(event.position()) - self._rotation_workspace_offset
            current_vector = mouse - self._rotation_start_center
            cross = (
                self._rotation_start_vector.x() * current_vector.y()
                - self._rotation_start_vector.y() * current_vector.x()
            )
            dot = (
                self._rotation_start_vector.x() * current_vector.x()
                + self._rotation_start_vector.y() * current_vector.y()
            )
            angle_delta = math.degrees(math.atan2(cross, dot))
            self.floating_rotation = (self._rotation_start_angle + angle_delta) % 360.0
            self.ensure_floating_within_workspace()
            self.status_changed.emit(f"浮動選取角度：{self.floating_rotation:.1f}°")
            self.update()
            return
        if self._dragging_floating and self.floating_image is not None and self._hover_pos is not None:
            self.floating_pos = QPointF(self._hover_pos) - self._floating_drag_offset
            self.ensure_floating_within_workspace()
            self.update()
            return
        if self._selecting and self.frame and self._hover_pos is not None:
            if self.tool == "select" and self._selection_start is not None:
                self.selection_rect = QRect(self._selection_start, self._hover_pos).normalized()
            elif self.tool == "lasso":
                if not self.lasso_points or (self.lasso_points[-1] - self._hover_pos).manhattanLength() > 1:
                    self.lasso_points.append(self._hover_pos)
            self.update()
            return
        if not self._drawing or not self.frame:
            self.update()
            return
        pos = self._hover_pos
        if pos is None or self._last_pos is None:
            return
        self._draw_line(self._last_pos, pos)
        self._last_pos = pos

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._resizing_floating:
            self._resizing_floating = False
            self._resize_handle = ""
            self._resize_workspace_offset = QPointF(0, 0)
            self.status_changed.emit("已縮放浮動選取")
            self.update()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._rotating_floating:
            self._rotating_floating = False
            self._rotation_workspace_offset = QPointF(0, 0)
            self.status_changed.emit(f"已旋轉到 {self.floating_rotation:.1f}°")
            self.update()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_floating:
            self._dragging_floating = False
            self.status_changed.emit("已移動浮動選取")
            self.update()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            self._normalize_selection()
            self.status_changed.emit("已建立選取範圍")
            self.update()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drawing:
            self._drawing = False
            self._last_pos = None
            blended_pixels = self._brush_blended_pixel_count()
            self._clear_brush_stroke_state()
            if self.tool == "pen" and self.pixel_blend_enabled:
                status = (
                    f"像素融色完成：實際融合 {blended_pixels} 個 pixel"
                    if blended_pixels
                    else "像素融色未命中鄰色：請靠近既有顏色繪製，或開啟透明淡邊"
                )
                self._finish_edit(status)
            else:
                self._finish_edit("已更新圖層")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.finish_active_selection():
            event.accept()
            return
        if event.key() not in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            super().keyPressEvent(event)
            return
        dx = -1 if event.key() == Qt.Key.Key_Left else 1 if event.key() == Qt.Key.Key_Right else 0
        dy = -1 if event.key() == Qt.Key.Key_Up else 1 if event.key() == Qt.Key.Key_Down else 0
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        if self.move_selection_or_floating(dx * step, dy * step):
            event.accept()
            return
        super().keyPressEvent(event)

    def move_selection_or_floating(self, dx: int, dy: int) -> bool:
        if self.floating_image is not None:
            self.floating_pos += QPointF(dx, dy)
            self.ensure_floating_within_workspace()
            self.status_changed.emit(f"已移動浮動選取 {dx}, {dy}")
            self.update()
            return True
        if self.selection_rect:
            self.selection_rect.translate(dx, dy)
            self.status_changed.emit(f"已移動選取框 {dx}, {dy}")
            self.update()
            return True
        if self.lasso_points:
            self.lasso_points = [QPoint(point.x() + dx, point.y() + dy) for point in self.lasso_points]
            self.status_changed.emit(f"已移動繩索選取 {dx}, {dy}")
            self.update()
            return True
        return False

    def leaveEvent(self, event) -> None:
        self._hover_pos = None
        self.update()
        super().leaveEvent(event)

    def _event_to_image_pos(self, event: QMouseEvent, allow_expansion: bool = False) -> Optional[QPoint]:
        if not self.frame or self.zoom <= 0:
            return None
        x = int((event.position().x() - self._image_rect.left()) / self.zoom)
        y = int((event.position().y() - self._image_rect.top()) / self.zoom)
        if allow_expansion and (x < 0 or y < 0 or x >= self.frame.width or y >= self.frame.height):
            left = self._workspace_expansion_amount(-x) if x < 0 else 0
            top = self._workspace_expansion_amount(-y) if y < 0 else 0
            right = self._workspace_expansion_amount(x - self.frame.width + 1) if x >= self.frame.width else 0
            bottom = self._workspace_expansion_amount(y - self.frame.height + 1) if y >= self.frame.height else 0
            self.workspace_expansion_requested.emit(left, top, right, bottom)
            x += left
            y += top
        if x < 0 or y < 0 or x >= self.frame.width or y >= self.frame.height:
            return None
        return QPoint(x, y)

    @staticmethod
    def _workspace_expansion_amount(required: float) -> int:
        padding = 64
        chunk = 128
        return math.ceil(max(padding, required + padding) / chunk) * chunk

    def ensure_floating_within_workspace(self) -> None:
        if self.frame is None or self.floating_image is None:
            return
        bounds = self._floating_transform().mapRect(
            QRectF(0, 0, self.floating_image.width(), self.floating_image.height())
        )
        left = self._workspace_expansion_amount(-bounds.left()) if bounds.left() < 0 else 0
        top = self._workspace_expansion_amount(-bounds.top()) if bounds.top() < 0 else 0
        right = (
            self._workspace_expansion_amount(bounds.right() - self.frame.width)
            if bounds.right() > self.frame.width
            else 0
        )
        bottom = (
            self._workspace_expansion_amount(bounds.bottom() - self.frame.height)
            if bounds.bottom() > self.frame.height
            else 0
        )
        if any((left, top, right, bottom)):
            self.workspace_expansion_requested.emit(left, top, right, bottom)

    def _draw_line(self, start: QPoint, end: QPoint) -> None:
        if not self.frame:
            return
        if (
            self.tool == "pen"
            and self.pixel_blend_enabled
            and self.color.alpha() > 0
        ):
            self._draw_pixel_blend_line(start, end)
            return
        image = self.frame.active_layer.image
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(self.color if self.tool == "pen" else QColor(0, 0, 0, 0), self.brush_size)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if self.tool == "eraser" or (self.tool == "pen" and self.color.alpha() == 0):
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setPen(pen)
        painter.drawLine(start, end)
        painter.end()
        self.frame.mark_dirty()
        self.update()

    def _begin_brush_stroke(self) -> None:
        self._clear_brush_stroke_state()
        if (
            not self.frame
            or self.tool != "pen"
            or not self.pixel_blend_enabled
            or self.color.alpha() <= 0
        ):
            return
        self._brush_base_layer_array = qimage_to_array(self.frame.active_layer.image)
        if self.pixel_blend_sample_visible_layers:
            self._brush_source_array = qimage_to_array(self.frame.composite())
            self._brush_fallback_source_array = None
        else:
            self._brush_source_array = self._brush_base_layer_array
            self._brush_fallback_source_array = (
                qimage_to_array(self.frame.composite()) if len(self.frame.layers) > 1 else None
            )
        shape = (self.frame.height, self.frame.width)
        self._brush_stroke_mask = np.zeros(shape, dtype=bool)
        self._brush_edge_factor = np.zeros(shape, dtype=np.float32)
        self._brush_blended_mask = np.zeros(shape, dtype=bool)

    def _clear_brush_stroke_state(self) -> None:
        self._brush_source_array = None
        self._brush_fallback_source_array = None
        self._brush_base_layer_array = None
        self._brush_stroke_mask = None
        self._brush_edge_factor = None
        self._brush_blended_mask = None

    def _brush_blended_pixel_count(self) -> int:
        return (
            int(np.count_nonzero(self._brush_blended_mask))
            if self._brush_blended_mask is not None
            else 0
        )

    def _expand_brush_stroke_state(self, dx: int, dy: int) -> None:
        if self.frame is None or self._brush_source_array is None:
            return
        new_height = self.frame.height
        new_width = self.frame.width

        def expand_array(array: np.ndarray) -> np.ndarray:
            shape = (new_height, new_width) + array.shape[2:]
            expanded = np.zeros(shape, dtype=array.dtype)
            old_height, old_width = array.shape[:2]
            expanded[dy : dy + old_height, dx : dx + old_width] = array
            return expanded

        shared_layer_source = self._brush_source_array is self._brush_base_layer_array
        self._brush_base_layer_array = expand_array(self._brush_base_layer_array)
        self._brush_source_array = (
            self._brush_base_layer_array
            if shared_layer_source
            else expand_array(self._brush_source_array)
        )
        if self._brush_fallback_source_array is not None:
            self._brush_fallback_source_array = expand_array(self._brush_fallback_source_array)
        self._brush_stroke_mask = expand_array(self._brush_stroke_mask)
        self._brush_edge_factor = expand_array(self._brush_edge_factor)
        self._brush_blended_mask = expand_array(self._brush_blended_mask)

    @staticmethod
    def _qimage_array_view(image: QImage) -> np.ndarray:
        return np.ndarray(
            shape=(image.height(), image.width(), 4),
            dtype=np.uint8,
            buffer=image.bits(),
            strides=(image.bytesPerLine(), 4, 1),
        )

    def _draw_pixel_blend_line(self, start: QPoint, end: QPoint) -> None:
        if not self.frame:
            return
        if self._brush_source_array is None:
            self._begin_brush_stroke()
        if (
            self._brush_source_array is None
            or self._brush_base_layer_array is None
            or self._brush_stroke_mask is None
            or self._brush_edge_factor is None
            or self._brush_blended_mask is None
        ):
            return

        width = self.frame.width
        height = self.frame.height
        radius = max(0.5, self.brush_size / 2.0)
        margin = math.ceil(radius) + 1
        x0 = max(0, min(start.x(), end.x()) - margin)
        y0 = max(0, min(start.y(), end.y()) - margin)
        x1 = min(width, max(start.x(), end.x()) + margin + 1)
        y1 = min(height, max(start.y(), end.y()) + margin + 1)
        if x0 >= x1 or y0 >= y1:
            return

        ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        vx = float(end.x() - start.x())
        vy = float(end.y() - start.y())
        length_sq = vx * vx + vy * vy
        if length_sq <= 0.0:
            nearest_x = np.full_like(xs, float(start.x()))
            nearest_y = np.full_like(ys, float(start.y()))
        else:
            projection = np.clip(
                ((xs - start.x()) * vx + (ys - start.y()) * vy) / length_sq,
                0.0,
                1.0,
            )
            nearest_x = start.x() + projection * vx
            nearest_y = start.y() + projection * vy
        distance = np.sqrt((xs - nearest_x) ** 2 + (ys - nearest_y) ** 2)
        segment_mask = distance <= radius
        if not np.any(segment_mask):
            return

        if self.brush_size <= self.pixel_blend_edge_width * 2:
            segment_factor = np.ones_like(distance, dtype=np.float32)
        else:
            core_radius = max(0.0, radius - float(self.pixel_blend_edge_width))
            segment_factor = np.clip(
                (distance - core_radius) / max(0.5, radius - core_radius),
                0.0,
                1.0,
            ).astype(np.float32)

        stroke_patch = self._brush_stroke_mask[y0:y1, x0:x1]
        factor_patch = self._brush_edge_factor[y0:y1, x0:x1]
        already_stroked = stroke_patch.copy()
        stroke_patch |= segment_mask
        factor_patch[segment_mask & ~already_stroked] = segment_factor[segment_mask & ~already_stroked]
        factor_patch[segment_mask & already_stroked] = np.minimum(
            factor_patch[segment_mask & already_stroked],
            segment_factor[segment_mask & already_stroked],
        )

        target_rgba = np.empty((y1 - y0, x1 - x0, 4), dtype=np.float32)
        brush_rgba = np.array(qcolor_to_rgba(self.color), dtype=np.float32)
        target_rgba[:, :, :] = brush_rgba
        strength = max(0.0, min(1.0, float(self.pixel_blend_strength)))
        blend_amount = np.clip(factor_patch * strength, 0.0, 1.0)
        nearby_rgb, has_visible_color, transparent_fraction = self._pixel_blend_neighbor_patch(
            x0,
            y0,
            x1,
            y1,
        )
        effective_blend = np.where(has_visible_color, blend_amount, 0.0)
        target_rgba[:, :, :3] = (
            brush_rgba[:3] * (1.0 - effective_blend[:, :, None])
            + nearby_rgb * effective_blend[:, :, None]
        )
        if self.pixel_blend_include_transparent:
            target_rgba[:, :, 3] = brush_rgba[3] * (
                1.0 - blend_amount * transparent_fraction
            )
        affected = stroke_patch
        changed_from_solid_brush = (
            np.max(np.abs(target_rgba[:, :, :3] - brush_rgba[:3]), axis=2) >= 0.5
        ) | (np.abs(target_rgba[:, :, 3] - brush_rgba[3]) >= 0.5)
        blended_patch = self._brush_blended_mask[y0:y1, x0:x1]
        blended_patch[affected] = changed_from_solid_brush[affected]

        base = self._brush_base_layer_array[y0:y1, x0:x1][affected].astype(np.float32)
        source = target_rgba[affected]
        source_alpha = source[:, 3:4] / 255.0
        base_alpha = base[:, 3:4] / 255.0
        output_alpha = source_alpha + base_alpha * (1.0 - source_alpha)
        premultiplied_rgb = (
            source[:, :3] * source_alpha
            + base[:, :3] * base_alpha * (1.0 - source_alpha)
        )
        output_rgb = np.divide(
            premultiplied_rgb,
            output_alpha,
            out=np.zeros_like(premultiplied_rgb),
            where=output_alpha > 0.0,
        )
        output = np.concatenate((output_rgb, output_alpha * 255.0), axis=1)

        image_array = self._qimage_array_view(self.frame.active_layer.image)
        image_patch = image_array[y0:y1, x0:x1]
        image_patch[affected] = np.clip(np.rint(output), 0, 255).astype(np.uint8)
        self.frame.mark_dirty()
        self.update()

    def _pixel_blend_neighbor_patch(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._brush_source_array is None or self._brush_stroke_mask is None:
            shape = (max(0, y1 - y0), max(0, x1 - x0))
            return (
                np.zeros(shape + (3,), dtype=np.float32),
                np.zeros(shape, dtype=bool),
                np.zeros(shape, dtype=np.float32),
            )
        radius = max(1, int(self.pixel_blend_sample_radius))
        height, width = self._brush_stroke_mask.shape
        sample_x0 = max(0, x0 - radius)
        sample_y0 = max(0, y0 - radius)
        sample_x1 = min(width, x1 + radius)
        sample_y1 = min(height, y1 + radius)
        available = (~self._brush_stroke_mask[sample_y0:sample_y1, sample_x0:sample_x1]).astype(
            np.float32
        )
        kernel = radius * 2 + 1
        sigma = max(0.5, radius / 2.0)

        def blur(values: np.ndarray) -> np.ndarray:
            return cv2.GaussianBlur(
                values.astype(np.float32),
                (kernel, kernel),
                sigmaX=sigma,
                sigmaY=sigma,
                borderType=cv2.BORDER_CONSTANT,
            )

        def sample_source(source_array: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
            source = source_array[sample_y0:sample_y1, sample_x0:sample_x1]
            alpha = source[:, :, 3].astype(np.float32) / 255.0
            visible_weight = alpha * available
            visible_sum = blur(visible_weight)
            weighted_rgb = blur(source[:, :, :3].astype(np.float32) * visible_weight[:, :, None])
            nearby_rgb = np.divide(
                weighted_rgb,
                visible_sum[:, :, None],
                out=np.zeros_like(weighted_rgb),
                where=visible_sum[:, :, None] > 1e-6,
            )
            available_sum = blur(available)
            transparent_sum = blur((alpha <= 0.0).astype(np.float32) * available)
            transparent_fraction = np.divide(
                transparent_sum,
                available_sum,
                out=np.zeros_like(transparent_sum),
                where=available_sum > 1e-6,
            )
            return nearby_rgb, visible_sum > 1e-6, transparent_fraction

        nearby_rgb, has_visible_color, transparent_fraction = sample_source(
            self._brush_source_array
        )
        if self._brush_fallback_source_array is not None:
            fallback_rgb, fallback_visible, fallback_transparent = sample_source(
                self._brush_fallback_source_array
            )
            use_fallback = ~has_visible_color & fallback_visible
            nearby_rgb[use_fallback] = fallback_rgb[use_fallback]
            transparent_fraction[use_fallback] = fallback_transparent[use_fallback]
            has_visible_color |= fallback_visible

        crop_y0 = y0 - sample_y0
        crop_x0 = x0 - sample_x0
        crop_y1 = crop_y0 + (y1 - y0)
        crop_x1 = crop_x0 + (x1 - x0)
        return (
            nearby_rgb[crop_y0:crop_y1, crop_x0:crop_x1],
            has_visible_color[crop_y0:crop_y1, crop_x0:crop_x1],
            transparent_fraction[crop_y0:crop_y1, crop_x0:crop_x1],
        )

    def _fill_lasso_selection(self, image: QImage) -> None:
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillPath(self._lasso_path(QPoint(0, 0)), self.color)
        painter.end()

    def copy_selection(self) -> bool:
        image = self._selection_to_image()
        if image is None:
            self.status_changed.emit("沒有可複製的選取範圍")
            return False
        self.clipboard_image = image
        self.clipboard_pos = self._selection_bounds().topLeft()
        self.status_changed.emit("已複製選取")
        return True

    def cut_selection(self) -> bool:
        if not self.frame:
            return False
        bounds = self._selection_bounds()
        if bounds.isNull() or bounds.width() <= 0 or bounds.height() <= 0:
            self.status_changed.emit("沒有可剪下的選取範圍")
            return False
        targets = self.selection_target_frames()
        floating_images = [(frame, self._selection_to_image(frame, bounds)) for frame in targets]
        floating_images = [(frame, image) for frame, image in floating_images if image is not None]
        image = next((image for frame, image in floating_images if frame is self.frame), None)
        if image is None:
            self.status_changed.emit("沒有可剪下的選取範圍")
            return False
        self.editing_started.emit()
        self.clipboard_image = image
        self.clipboard_pos = bounds.topLeft()
        for frame, _ in floating_images:
            self._clear_selection_from_layer(frame)
            frame.mark_dirty()
        self.floating_image = image.copy()
        self.batch_floating_images = floating_images if len(floating_images) > 1 else []
        self.floating_pos = QPointF(bounds.topLeft())
        self.floating_rotation = 0
        self.floating_flip_x = False
        self.floating_flip_y = False
        self.floating_scale_x = 1.0
        self.floating_scale_y = 1.0
        self.selection_rect = None
        self.lasso_points = []
        target_count = len(floating_images)
        status = "已建立同步浮動選取" if target_count > 1 else "已剪下為浮動選取"
        self._finish_edit(f"{status}（{target_count} 幀）" if target_count > 1 else status)
        return True

    def paste_selection(self) -> bool:
        if not self.frame or self.clipboard_image is None:
            self.status_changed.emit("剪貼簿沒有影像")
            return False
        self.commit_floating_selection()
        self.editing_started.emit()
        self.floating_image = self.clipboard_image.copy()
        self.batch_floating_images = []
        self.floating_pos = QPointF(getattr(self, "clipboard_pos", QPoint(0, 0)))
        self.floating_rotation = 0
        self.floating_flip_x = False
        self.floating_flip_y = False
        self.floating_scale_x = 1.0
        self.floating_scale_y = 1.0
        self.selection_rect = None
        self.lasso_points = []
        self.status_changed.emit("已貼上浮動選取，可拖曳/旋轉/翻轉")
        self.update()
        return True

    def rotate_floating_selection(self, degrees: float) -> None:
        if self.floating_image is None:
            return
        self.floating_rotation = (self.floating_rotation + degrees) % 360
        self.ensure_floating_within_workspace()
        self.status_changed.emit(f"浮動選取角度：{round(self.floating_rotation)}°")
        self.update()

    def set_floating_rotation(self, degrees: float) -> None:
        if self.floating_image is None:
            self.status_changed.emit("沒有浮動選取可旋轉")
            return
        self.floating_rotation = degrees % 360
        self.ensure_floating_within_workspace()
        self.status_changed.emit(f"浮動選取角度：{self.floating_rotation:.1f}°")
        self.update()

    def flip_floating_selection(self, horizontal: bool) -> None:
        if self.floating_image is None:
            return
        if horizontal:
            self.floating_flip_x = not self.floating_flip_x
            self.status_changed.emit("已水平翻轉浮動選取")
        else:
            self.floating_flip_y = not self.floating_flip_y
            self.status_changed.emit("已垂直翻轉浮動選取")
        self.ensure_floating_within_workspace()
        self.update()

    def commit_floating_selection(self) -> bool:
        if not self.frame or self.floating_image is None:
            return False
        self.ensure_floating_within_workspace()
        transform = self._floating_transform()
        floating_images = self.batch_floating_images or [(self.frame, self.floating_image)]
        for frame, image in floating_images:
            painter = QPainter(frame.active_layer.image)
            painter.setRenderHint(
                QPainter.RenderHint.SmoothPixmapTransform,
                self.smooth_selection_transform,
            )
            painter.setRenderHint(
                QPainter.RenderHint.Antialiasing,
                self.smooth_selection_transform,
            )
            painter.setTransform(transform)
            painter.drawImage(0, 0, image)
            painter.end()
            frame.mark_dirty()
        self.floating_image = None
        self.batch_floating_images = []
        self.image_changed.emit()
        self.update()
        return True

    def finish_active_selection(self) -> bool:
        had_selection = (
            self.floating_image is not None
            or self.has_active_selection()
            or self._selecting
        )
        if not had_selection:
            return False
        committed = self.commit_floating_selection()
        self._selecting = False
        self._selection_start = None
        self._dragging_floating = False
        self._resizing_floating = False
        self._rotating_floating = False
        self._resize_handle = ""
        self.selection_rect = None
        self.lasso_points = []
        self.status_changed.emit("已完成選取並退出" if committed else "已取消選取")
        self.update()
        return True

    def clear_selection(self) -> None:
        self.selection_rect = None
        self.lasso_points = []
        self.update()

    def has_active_selection(self) -> bool:
        return (
            self.selection_rect is not None and not self.selection_rect.isNull()
        ) or len(self.lasso_points) >= 3

    def selection_mask_image(self) -> Optional[QImage]:
        """Return the rectangular or lasso selection as an image-sized mask."""
        if not self.frame or not self.has_active_selection():
            return None

        mask = QImage(self.frame.width, self.frame.height, QImage.Format.Format_RGBA8888)
        mask.fill(Qt.GlobalColor.transparent)
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 255))
        if len(self.lasso_points) >= 3:
            painter.drawPath(self._lasso_path(QPoint(0, 0)))
        elif self.selection_rect is not None:
            painter.drawRect(self._selection_bounds())
        painter.end()
        return mask

    def delete_selection(self) -> bool:
        if self.floating_image is not None:
            self.editing_started.emit()
            self.floating_image = None
            target_count = len(self.batch_floating_images) or 1
            self.batch_floating_images = []
            self.status_changed.emit(f"已刪除浮動選取（{target_count} 幀）" if target_count > 1 else "已刪除浮動選取")
            self.update()
            return True
        if self.selection_rect or self.lasso_points:
            self.editing_started.emit()
            targets = self.selection_target_frames()
            for frame in targets:
                self._clear_selection_from_layer(frame)
                frame.mark_dirty()
            self.selection_rect = None
            self.lasso_points = []
            target_count = len(targets)
            self._finish_edit(f"已刪除選取內容（{target_count} 幀）" if target_count > 1 else "已刪除選取內容")
            return True
        return False

    def _finish_edit(self, status: str) -> None:
        if self.frame:
            self.frame.mark_dirty()
        self.image_changed.emit()
        self.status_changed.emit(status)
        self.update()

    def _sample_color(self, pos: QPoint) -> None:
        if not self.frame:
            return
        color = self.frame.composite().pixelColor(pos)
        self.color = QColor(color)
        self.color_sampled.emit(QColor(color))
        alpha = color.alpha()
        self.status_changed.emit(f"已取樣顏色 {color.name().upper()} / {alpha}")
        self.update()

    def _paint_checker(self, painter: QPainter) -> None:
        size = 16
        c1 = QColor(96, 96, 96)
        c2 = QColor(112, 112, 112)
        for y in range(0, self.height(), size):
            for x in range(0, self.width(), size):
                painter.fillRect(x, y, size, size, c1 if (x // size + y // size) % 2 == 0 else c2)

    def _paint_selection_overlay(self, painter: QPainter) -> None:
        painter.save()
        painter.setPen(QPen(QColor(0, 180, 255), 1, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(0, 180, 255, 35))
        if self.selection_rect and not self.selection_rect.isNull():
            view_rect = self._image_to_view_rect(self.selection_rect)
            painter.drawRect(view_rect)
            self._paint_rotation_handle(painter, self._selection_handle_center(view_rect))
            self._paint_resize_handles(painter, self._selection_resize_handle_centers(view_rect))
        elif len(self.lasso_points) > 1:
            path = QPainterPath(self._image_to_view_point(self.lasso_points[0]))
            for point in self.lasso_points[1:]:
                path.lineTo(self._image_to_view_point(point))
            if not self._selecting and len(self.lasso_points) > 2:
                path.closeSubpath()
                self._paint_rotation_handle(painter, self._selection_handle_center(path.boundingRect()))
            painter.drawPath(path)
        painter.restore()

    def _paint_floating_selection(self, painter: QPainter) -> None:
        if self.floating_image is None:
            return
        painter.save()
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            self.smooth_selection_transform,
        )
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            self.smooth_selection_transform,
        )
        view_transform = QTransform()
        view_transform.translate(self._image_rect.left(), self._image_rect.top())
        view_transform.scale(self.zoom, self.zoom)
        painter.setTransform(self._floating_transform() * view_transform, True)
        painter.drawImage(0, 0, self.floating_image)
        rect = QRectF(0, 0, self.floating_image.width(), self.floating_image.height())
        painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
        painter.drawRect(rect)
        painter.restore()
        painter.save()
        self._paint_rotation_handle(painter, self._floating_handle_center_view())
        self._paint_resize_handles(painter, self._floating_resize_handle_centers_view())
        painter.restore()

    def _paint_brush_preview(self, painter: QPainter) -> None:
        if self._hover_pos is None or self.tool not in {"pen", "eraser"}:
            return
        center = self._image_to_view_point(self._hover_pos)
        radius = max(1.0, self.brush_size * self.zoom / 2)
        painter.save()
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QColor(255, 255, 255, 32) if self.tool == "pen" else QColor(0, 0, 0, 24))
        painter.drawEllipse(center, radius, radius)
        painter.setPen(QPen(QColor(0, 0, 0), 1, Qt.PenStyle.DashLine))
        painter.drawEllipse(center, radius, radius)
        if self.tool == "pen" and self.pixel_blend_enabled:
            core_radius = (self.brush_size / 2.0 - self.pixel_blend_edge_width) * self.zoom
            if core_radius > 0.5:
                painter.setPen(QPen(QColor(0, 220, 255), 1, Qt.PenStyle.DashLine))
                painter.drawEllipse(center, core_radius, core_radius)
        painter.restore()

    def _selection_to_image(self, frame: Optional[Frame] = None, bounds: Optional[QRect] = None) -> Optional[QImage]:
        target_frame = frame or self.frame
        if not target_frame:
            return None
        bounds = bounds or self._selection_bounds()
        if bounds.isNull() or bounds.width() <= 0 or bounds.height() <= 0:
            return None
        layer = target_frame.active_layer.image
        out = QImage(bounds.size(), QImage.Format.Format_RGBA8888)
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        if self.lasso_points:
            path = self._lasso_path(bounds.topLeft())
            painter.setClipPath(path)
        painter.drawImage(-bounds.left(), -bounds.top(), layer)
        painter.end()
        return out

    def _point_in_selection(self, point: QPoint) -> bool:
        if self.selection_rect:
            return self.selection_rect.normalized().contains(point)
        if len(self.lasso_points) > 2:
            return self._lasso_path(QPoint(0, 0)).contains(QPointF(point))
        return False

    def _clear_selection_from_layer(self, frame: Optional[Frame] = None) -> None:
        target_frame = frame or self.frame
        if not target_frame:
            return
        image = target_frame.active_layer.image
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        if self.lasso_points:
            painter.fillPath(self._lasso_path(QPoint(0, 0)), QColor(0, 0, 0, 0))
        elif self.selection_rect:
            painter.fillRect(self.selection_rect, QColor(0, 0, 0, 0))
        painter.end()
        target_frame.mark_dirty()

    def _selection_bounds(self) -> QRect:
        if self.selection_rect:
            return self.selection_rect.normalized().intersected(QRect(0, 0, self.frame.width, self.frame.height)) if self.frame else QRect()
        if not self.lasso_points or not self.frame:
            return QRect()
        min_x = max(0, min(point.x() for point in self.lasso_points))
        min_y = max(0, min(point.y() for point in self.lasso_points))
        max_x = min(self.frame.width - 1, max(point.x() for point in self.lasso_points))
        max_y = min(self.frame.height - 1, max(point.y() for point in self.lasso_points))
        return QRect(QPoint(min_x, min_y), QPoint(max_x, max_y)).normalized()

    def _lasso_path(self, offset: QPoint) -> QPainterPath:
        path = QPainterPath()
        if not self.lasso_points:
            return path
        first = self.lasso_points[0] - offset
        path.moveTo(first)
        for point in self.lasso_points[1:]:
            path.lineTo(point - offset)
        path.closeSubpath()
        return path

    def _normalize_selection(self) -> None:
        if self.selection_rect:
            self.selection_rect = self.selection_rect.normalized()
            if self.selection_rect.width() < 2 or self.selection_rect.height() < 2:
                self.selection_rect = None
        if len(self.lasso_points) < 3:
            self.lasso_points = []

    def _point_in_floating(self, point: QPoint) -> bool:
        if self.floating_image is None:
            return False
        mapped = self._floating_transform().inverted()[0].map(QPointF(point))
        return QRectF(0, 0, self.floating_image.width(), self.floating_image.height()).contains(mapped)

    def _rotation_handle_hit(self, view_pos: QPointF) -> bool:
        center = None
        if self.floating_image is not None:
            center = self._floating_handle_center_view()
        elif self.selection_rect:
            center = self._selection_handle_center(self._image_to_view_rect(self.selection_rect))
        elif len(self.lasso_points) > 2:
            path = QPainterPath(self._image_to_view_point(self.lasso_points[0]))
            for point in self.lasso_points[1:]:
                path.lineTo(self._image_to_view_point(point))
            center = self._selection_handle_center(path.boundingRect())
        if center is None:
            return False
        return QRectF(center.x() - 9, center.y() - 9, 18, 18).contains(view_pos)

    def _resize_handle_hit(self, view_pos: QPointF) -> str:
        centers = {}
        if self.floating_image is not None:
            centers = self._floating_resize_handle_centers_view()
        elif self.selection_rect:
            centers = self._selection_resize_handle_centers(self._image_to_view_rect(self.selection_rect))
        for name, center in centers.items():
            if QRectF(center.x() - 7, center.y() - 7, 14, 14).contains(view_pos):
                return name
        return ""

    def _paint_rotation_handle(self, painter: QPainter, center: Optional[QPointF]) -> None:
        if center is None:
            return
        painter.save()
        painter.setPen(QPen(QColor(20, 20, 20), 1))
        painter.setBrush(QColor(255, 235, 59))
        painter.drawEllipse(center, 7, 7)
        painter.drawLine(QPointF(center.x(), center.y() + 7), QPointF(center.x(), center.y() + 20))
        painter.restore()

    def _paint_resize_handles(self, painter: QPainter, centers: dict) -> None:
        painter.save()
        painter.setPen(QPen(QColor(20, 20, 20), 1))
        painter.setBrush(QColor(255, 255, 255))
        for center in centers.values():
            painter.drawRect(QRectF(center.x() - 4, center.y() - 4, 8, 8))
        painter.restore()

    def _selection_resize_handle_centers(self, rect: QRectF) -> dict:
        return {
            "tl": rect.topLeft(),
            "tr": rect.topRight(),
            "br": rect.bottomRight(),
            "bl": rect.bottomLeft(),
        }

    def _selection_handle_center(self, rect: QRectF) -> QPointF:
        return QPointF(rect.center().x(), rect.top() - 24)

    def _floating_center_image(self) -> QPointF:
        if self.floating_image is None:
            return QPointF(0, 0)
        return self._floating_transform().map(QPointF(self.floating_image.width() / 2, self.floating_image.height() / 2))

    def _floating_handle_center_view(self) -> Optional[QPointF]:
        if self.floating_image is None:
            return None
        top_center = QPointF(self.floating_image.width() / 2, -24 / max(0.1, self.zoom))
        image_pos = self._floating_transform().map(top_center)
        return self._image_to_view_point_f(image_pos)

    def _floating_resize_handle_centers_view(self) -> dict:
        if self.floating_image is None:
            return {}
        points = {
            "tl": QPointF(0, 0),
            "tr": QPointF(self.floating_image.width(), 0),
            "br": QPointF(self.floating_image.width(), self.floating_image.height()),
            "bl": QPointF(0, self.floating_image.height()),
        }
        return {name: self._image_to_view_point_f(self._floating_transform().map(point)) for name, point in points.items()}

    def _floating_transform(self) -> QTransform:
        if self.floating_image is None:
            return QTransform()
        transform = QTransform()
        transform.translate(self.floating_pos.x() + self.floating_image.width() / 2, self.floating_pos.y() + self.floating_image.height() / 2)
        transform.rotate(self.floating_rotation)
        transform.scale(self.floating_scale_x, self.floating_scale_y)
        transform.scale(-1 if self.floating_flip_x else 1, -1 if self.floating_flip_y else 1)
        transform.translate(-self.floating_image.width() / 2, -self.floating_image.height() / 2)
        return transform

    def _image_to_view_point(self, point: QPoint) -> QPointF:
        return QPointF(self._image_rect.left() + point.x() * self.zoom, self._image_rect.top() + point.y() * self.zoom)

    def _image_to_view_point_f(self, point: QPointF) -> QPointF:
        return QPointF(self._image_rect.left() + point.x() * self.zoom, self._image_rect.top() + point.y() * self.zoom)

    def _view_to_image_point(self, point: QPointF) -> QPointF:
        return QPointF((point.x() - self._image_rect.left()) / self.zoom, (point.y() - self._image_rect.top()) / self.zoom)

    def _image_to_view_rect(self, rect: QRect) -> QRectF:
        return QRectF(
            self._image_rect.left() + rect.left() * self.zoom,
            self._image_rect.top() + rect.top() * self.zoom,
            rect.width() * self.zoom,
            rect.height() * self.zoom,
        )

    def _update_cursor(self) -> None:
        if self.tool == "pen":
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        elif self.tool == "eraser":
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        elif self.tool == "fill":
            self.setCursor(QCursor(Qt.CursorShape.WhatsThisCursor))
        elif self.tool in {"select", "lasso"}:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        elif self.tool in {"wand", "global_wand", "universal_wand"}:
            self.setCursor(QCursor(Qt.CursorShape.UpArrowCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
