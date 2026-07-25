from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter


RGBA_FORMAT = QImage.Format.Format_RGBA8888


def make_blank_image(width: int, height: int) -> QImage:
    image = QImage(max(1, width), max(1, height), RGBA_FORMAT)
    image.fill(Qt.GlobalColor.transparent)
    return image


def clone_image(image: QImage) -> QImage:
    return image.convertToFormat(RGBA_FORMAT).copy()


@dataclass
class Layer:
    name: str
    image: QImage
    opacity: float = 1.0
    visible: bool = True

    def clone(self) -> "Layer":
        return Layer(
            name=self.name,
            image=clone_image(self.image),
            opacity=self.opacity,
            visible=self.visible,
        )


@dataclass
class Frame:
    name: str
    layers: List[Layer]
    active_layer_index: int = 0
    source_path: Optional[Path] = None
    export_center_x: Optional[float] = None
    export_center_y: Optional[float] = None
    _composite_cache: Optional[QImage] = field(default=None, init=False, repr=False)
    _dirty: bool = field(default=True, init=False, repr=False)

    @property
    def width(self) -> int:
        return self.layers[0].image.width() if self.layers else 1

    @property
    def height(self) -> int:
        return self.layers[0].image.height() if self.layers else 1

    @property
    def export_center(self) -> tuple[float, float]:
        return (
            self.width / 2 if self.export_center_x is None else self.export_center_x,
            self.height / 2 if self.export_center_y is None else self.export_center_y,
        )

    @property
    def active_layer(self) -> Layer:
        self.active_layer_index = max(0, min(self.active_layer_index, len(self.layers) - 1))
        return self.layers[self.active_layer_index]

    def mark_dirty(self) -> None:
        self._dirty = True

    def composite(self) -> QImage:
        if self._composite_cache is not None and not self._dirty:
            return self._composite_cache

        output = make_blank_image(self.width, self.height)
        painter = QPainter(output)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        for layer in self.layers:
            if not layer.visible or layer.opacity <= 0:
                continue
            painter.setOpacity(max(0.0, min(1.0, layer.opacity)))
            painter.drawImage(0, 0, layer.image)
        painter.end()

        self._composite_cache = output
        self._dirty = False
        return output

    def clone(self) -> "Frame":
        cloned = Frame(
            name=self.name,
            layers=[layer.clone() for layer in self.layers],
            active_layer_index=self.active_layer_index,
            source_path=self.source_path,
            export_center_x=self.export_center_x,
            export_center_y=self.export_center_y,
        )
        cloned.mark_dirty()
        return cloned


def frame_from_image(path: Path) -> Frame:
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"Cannot read image: {path}")
    image = image.convertToFormat(RGBA_FORMAT)
    return Frame(
        name=path.name,
        layers=[Layer("圖層 1", image)],
        active_layer_index=0,
        source_path=path,
        export_center_x=image.width() / 2,
        export_center_y=image.height() / 2,
    )


def frame_from_qimage(image: QImage, name: str, source_path: Optional[Path] = None) -> Frame:
    return Frame(
        name=name,
        layers=[Layer("Layer 1", image.convertToFormat(RGBA_FORMAT))],
        active_layer_index=0,
        source_path=source_path,
        export_center_x=image.width() / 2,
        export_center_y=image.height() / 2,
    )
