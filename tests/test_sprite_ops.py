import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from sprite_maker.models import RGBA_FORMAT
from sprite_maker.sprite_ops import (
    SpriteSheetLayout,
    calculate_sprite_geometry,
    split_spritesheet,
)


def solid_image(width: int, height: int, color: str) -> QImage:
    image = QImage(width, height, RGBA_FORMAT)
    image.fill(QColor(color))
    return image


class SpriteSheetSplitTests(unittest.TestCase):
    def test_splits_row_major_order(self) -> None:
        image = QImage(4, 4, RGBA_FORMAT)
        image.fill(Qt.GlobalColor.transparent)
        colors = [QColor("red"), QColor("green"), QColor("blue"), QColor("yellow")]
        for index, color in enumerate(colors):
            left = (index % 2) * 2
            top = (index // 2) * 2
            for y in range(top, top + 2):
                for x in range(left, left + 2):
                    image.setPixelColor(x, y, color)

        frames = split_spritesheet(image, SpriteSheetLayout(columns=2, rows=2))

        self.assertEqual(len(frames), 4)
        self.assertEqual([(frame.width(), frame.height()) for frame in frames], [(2, 2)] * 4)
        self.assertEqual([frame.pixelColor(0, 0).name() for frame in frames], [color.name() for color in colors])

    def test_pads_non_divisible_right_and_bottom_edges(self) -> None:
        image = solid_image(5, 3, "#336699")
        layout = SpriteSheetLayout(columns=2, rows=2)

        geometry = calculate_sprite_geometry(image, layout)
        frames = split_spritesheet(image, layout)

        self.assertEqual((geometry.cell_size.width(), geometry.cell_size.height()), (3, 2))
        self.assertEqual((geometry.padding_right, geometry.padding_bottom), (1, 1))
        self.assertEqual(frames[1].pixelColor(2, 0).alpha(), 0)
        self.assertEqual(frames[2].pixelColor(0, 1).alpha(), 0)
        self.assertEqual(frames[3].pixelColor(2, 1).alpha(), 0)
        self.assertEqual(frames[3].pixelColor(0, 0).name(), "#336699")

    def test_excludes_outer_margin_and_spacing(self) -> None:
        image = solid_image(9, 4, "#ff00ff")
        for y in range(1, 3):
            for x in range(1, 4):
                image.setPixelColor(x, y, QColor("red"))
            for x in range(5, 8):
                image.setPixelColor(x, y, QColor("blue"))
        layout = SpriteSheetLayout(
            columns=2,
            rows=1,
            horizontal_spacing=1,
            outer_margin=1,
        )

        frames = split_spritesheet(image, layout)

        self.assertEqual([(frame.width(), frame.height()) for frame in frames], [(3, 2), (3, 2)])
        self.assertEqual(frames[0].pixelColor(1, 1).name(), "#ff0000")
        self.assertEqual(frames[1].pixelColor(1, 1).name(), "#0000ff")

    def test_rejects_spacing_that_consumes_the_source(self) -> None:
        image = solid_image(8, 8, "red")
        layout = SpriteSheetLayout(columns=4, rows=1, horizontal_spacing=3)

        with self.assertRaisesRegex(ValueError, "no usable sprite pixels"):
            split_spritesheet(image, layout)


if __name__ == "__main__":
    unittest.main()
