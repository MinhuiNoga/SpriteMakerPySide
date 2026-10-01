import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from sprite_maker.app import MainWindow
from sprite_maker.image_ops import array_to_qimage, consolidate_similar_colors, qimage_to_array
from sprite_maker.models import Layer, frame_from_qimage
from sprite_maker.widgets import CanvasWidget


def sheet(width=4, height=3):
    pixels = np.full((height, width, 4), (200, 20, 30, 128), dtype=np.uint8)
    return array_to_qimage(pixels)


class ColorConsolidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_source_and_target_are_independent_and_preserve_alpha(self):
        pixels = np.array([[[200, 20, 30, 128], [202, 22, 31, 255], [0, 0, 255, 255],
                            [200, 20, 30, 0], [200, 20, 30, 255]]], dtype=np.uint8)
        mask = np.zeros_like(pixels)
        mask[0, :4, 3] = 255
        result, _, stats = consolidate_similar_colors(array_to_qimage(pixels), QColor(200, 20, 30),
            5, array_to_qimage(mask), QColor("blue"))
        actual = qimage_to_array(result)
        np.testing.assert_array_equal(actual[0, :2, :3], [[0, 0, 255]] * 2)
        np.testing.assert_array_equal(actual[:, :, 3], pixels[:, :, 3])
        np.testing.assert_array_equal(actual[0, 2:], pixels[0, 2:])
        self.assertEqual(stats["matchedPixelCount"], 2)
        self.assertEqual(stats["changedPixelCount"], 2)
        self.assertEqual(stats["targetColor"], "#0000FF")

    def make_canvas(self):
        canvas = CanvasWidget()
        self.addCleanup(canvas.close)
        frames = [frame_from_qimage(sheet(), str(i)) for i in range(3)]
        canvas.set_frame(frames[0])
        canvas.set_batch_selection_frames(frames[:2], active=True)
        canvas.selection_rect = QRect(1, 1, 2, 1)
        canvas.set_color_consolidation_target(QColor("blue"))
        canvas._sample_color_for_consolidation(QPoint(0, 0))
        return canvas, frames

    def test_batch_is_limited_to_selected_frames_region_and_active_layer(self):
        canvas, frames = self.make_canvas()
        frames[1].layers.append(Layer("second", sheet()))
        frames[1].active_layer_index = 1
        original = qimage_to_array(sheet())
        edits = []
        canvas.editing_started.connect(lambda: edits.append(True))
        self.assertEqual(canvas.color_consolidation_stats["frameCount"], 2)
        self.assertEqual(canvas.color_consolidation_stats["changedPixelCount"], 4)
        self.assertTrue(canvas.apply_color_consolidation())
        self.assertEqual(len(edits), 1)
        expected = original.copy()
        expected[1, 1:3, :3] = (0, 0, 255)
        for frame in frames[:2]:
            np.testing.assert_array_equal(qimage_to_array(frame.active_layer.image), expected)
        np.testing.assert_array_equal(qimage_to_array(frames[1].layers[0].image), original)
        np.testing.assert_array_equal(qimage_to_array(frames[2].active_layer.image), original)

    def test_different_frame_sizes_clip_same_rect_without_rescaling(self):
        canvas, frames = self.make_canvas()
        frames[1].layers[0].image = sheet(2, 2)
        self.assertTrue(canvas.apply_color_consolidation())
        small = qimage_to_array(frames[1].active_layer.image)
        self.assertEqual(np.count_nonzero(small[:, :, 2] == 255), 1)
        self.assertEqual(small[1, 1].tolist(), [0, 0, 255, 128])

    def test_lasso_masks_are_applied_to_each_frame(self):
        canvas, frames = self.make_canvas()
        canvas.selection_rect = None
        canvas.lasso_points = [QPoint(0, 0), QPoint(3, 0), QPoint(0, 3)]
        mask = qimage_to_array(canvas.selection_mask_image())[:, :, 3] > 0
        self.assertTrue(canvas.apply_color_consolidation())
        for frame in frames[:2]:
            actual = qimage_to_array(frame.active_layer.image)
            np.testing.assert_array_equal(actual[:, :, 2] == 255, mask)

    def test_cancel_noop_and_missing_batch_selection_make_no_undo(self):
        canvas, frames = self.make_canvas()
        edits = []
        canvas.editing_started.connect(lambda: edits.append(True))
        self.assertTrue(canvas.cancel_color_consolidation())
        self.assertFalse(canvas.apply_color_consolidation())
        canvas._sample_color_for_consolidation(QPoint(0, 0))
        canvas.set_color_consolidation_target(None)
        self.assertFalse(canvas.apply_color_consolidation())
        canvas.set_color_consolidation_target(QColor("blue"))
        canvas.clear_selection()
        self.assertEqual(canvas.color_consolidation_stats["matchedPixelCount"], 24)
        canvas.selection_rect = QRect(0, 0, 1, 1)
        canvas.set_batch_selection_frames([], active=True)
        self.assertFalse(canvas.apply_color_consolidation())
        self.assertEqual(edits, [])
        for frame in frames:
            self.assertEqual(frame.active_layer.image, sheet())

    def test_target_and_palette_independence_and_preview_refresh(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.replace_with_sprite_frames([sheet()])
        window.set_tool("color_consolidate")
        palette = QColor(window.color)
        window.canvas._sample_color_for_consolidation(QPoint(0, 0))
        with patch("sprite_maker.app.choose_fixed_color", return_value=QColor("blue")):
            window.choose_consolidation_color()
        self.assertEqual(window.canvas.color_consolidation_stats["changedPixelCount"], 12)
        self.assertEqual(window.color, palette)
        self.assertEqual(window.canvas.color, palette)
        window.canvas._sample_color_for_consolidation(QPoint(1, 1))
        self.assertEqual(window.canvas.color_consolidation_target, QColor("blue"))
        with patch("sprite_maker.app.choose_fixed_color", return_value=QColor()):
            window.choose_consolidation_color()
        self.assertEqual(window.canvas.color_consolidation_target, QColor("blue"))
        window.reset_consolidation_color()
        self.assertEqual(window.canvas.color_consolidation_stats["changedPixelCount"], 0)

    def test_editor_batch_selection_undo_redo_one_step(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.replace_with_sprite_frames([sheet(), sheet(), sheet()])
        window.sync_selection_toggle.setChecked(True)
        window.thumbnails.item(1).setSelected(True)
        self.assertEqual(window.selected_frame_rows(), [0, 1])
        window.canvas.selection_rect = QRect(1, 1, 1, 1)
        window.set_tool("color_consolidate")
        window.canvas.set_color_consolidation_target(QColor("blue"))
        window.canvas._sample_color_for_consolidation(QPoint(0, 0))
        self.assertTrue(window.canvas.apply_color_consolidation())
        self.assertEqual(len(window.undo_stack), 1)
        after = [frame.active_layer.image.copy() for frame in window.frames]
        self.assertEqual(after[2], sheet())
        self.assertNotEqual(after[0], sheet())
        self.assertNotEqual(after[1], sheet())
        window.undo()
        self.assertTrue(all(frame.active_layer.image == sheet() for frame in window.frames))
        window.redo()
        self.assertEqual([frame.active_layer.image for frame in window.frames], after)

    def test_single_frame_without_region_remains_supported(self):
        canvas, frames = self.make_canvas()
        canvas.set_batch_selection_frames([], active=False)
        canvas.clear_selection()
        self.assertTrue(canvas.apply_color_consolidation())
        self.assertTrue(np.all(qimage_to_array(frames[0].active_layer.image)[:, :, 2] == 255))
        self.assertEqual(frames[1].active_layer.image, sheet())

    def test_shift_multiselect_without_region_previews_and_edits_both_frames(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.replace_with_sprite_frames([sheet(), sheet(), sheet()])
        window.show()
        self.app.processEvents()
        view = window.thumbnails
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         pos=view.visualItemRect(view.item(0)).center())
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                         pos=view.visualItemRect(view.item(1)).center())
        self.assertEqual(window.selected_frame_rows(), [0, 1])
        self.assertFalse(window.sync_selection_toggle.isChecked())
        window.set_tool("color_consolidate")
        window.canvas.set_color_consolidation_target(QColor("blue"))
        window.canvas._sample_color_for_consolidation(QPoint(0, 0))
        stats = window.canvas.color_consolidation_stats
        self.assertEqual(stats["frameCount"], 2)
        self.assertEqual(stats["matchedPixelCount"], 24)
        overlay = window.canvas.color_consolidation_overlay_image
        self.assertIsNotNone(overlay)
        self.assertTrue(np.any(qimage_to_array(overlay)[:, :, 3] > 0))
        self.assertTrue(window.canvas.apply_color_consolidation())
        self.assertEqual(len(window.undo_stack), 1)
        self.assertEqual(window.frames[2].active_layer.image, sheet())
        for frame in window.frames[:2]:
            self.assertEqual(frame.active_layer.image.pixelColor(0, 0).blue(), 255)

    def test_drawing_region_before_shift_multiselect_preserves_region_and_preview(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.replace_with_sprite_frames([sheet(), sheet(), sheet()])
        window.sync_selection_toggle.setChecked(True)
        window.show()
        self.app.processEvents()
        region = QRect(1, 1, 1, 1)
        window.canvas.selection_rect = region
        window.set_tool("color_consolidate")
        window.canvas._sample_color_for_consolidation(QPoint(0, 0))
        view = window.thumbnails
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                         pos=view.visualItemRect(view.item(1)).center())
        self.assertEqual(window.selected_frame_rows(), [0, 1])
        self.assertEqual(window.current_index, 1)
        self.assertEqual(window.canvas.selection_rect, region)
        self.assertIsNotNone(window.canvas.color_consolidation_overlay_image)
        self.assertEqual(window.canvas.color_consolidation_stats["matchedPixelCount"], 2)


if __name__ == "__main__":
    unittest.main()
