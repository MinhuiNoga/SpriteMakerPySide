import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from sprite_maker.image_ops import alpha_aware_gaussian_blur, array_to_qimage, qimage_to_array
from sprite_maker.models import Frame, Layer, frame_from_qimage
from sprite_maker.widgets import CanvasWidget


class AlphaAwareGaussianBlurTests(unittest.TestCase):
    def test_preserve_alpha_ignores_hidden_transparent_rgb(self) -> None:
        source = np.zeros((9, 9, 4), dtype=np.uint8)
        source[:, :, :3] = (0, 255, 0)
        source[3:6, 3:6] = (200, 20, 30, 255)

        result = alpha_aware_gaussian_blur(source, radius=3, preserve_alpha=True)

        np.testing.assert_array_equal(result[:, :, 3], source[:, :, 3])
        np.testing.assert_array_equal(result[source[:, :, 3] == 0, :3], source[source[:, :, 3] == 0, :3])
        self.assertLess(float(result[4, 4, 1]), 30.0)

    def test_optional_alpha_blur_softens_the_shape(self) -> None:
        source = np.zeros((9, 9, 4), dtype=np.uint8)
        source[4, 4] = (255, 0, 0, 255)

        result = alpha_aware_gaussian_blur(source, radius=2, preserve_alpha=False)

        self.assertLess(float(result[4, 4, 3]), 255.0)
        self.assertGreater(float(result[4, 3, 3]), 0.0)


class CanvasBlurBrushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_canvas(self) -> tuple[CanvasWidget, np.ndarray]:
        source = np.zeros((32, 32, 4), dtype=np.uint8)
        source[:, :16] = (220, 30, 30, 255)
        source[:, 16:] = (20, 40, 220, 255)
        canvas = CanvasWidget()
        canvas.set_frame(frame_from_qimage(array_to_qimage(source), "test.png"))
        canvas.tool = "pen"
        canvas.brush_size = 14
        canvas.blur_brush_enabled = True
        canvas.blur_brush_strength = 1.0
        canvas.blur_brush_radius = 4
        canvas.blur_brush_hardness = 1.0
        canvas.blur_brush_preserve_alpha = True
        return canvas, source

    def test_blur_brush_changes_only_selected_pixels(self) -> None:
        canvas, source = self.make_canvas()
        canvas.selection_rect = QRect(14, 8, 4, 16)

        canvas._begin_brush_stroke()
        canvas._draw_blur_brush_line(QPoint(16, 6), QPoint(16, 25))
        result = qimage_to_array(canvas.frame.active_layer.image)

        selection = np.zeros((32, 32), dtype=bool)
        selection[8:24, 14:18] = True
        np.testing.assert_array_equal(result[~selection], source[~selection])
        self.assertTrue(np.any(result[selection] != source[selection]))

    def test_lasso_selection_constrains_blur(self) -> None:
        canvas, source = self.make_canvas()
        canvas.lasso_points = [QPoint(14, 8), QPoint(18, 8), QPoint(18, 24), QPoint(14, 24)]

        canvas._begin_brush_stroke()
        selection = canvas._brush_selection_mask.copy()
        canvas._draw_blur_brush_line(QPoint(16, 6), QPoint(16, 25))
        result = qimage_to_array(canvas.frame.active_layer.image)

        np.testing.assert_array_equal(result[~selection], source[~selection])
        self.assertTrue(np.any(result[selection] != source[selection]))

    def test_repeating_a_segment_in_one_stroke_is_stable(self) -> None:
        canvas, _ = self.make_canvas()

        canvas._begin_brush_stroke()
        canvas._draw_blur_brush_line(QPoint(16, 8), QPoint(16, 24))
        first_result = qimage_to_array(canvas.frame.active_layer.image)
        canvas._draw_blur_brush_line(QPoint(16, 8), QPoint(16, 24))
        second_result = qimage_to_array(canvas.frame.active_layer.image)

        np.testing.assert_array_equal(second_result, first_result)

    def test_preserve_alpha_keeps_layer_alpha(self) -> None:
        canvas, source = self.make_canvas()
        source[:, :, 3] = np.arange(32, dtype=np.uint8)[None, :] * 8
        canvas.set_frame(frame_from_qimage(array_to_qimage(source), "alpha.png"))

        canvas._begin_brush_stroke()
        canvas._draw_blur_brush_line(QPoint(16, 8), QPoint(16, 24))
        result = qimage_to_array(canvas.frame.active_layer.image)

        np.testing.assert_array_equal(result[:, :, 3], source[:, :, 3])

    def test_blur_brush_changes_only_active_layer_and_does_not_paint_current_color(self) -> None:
        canvas, source = self.make_canvas()
        lower = np.full((32, 32, 4), (10, 180, 60, 255), dtype=np.uint8)
        frame = Frame(
            "layers.png",
            [Layer("lower", array_to_qimage(lower)), Layer("active", array_to_qimage(source))],
            active_layer_index=1,
        )
        canvas.set_frame(frame)
        canvas.color.setRgb(0, 255, 0, 255)

        canvas._begin_brush_stroke()
        canvas._draw_blur_brush_line(QPoint(16, 8), QPoint(16, 24))

        np.testing.assert_array_equal(qimage_to_array(frame.layers[0].image), lower)
        result = qimage_to_array(frame.active_layer.image)
        self.assertTrue(np.any(result != source))
        self.assertLessEqual(int(result[:, :, 1].max()), 40)


if __name__ == "__main__":
    unittest.main()
