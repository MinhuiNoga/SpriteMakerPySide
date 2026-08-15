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
    horizontal_spacing: int = 0
    vertical_spacing: int = 0
    outer_margin: int = 0

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
    if layout.horizontal_spacing < 0 or layout.vertical_spacing < 0 or layout.outer_margin < 0:
        raise ValueError("Spacing and outer margin cannot be negative.")

    content_width = image.width() - layout.outer_margin * 2
    content_height = image.height() - layout.outer_margin * 2
    sprite_width = content_width - layout.horizontal_spacing * (layout.columns - 1)
    sprite_height = content_height - layout.vertical_spacing * (layout.rows - 1)
    if sprite_width < 1 or sprite_height < 1:
        raise ValueError("Margins and spacing leave no usable sprite pixels.")

    cell_width = (sprite_width + layout.columns - 1) // layout.columns
    cell_height = (sprite_height + layout.rows - 1) // layout.rows
    padded_width = (
        layout.outer_margin * 2
        + cell_width * layout.columns
        + layout.horizontal_spacing * (layout.columns - 1)
    )
    padded_height = (
        layout.outer_margin * 2
        + cell_height * layout.rows
        + layout.vertical_spacing * (layout.rows - 1)
    )
    return SpriteSheetGeometry(
        cell_size=QSize(cell_width, cell_height),
        padded_size=QSize(padded_width, padded_height),
        source_content_rect=QRect(
            layout.outer_margin,
            layout.outer_margin,
            content_width,
            content_height,
        ),
        padding_right=padded_width - image.width(),
        padding_bottom=padded_height - image.height(),
    )


def sprite_cell_rect(layout: SpriteSheetLayout, geometry: SpriteSheetGeometry, index: int) -> QRect:
    if index < 0 or index >= layout.cell_count:
        raise IndexError("Sprite cell index out of range.")
    column = index % layout.columns
    row = index // layout.columns
    x = layout.outer_margin + column * (geometry.cell_size.width() + layout.horizontal_spacing)
    y = layout.outer_margin + row * (geometry.cell_size.height() + layout.vertical_spacing)
    return QRect(x, y, geometry.cell_size.width(), geometry.cell_size.height())


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
