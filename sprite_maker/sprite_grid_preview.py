"""Interactive source-space grid overlay, independent of dialog/list rebuilding."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .sprite_ops import SpriteSheetLayout, calculate_sprite_geometry, sprite_cell_rect


class SpriteGridPreviewWidget(QWidget):
    gridRectChanged = Signal(QRect)
    gridRectChangeFinished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self._zoom = 1.0
        self.layout = None
        self.checked = set()
        self.empty = []
        self._drag = None
        self._canvas = QRectF(0, 0, 280, 220)
        tile = QPixmap(24, 24)
        tile.fill(QColor("#909090"))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 12, 12, QColor("#707070"))
        painter.fillRect(12, 12, 12, 12, QColor("#707070"))
        painter.end()
        self._checker = QBrush(tile)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 220)

    @property
    def grid_rect(self) -> QRect:
        if self.layout is None:
            return QRect()
        value = self.layout
        return QRect(value.grid_x, value.grid_y, value.grid_width, value.grid_height)

    def setImage(self, image: QImage) -> None:
        self._image = image.copy()
        self.setZoom(self._zoom)

    def setGrid(self, layout, checked=(), empty=()) -> None:
        self.layout = layout
        self.checked = set(checked)
        self.empty = list(empty)
        if self._drag is None:
            self._resize_canvas()
        self.update()

    def setZoom(self, zoom: float) -> None:
        self._zoom = max(0.1, min(8.0, float(zoom)))
        self._resize_canvas()
        self.update()

    def _resize_canvas(self) -> None:
        # Leave room outside the handles for dragging. Freeze this transform
        # during a gesture so expanding left/top never moves the drag origin.
        bounds = QRectF(self._image.rect())
        if self.layout is not None:
            bounds = bounds.united(QRectF(self.grid_rect))
        margin = 72 / self._zoom
        self._canvas = bounds.adjusted(-margin, -margin, margin, margin)
        self.resize(max(280, round(self._canvas.width() * self._zoom)),
                    max(220, round(self._canvas.height() * self._zoom)))

    def _offset(self) -> QPointF:
        return QPointF((self.width() - self._canvas.width() * self._zoom) / 2 - self._canvas.x() * self._zoom,
                       (self.height() - self._canvas.height() * self._zoom) / 2 - self._canvas.y() * self._zoom)

    def imageToWidget(self, point: QPointF) -> QPointF:
        return self._offset() + point * self._zoom

    def _image_point(self, point: QPointF) -> QPointF:
        return (point - self._offset()) / self._zoom

    def _handles(self):
        rect = self.grid_rect
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        return {
            "lt": QPointF(x, y), "t": QPointF(x + w / 2, y), "rt": QPointF(x + w, y),
            "l": QPointF(x, y + h / 2), "r": QPointF(x + w, y + h / 2),
            "lb": QPointF(x, y + h), "b": QPointF(x + w / 2, y + h), "rb": QPointF(x + w, y + h),
        }

    def _hit(self, position: QPointF):
        if self.layout is None:
            return None
        for name, point in self._handles().items():
            delta = position - self.imageToWidget(point)
            if abs(delta.x()) <= 7 and abs(delta.y()) <= 7:
                return name
        point = self._image_point(position)
        rect = QRectF(self.grid_rect)
        tolerance = 6 / self._zoom
        if not rect.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(point):
            return None
        for name, distance in (("l", point.x() - rect.left()), ("r", point.x() - rect.right()),
                               ("t", point.y() - rect.top()), ("b", point.y() - rect.bottom())):
            if abs(distance) <= tolerance:
                return name
        return "move" if rect.contains(point) else None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111827"))
        if self._image.isNull():
            painter.setPen(QColor("white"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "選擇圖片後會顯示拆分格線")
            return
        painter.translate(self._offset())
        painter.scale(self._zoom, self._zoom)
        visible = QRectF(self._image_point(QPointF(0, 0)),
                         self._image_point(QPointF(self.width(), self.height())))
        painter.fillRect(visible, self._checker)
        painter.drawImage(0, 0, self._image)
        if self.layout is None:
            return
        geometry = calculate_sprite_geometry(self._image, self.layout)
        pen = QPen(QColor("#22d3ee"), 1)
        pen.setCosmetic(True)
        for index in range(self.layout.cell_count):
            rect = QRectF(sprite_cell_rect(self.layout, geometry, index))
            if self._drag is None and index not in self.checked:
                painter.fillRect(rect, QColor(55, 55, 55, 175))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
        painter.setPen(QPen(QColor("#fbbf24"), 2 / self._zoom))
        painter.drawRect(QRectF(self.grid_rect))
        painter.resetTransform()
        # Labels and handles stay readable/clickable at every zoom level.
        for index in range(self.layout.cell_count):
            rect = sprite_cell_rect(self.layout, geometry, index)
            position = self.imageToWidget(QPointF(rect.x(), rect.y()))
            text = str(index + 1)
            painter.save()
            painter.setClipRect(QRectF(position.x(), position.y(), rect.width() * self._zoom, rect.height() * self._zoom))
            badge = QRectF(position.x() + 2, position.y() + 2, painter.fontMetrics().horizontalAdvance(text) + 8, 18)
            painter.fillRect(badge, QColor(0, 0, 0, 170))
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
            if self._drag is None and index < len(self.empty) and self.empty[index]:
                font = painter.font()
                font.setPixelSize(10)
                painter.setFont(font)
                badge = QRectF(position.x() + 2, position.y() + 21, painter.fontMetrics().horizontalAdvance("EMPTY") + 4, 14)
                painter.fillRect(badge, QColor(0, 0, 0, 190))
                painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "EMPTY")
            painter.restore()
        for point in self._handles().values():
            point = self.imageToWidget(point)
            painter.fillRect(QRectF(point.x() - 4, point.y() - 4, 8, 8), QColor("#fbbf24"))

    def mousePressEvent(self, event) -> None:
        hit = self._hit(event.position())
        if event.button() == Qt.MouseButton.LeftButton and hit:
            self._drag = (hit, self._image_point(event.position()), self.grid_rect)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            hit = self._hit(event.position())
            cursors = {"move": Qt.CursorShape.SizeAllCursor, "l": Qt.CursorShape.SizeHorCursor,
                       "r": Qt.CursorShape.SizeHorCursor, "t": Qt.CursorShape.SizeVerCursor,
                       "b": Qt.CursorShape.SizeVerCursor, "lt": Qt.CursorShape.SizeFDiagCursor,
                       "rb": Qt.CursorShape.SizeFDiagCursor, "rt": Qt.CursorShape.SizeBDiagCursor,
                       "lb": Qt.CursorShape.SizeBDiagCursor}
            self.setCursor(cursors.get(hit, Qt.CursorShape.ArrowCursor))
            return
        hit, origin, initial = self._drag
        delta = self._image_point(event.position()) - origin
        dx, dy = round(delta.x()), round(delta.y())
        left, top = initial.x(), initial.y()
        right, bottom = left + initial.width(), top + initial.height()
        layout = self.layout
        # Negative separations remain available for existing overlapping sheets.
        min_width = max(layout.columns + layout.horizontal_spacing * (layout.columns - 1),
                        layout.columns - layout.horizontal_spacing if layout.columns > 1 else 1, 1)
        min_height = max(layout.rows + layout.vertical_spacing * (layout.rows - 1),
                         layout.rows - layout.vertical_spacing if layout.rows > 1 else 1, 1)
        if hit == "move":
            left = left + dx
            top = top + dy
            right, bottom = left + initial.width(), top + initial.height()
        else:
            if "l" in hit:
                left = min(right - min_width, left + dx)
            if "r" in hit:
                right = max(left + min_width, right + dx)
            if "t" in hit:
                top = min(bottom - min_height, top + dy)
            if "b" in hit:
                bottom = max(top + min_height, bottom + dy)
        rect = QRect(left, top, right - left, bottom - top)
        candidate = replace(layout, grid_x=left, grid_y=top, grid_width=rect.width(), grid_height=rect.height())
        if (abs(left) > 1000000 or abs(top) > 1000000
                or rect.width() > 1000000 or rect.height() > 1000000):
            return
        try:
            calculate_sprite_geometry(self._image, candidate)
        except ValueError:
            return
        self.layout = candidate
        self.gridRectChanged.emit(rect)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self.mouseMoveEvent(event)
            self._drag = None
            self._resize_canvas()
            self.gridRectChangeFinished.emit()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._drag is None:
                self.setZoom(self._zoom * (1.12 if event.angleDelta().y() > 0 else 1 / 1.12))
            event.accept()
        else:
            event.ignore()
