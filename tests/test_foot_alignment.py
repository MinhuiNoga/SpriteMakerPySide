import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from sprite_maker.alignment_dialog import FootAlignmentDialog
from sprite_maker.app import MainWindow, AnimationDialog, build_spritesheet_image, cropped_canvas_image
from sprite_maker.models import frame_from_qimage, make_blank_image


def marker_frame(x, y, width=24, height=24):
    image = make_blank_image(width, height)
    image.setPixelColor(x, y, QColor("red"))
    return frame_from_qimage(image, "foot.png")


class FootAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.frames = [marker_frame(6, 18), marker_frame(10, 20)]
        self.dialog = FootAlignmentDialog(self.frames, QSize(24, 24))

    def tearDown(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        self.app.processEvents()

    def align(self):
        self.dialog.begin_reference()
        self.dialog.pick_anchor(QPoint(6, 18))
        self.dialog.frame_list.setCurrentRow(1)
        self.dialog.pick_anchor(QPoint(10, 20))

    def test_anchor_aligns_export_pixels_without_changing_sources(self):
        before = self.frames[1].composite().copy()
        self.align()
        adjusted = self.dialog.frames[1]
        self.assertEqual(adjusted.export_center, (16, 14))
        self.assertEqual(self.frames[1].export_center, (12, 12))
        self.assertEqual(adjusted.composite(), before)
        result = cropped_canvas_image(adjusted.composite(), 24, 24, *adjusted.export_center)
        self.assertEqual(result.pixelColor(6, 18), QColor("red"))
        self.dialog.reject()
        self.assertEqual(self.frames[1].composite(), before)
        self.assertEqual(self.frames[1].export_center, (12, 12))

    def test_vertical_only_and_manual_nudge_reset(self):
        self.dialog.axis.setCurrentIndex(1)
        self.align()
        self.assertEqual(self.dialog.frames[1].export_center, (12, 14))
        self.dialog.dx.setValue(3)
        self.dialog.dy.setValue(-4)
        self.assertEqual(self.dialog.frames[1].export_center, (9, 16))
        self.dialog.reset_current()
        self.assertEqual(self.dialog.frames[1].export_center, (12, 12))
        self.assertIsNone(self.dialog.canvas.anchor)

    def test_reference_stays_fixed_after_edit_and_frame_switch(self):
        self.align()
        reference = self.dialog.canvas.reference
        self.dialog.frame_list.setCurrentRow(0)
        self.dialog.dx.setValue(5)
        self.assertEqual(reference.export_center, (12, 12))
        self.dialog.frame_list.setCurrentRow(1)
        self.assertEqual(self.dialog.canvas.anchor, QPoint(10, 20))
        self.assertEqual(self.dialog.dx.value(), -4)
        self.assertEqual(self.dialog.dy.value(), -2)

    def test_empty_frame_and_click_without_reference_do_not_change_center(self):
        self.dialog.pick_anchor(QPoint(6, 18))
        self.assertIsNone(self.dialog.canvas.target)
        blank = FootAlignmentDialog([frame_from_qimage(make_blank_image(24, 24), "blank")], QSize(24, 24))
        blank.begin_reference()
        blank.pick_anchor(QPoint(6, 18))
        self.assertIsNone(blank.canvas.target)
        self.assertFalse(blank.is_clipped(0))
        blank.reject()

    def test_clipping_guard_checks_all_frames_and_keeps_draft_on_decline(self):
        self.dialog.dx.setValue(100)
        self.assertTrue(self.dialog.is_clipped(0))
        self.dialog.frame_list.setCurrentRow(1)
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No) as warning:
            self.dialog.accept()
            warning.assert_called_once()
        self.assertNotEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.frames[0].export_center, (12, 12))
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            self.dialog.accept()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)

    def test_click_mapping_at_zoom_and_playback_cannot_edit(self):
        self.dialog.show()
        self.dialog.canvas.set_zoom(2)
        self.app.processEvents()
        self.dialog.begin_reference()
        canvas = self.dialog.canvas
        point = canvas._image_to_view_point(QPoint(6, 18)).toPoint()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(canvas.anchor, QPoint(6, 18))
        self.dialog.play.setChecked(True)
        self.dialog.pick_anchor(QPoint(1, 1))
        self.assertEqual(canvas.anchor, QPoint(6, 18))
        self.dialog.reject()
        self.assertFalse(self.dialog.timer.isActive())

    def test_odd_canvas_sizes_match_reference_in_actual_export(self):
        dialog = FootAlignmentDialog([marker_frame(6, 18, 25, 25), marker_frame(10, 20)], QSize(24, 24))
        dialog.begin_reference()
        dialog.pick_anchor(QPoint(6, 18))
        dialog.frame_list.setCurrentRow(1)
        dialog.pick_anchor(QPoint(10, 20))
        images = [cropped_canvas_image(f.composite(), 24, 24, *f.export_center) for f in dialog.frames]
        self.assertEqual(images[0], images[1])
        dialog.reject()

    def test_sheet_and_animation_use_same_alignment_as_png(self):
        self.align()
        frames = self.dialog.frames
        sheet = build_spritesheet_image(frames, 2, 0, 0, QColor("black"), QSize(24, 24))
        self.assertEqual(sheet.pixelColor(6, 18), QColor("red"))
        self.assertEqual(sheet.pixelColor(30, 18), QColor("red"))
        animation = AnimationDialog(frames, output_size=QSize(24, 24))
        self.assertEqual(animation.preview_image(frames[0]), animation.preview_image(frames[1]))
        animation.close()

    def test_one_pixel_nudge_on_odd_source_moves_exactly_one_pixel(self):
        dialog = FootAlignmentDialog([marker_frame(6, 18, 25, 25)], QSize(24, 24))
        for delta in (1, 2, 3, -1):
            dialog.dx.setValue(delta)
            frame = dialog.frames[0]
            output = cropped_canvas_image(frame.composite(), 24, 24, *frame.export_center)
            self.assertEqual(output.pixelColor(6 + delta, 18), QColor("red"))
        dialog.reject()

    def test_apply_is_one_undo_and_redo_preserves_pixels(self):
        self.align()
        window = MainWindow()
        window.frames = self.frames
        window.after_project_changed("test")
        with patch("sprite_maker.app.FootAlignmentDialog", return_value=self.dialog), patch.object(FootAlignmentDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            window.show_foot_alignment()
        self.assertEqual(len(window.undo_stack), 1)
        self.assertEqual(window.frames[1].export_center, (16, 14))
        expected = window.export_frame_image(window.frames[1])
        window.undo()
        self.assertEqual(window.frames[1].export_center, (12, 12))
        window.redo()
        self.assertEqual(window.export_frame_image(window.frames[1]), expected)
        window.close()

    def test_cancel_and_unchanged_apply_do_not_create_undo(self):
        window = MainWindow()
        window.frames = self.frames
        window.after_project_changed("test")
        for result in (QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted):
            with patch("sprite_maker.app.FootAlignmentDialog", return_value=self.dialog), patch.object(FootAlignmentDialog, "exec", return_value=result):
                window.show_foot_alignment()
        self.assertEqual(window.undo_stack, [])
        window.close()


if __name__ == "__main__":
    unittest.main()
