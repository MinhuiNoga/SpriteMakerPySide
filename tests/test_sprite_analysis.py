import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QRect

from sprite_maker.image_ops import array_to_qimage
from sprite_maker.sprite_analysis import (
    BackgroundSettings, background_mask, detect_axis_layout, detect_empty_frames, detect_spritesheet,
)
from sprite_maker.sprite_ops import SpriteSheetLayout, calculate_sprite_geometry, sprite_cell_rect


def make_sheet(color=None, empty_index=6, noise=False):
    # Asymmetric outside margins: 7/13, 9/15. Different X/Y gaps: 4/6.
    pixels = np.zeros((122, 112, 4), dtype=np.uint8)
    if color is not None:
        pixels[:] = (*color, 255)
    for index in range(16):
        if index == empty_index:
            continue
        x, y = 7 + index % 4 * 24, 9 + index // 4 * 26
        pixels[y:y + 20, x:x + 20] = (210, 40, 60, 255)
    if noise:
        # A low-alpha speck is background even when RGB is wildly different.
        pixels[4, 4] = (255, 255, 255, 8)
    return array_to_qimage(pixels)


class SpriteAnalysisTests(unittest.TestCase):
    def test_empty_ratio_includes_transparent_extension(self):
        mask = np.zeros((1, 1), dtype=bool)
        self.assertEqual(detect_empty_frames(mask, [QRect(-999, 0, 1000, 1), QRect(10, 10, 2, 2)]), [True, True])
        self.assertEqual(detect_empty_frames(mask, [QRect(0, 0, 1, 1)]), [False])
    def test_transparent_color_backgrounds_and_asymmetric_grid(self):
        for color in (None, (0, 255, 0), (0, 0, 255), (83, 112, 47)):
            with self.subTest(color=color):
                image = make_sheet(color, noise=True)
                settings = BackgroundSettings() if color is None else BackgroundSettings(mode="color", color=color)
                result = detect_spritesheet(image, settings)
                self.assertEqual((result.columns, result.rows), (4, 4))
                self.assertEqual((result.grid_x, result.grid_y, result.grid_width, result.grid_height), (7, 9, 92, 98))
                self.assertEqual((result.horizontal_spacing, result.vertical_spacing), (4, 6))
                self.assertGreaterEqual(result.confidence, 0.9)
                layout = SpriteSheetLayout(4, 4, 7, 9, 92, 98, 4, 6)
                geometry = calculate_sprite_geometry(image, layout)
                empty = detect_empty_frames(background_mask(image, settings),
                    [sprite_cell_rect(layout, geometry, i) for i in range(16)])
                self.assertEqual([i for i, value in enumerate(empty) if value], [6])

    def test_distance_tolerance_and_transparency(self):
        pixels = np.array([[[5, 245, 4, 255], [40, 220, 0, 255], [255, 0, 0, 0]]], dtype=np.uint8)
        image = array_to_qimage(pixels)
        mask = background_mask(image, BackgroundSettings(mode="color", tolerance=20))
        self.assertEqual(mask.tolist(), [[True, False, True]])

    def test_noise_line_projection_does_not_require_all_background(self):
        pixels = np.zeros((1000, 112, 4), dtype=np.uint8)
        for x in (7, 31, 55, 79):
            pixels[20:980, x:x + 20] = (255, 0, 0, 255)
        # Every separator line has one opaque noise pixel (0.1%).
        pixels[0, :] = (255, 255, 255, 255)
        result = detect_spritesheet(array_to_qimage(pixels))
        self.assertEqual((result.columns, result.grid_x, result.grid_width), (4, 7, 92))
        self.assertIsNone(result.rows)

    def test_empty_threshold_inclusive_and_keeps_indices(self):
        mask = np.ones((10, 200), dtype=bool)
        mask[0, 0] = False
        mask[0, 100:102] = False
        self.assertEqual(detect_empty_frames(mask, [QRect(0, 0, 100, 10), QRect(100, 0, 100, 10)]), [True, False])

    def test_no_foreground_and_opaque_unrecognizable(self):
        for value, message in ((0, "No foreground detected."), (255, "Unable to determine a regular sprite grid.")):
            pixels = np.full((20, 20, 4), value, dtype=np.uint8)
            result = detect_spritesheet(array_to_qimage(pixels))
            self.assertIsNone(result.columns)
            self.assertIsNone(result.rows)
            self.assertIn(message, result.warnings)

    def test_irregular_holes_are_not_all_separators(self):
        projection = np.ones(120)
        for start, end in ((4, 7), (11, 29), (41, 43), (49, 86), (103, 109)):
            projection[start:end] = 0.4
        self.assertIsNone(detect_axis_layout(projection).count)

    def test_internal_holes_can_be_grouped(self):
        projection = np.ones(112)
        for x in (7, 31, 55, 79):
            projection[x:x + 5] = 0
            projection[x + 8:x + 20] = 0
        result = detect_axis_layout(projection)
        self.assertEqual((result.count, result.start, result.end, result.spacing), (4, 7, 99, 4))

    def test_alternating_rounding_in_separators(self):
        projection = np.ones(105)
        for x in (2, 29, 57, 84):
            projection[x:x + 20] = 0
        result = detect_axis_layout(projection)
        self.assertEqual(result.count, 4)
        self.assertEqual(result.spacing, 7)

    def test_different_internal_holes_per_cell(self):
        projection = np.ones(112)
        for x in (7, 31, 55, 79):
            projection[x:x + 20] = 0
        projection[12:15] = 1
        projection[60:63] = 1
        projection[68:70] = 1
        result = detect_axis_layout(projection)
        self.assertEqual((result.count, result.start, result.end, result.spacing), (4, 7, 99, 4))


if __name__ == "__main__":
    unittest.main()
