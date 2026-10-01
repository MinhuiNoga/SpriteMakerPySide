from __future__ import annotations

from dataclasses import dataclass
from typing import List

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage, QPainter

from .models import RGBA_FORMAT, make_blank_image


MAX_SPRITE_CELLS = 4096


@dataclass(frozen=True)
class SpriteSheetLayout:
    columns: int
    rows: int
    grid_x: int
    grid_y: int
    grid_width: int
    grid_height: int
    horizontal_spacing: int = 0
    vertical_spacing: int = 0

    @property
    def cell_count(self) -> int:
        return self.columns * self.rows


@dataclass(frozen=True)
class SpriteSheetGeometry:
    cell_size: QSize
    padded_size: QSize
    source_content_rect: QRect
    padding_right: int
    padding_bottom: int


def calculate_sprite_geometry(image: QImage, layout: SpriteSheetLayout) -> SpriteSheetGeometry:
    if image.isNull():
        raise ValueError("Sprite sheet image is empty.")
    if layout.columns < 1 or layout.rows < 1:
        raise ValueError("Columns and rows must be at least 1.")
    if layout.cell_count > MAX_SPRITE_CELLS:
        raise ValueError(f"Sprite sheet cannot exceed {MAX_SPRITE_CELLS} cells.")
    if layout.grid_width < 1 or layout.grid_height < 1:
        raise ValueError("Grid dimensions must be positive.")
    content_width = layout.grid_width
    content_height = layout.grid_height
    sprite_width = content_width - layout.horizontal_spacing * (layout.columns - 1)
    sprite_height = content_height - layout.vertical_spacing * (layout.rows - 1)
    if sprite_width < layout.columns or sprite_height < layout.rows:
        raise ValueError("Grid and separation leave no usable sprite pixels (minimum 1 px per cell).")

    cell_width = (sprite_width + layout.columns - 1) // layout.columns
    cell_height = (sprite_height + layout.rows - 1) // layout.rows
    if layout.columns > 1 and sprite_width // layout.columns + layout.horizontal_spacing < 1:
        raise ValueError("Horizontal spacing leaves no forward step between sprite cells.")
    if layout.rows > 1 and sprite_height // layout.rows + layout.vertical_spacing < 1:
        raise ValueError("Vertical spacing leaves no forward step between sprite cells.")
    if cell_width * cell_height * layout.cell_count > 64 * 1024 * 1024:
        raise ValueError("Expanded grid exceeds the 64 megapixel output limit.")
    return SpriteSheetGeometry(
        cell_size=QSize(cell_width, cell_height),
        padded_size=image.size(),
        source_content_rect=QRect(
            layout.grid_x,
            layout.grid_y,
            content_width,
            content_height,
        ).intersected(image.rect()),
        padding_right=cell_width * layout.columns - sprite_width,
        padding_bottom=cell_height * layout.rows - sprite_height,
    )


def sprite_cell_rect(layout: SpriteSheetLayout, geometry: SpriteSheetGeometry, index: int) -> QRect:
    if index < 0 or index >= layout.cell_count:
        raise IndexError("Sprite cell index out of range.")
    column = index % layout.columns
    row = index // layout.columns
    # Distribute integer remainders across cells, never across the grid boundary.
    def axis(start: int, extent: int, count: int, gap: int, cell: int):
        usable = extent - gap * (count - 1)
        left = (cell * usable + count - 1) // count
        right = ((cell + 1) * usable + count - 1) // count
        return start + left + cell * gap, right - left

    x, width = axis(layout.grid_x, layout.grid_width, layout.columns, layout.horizontal_spacing, column)
    y, height = axis(layout.grid_y, layout.grid_height, layout.rows, layout.vertical_spacing, row)
    return QRect(x, y, width, height)


def padded_spritesheet_image(image: QImage, geometry: SpriteSheetGeometry) -> QImage:
    source = image.convertToFormat(RGBA_FORMAT)
    padded = make_blank_image(geometry.padded_size.width(), geometry.padded_size.height())
    painter = QPainter(padded)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(0, 0, source)
    painter.end()
    return padded


def split_spritesheet(image: QImage, layout: SpriteSheetLayout) -> List[QImage]:
    geometry = calculate_sprite_geometry(image, layout)
    source = image.convertToFormat(RGBA_FORMAT)
    content_bounds = geometry.source_content_rect
    frames: List[QImage] = []
    for index in range(layout.cell_count):
        cell_rect = sprite_cell_rect(layout, geometry, index)
        source_rect = cell_rect.intersected(content_bounds)
        frame = make_blank_image(geometry.cell_size.width(), geometry.cell_size.height())
        if not source_rect.isEmpty():
            painter = QPainter(frame)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            target = QRect(
                source_rect.x() - cell_rect.x(),
                source_rect.y() - cell_rect.y(),
                source_rect.width(),
                source_rect.height(),
            )
            painter.drawImage(target, source, source_rect)
            painter.end()
        frame.setDevicePixelRatio(1.0)
        frames.append(frame)
    return frames
