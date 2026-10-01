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
    sprite_cell_rect,
)


def solid_image(width: int, height: int, color: str) -> QImage:
    image = QImage(width, height, RGBA_FORMAT)
    image.fill(QColor(color))
    return image


class SpriteSheetSplitTests(unittest.TestCase):
    def test_grid_expands_on_all_sides_without_scaling_source(self):
        image = solid_image(4, 4, "red")
        image.setPixelColor(0, 0, QColor("blue"))
        layout = SpriteSheetLayout(2, 2, -2, -2, 8, 8)
        frames = split_spritesheet(image, layout)
        self.assertEqual([frame.size() for frame in frames], [image.size()] * 4)
        self.assertEqual(frames[0].pixelColor(2, 2), QColor("blue"))
        self.assertEqual(frames[0].pixelColor(3, 2), QColor("red"))
        for index, point in ((0, (0, 0)), (1, (3, 0)), (2, (0, 3)), (3, (3, 3))):
            self.assertEqual(frames[index].pixelColor(*point).alpha(), 0)
        self.assertEqual(frames[3].pixelColor(0, 0), QColor("red"))

    def test_grid_entirely_outside_source_is_transparent(self):
        for x, y in ((-20, -20), (20, 20), (-20, 0), (0, 20)):
            frames = split_spritesheet(solid_image(4, 4, "red"), SpriteSheetLayout(1, 1, x, y, 5, 5))
            self.assertTrue(all(frames[0].pixelColor(cx, cy).alpha() == 0
                                for cy in range(5) for cx in range(5)))

    def test_grid_width_rescales_all_cells_without_changing_gaps(self):
        image = solid_image(2000, 1200, "red")
        for width, expected in ((1600, 400), (1800, 450)):
            layout = SpriteSheetLayout(4, 2, 10, 20, width, 1000)
            geometry = calculate_sprite_geometry(image, layout)
            rects = [sprite_cell_rect(layout, geometry, i) for i in range(8)]
            self.assertEqual([r.width() for r in rects], [expected] * 8)
            self.assertEqual([r.x() for r in rects[:4]], [10 + i * expected for i in range(4)])
            self.assertEqual(rects[3].x() + rects[3].width(), 10 + width)
            self.assertEqual(rects[4].y(), 520)

    def test_grid_height_and_separation_have_distinct_meanings(self):
        image = solid_image(200, 200, "red")
        for height, gap, cell_height in ((80, 0, 40), (100, 0, 50), (100, 10, 45)):
            layout = SpriteSheetLayout(2, 2, 13, 17, 100, height, 4, gap)
            geometry = calculate_sprite_geometry(image, layout)
            first, second = [sprite_cell_rect(layout, geometry, i) for i in (0, 2)]
            self.assertEqual(first.height(), cell_height)
            self.assertEqual(second.y() - first.y() - first.height(), gap)
            self.assertEqual(second.y() + second.height(), 17 + height)

    def test_nondivisible_cells_stay_inside_grid_and_never_sample_margin(self):
        image = solid_image(30, 20, "magenta")
        layout = SpriteSheetLayout(4, 3, 3, 4, 17, 11, 1, 1)
        geometry = calculate_sprite_geometry(image, layout)
        frames = split_spritesheet(image, layout)
        rects = [sprite_cell_rect(layout, geometry, i) for i in range(12)]
        self.assertEqual(rects[3].x() + rects[3].width(), 20)
        self.assertEqual(rects[-1].y() + rects[-1].height(), 15)
        self.assertEqual(geometry.padded_size, image.size())
        for rect, frame in zip(rects, frames):
            self.assertTrue(geometry.source_content_rect.contains(rect))
            if rect.width() < frame.width():
                self.assertEqual(frame.pixelColor(frame.width() - 1, 0).alpha(), 0)

    def test_invalid_grid_bounds_and_subpixel_cells(self):
        image = solid_image(10, 10, "red")
        for args in ((0, 0, 0, 8), (0, 0, 3, 8)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                calculate_sprite_geometry(image, SpriteSheetLayout(4, 1, *args))

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

        frames = split_spritesheet(image, SpriteSheetLayout(columns=2, rows=2, grid_x=0, grid_y=0, grid_width=image.width(), grid_height=image.height()))

        self.assertEqual(len(frames), 4)
        self.assertEqual([(frame.width(), frame.height()) for frame in frames], [(2, 2)] * 4)
        self.assertEqual([frame.pixelColor(0, 0).name() for frame in frames], [color.name() for color in colors])

    def test_pads_non_divisible_right_and_bottom_edges(self) -> None:
        image = solid_image(5, 3, "#336699")
        layout = SpriteSheetLayout(columns=2, rows=2, grid_x=0, grid_y=0, grid_width=image.width(), grid_height=image.height())

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
            grid_x=1, grid_y=1, grid_width=7, grid_height=2,
        )

        frames = split_spritesheet(image, layout)

        self.assertEqual([(frame.width(), frame.height()) for frame in frames], [(3, 2), (3, 2)])
        self.assertEqual(frames[0].pixelColor(1, 1).name(), "#ff0000")
        self.assertEqual(frames[1].pixelColor(1, 1).name(), "#0000ff")

    def test_rejects_spacing_that_consumes_the_source(self) -> None:
        image = solid_image(8, 8, "red")
        layout = SpriteSheetLayout(columns=4, rows=1, grid_x=0, grid_y=0, grid_width=8, grid_height=8, horizontal_spacing=3)

        with self.assertRaisesRegex(ValueError, "no usable sprite pixels"):
            split_spritesheet(image, layout)

    def test_negative_spacing_overlaps_adjacent_cells(self) -> None:
        image = QImage(7, 7, RGBA_FORMAT)
        for y in range(image.height()):
            for x in range(image.width()):
                image.setPixelColor(x, y, QColor(x * 30, y * 30, 0))
        layout = SpriteSheetLayout(
            columns=2,
            rows=2,
            grid_x=0, grid_y=0, grid_width=7, grid_height=7,
            horizontal_spacing=-1,
            vertical_spacing=-1,
        )

        geometry = calculate_sprite_geometry(image, layout)
        frames = split_spritesheet(image, layout)

        self.assertEqual((geometry.cell_size.width(), geometry.cell_size.height()), (4, 4))
        self.assertEqual(sprite_cell_rect(layout, geometry, 0).x(), 0)
        self.assertEqual(sprite_cell_rect(layout, geometry, 1).x(), 3)
        self.assertEqual(sprite_cell_rect(layout, geometry, 2).y(), 3)
        self.assertEqual(frames[0].pixelColor(3, 0), frames[1].pixelColor(0, 0))
        self.assertEqual(frames[0].pixelColor(0, 3), frames[2].pixelColor(0, 0))

    def test_rejects_negative_spacing_with_no_forward_step(self) -> None:
        image = solid_image(4, 4, "red")
        layout = SpriteSheetLayout(columns=2, rows=1, grid_x=0, grid_y=0, grid_width=4, grid_height=4, horizontal_spacing=-4)

        with self.assertRaisesRegex(ValueError, "no forward step"):
            split_spritesheet(image, layout)


if __name__ == "__main__":
    unittest.main()
