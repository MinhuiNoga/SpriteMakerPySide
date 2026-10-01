import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QDialog

from sprite_maker.alignment_dialog import FootAlignmentDialog, detect_foot_anchor
from sprite_maker.app import MainWindow
from sprite_maker.models import frame_from_qimage, make_blank_image


def silhouette(dx=0, dy=0):
    image = make_blank_image(100, 100)
    painter = QPainter(image)
    for rect in (QRect(35, 15, 30, 45), QRect(30, 55, 12, 30), QRect(58, 55, 12, 32)):
        painter.fillRect(rect.translated(dx, dy), QColor("red"))
    painter.end()
    return image


class AlignmentSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.frames = [frame_from_qimage(silhouette(), "a"), frame_from_qimage(silhouette(8, 4), "b")]
        self.window.after_project_changed("test")
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.reject()
        self.window.close()
        self.app.processEvents()

    def open_dialog(self, index=0):
        dialog = FootAlignmentDialog(self.window.frames, self.window.export_size(), index,
                                     session=self.window._alignment_session)
        self.dialogs.append(dialog)
        return dialog

    def apply(self, dialog, accepted=True):
        with patch("sprite_maker.app.FootAlignmentDialog", return_value=dialog), patch.object(
            FootAlignmentDialog, "exec", return_value=QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
        ):
            self.window.show_foot_alignment()

    def test_minus_168_survives_reopen_without_double_application(self):
        first = self.open_dialog()
        first.dx.setValue(-168)
        self.apply(first)
        center = self.window.frames[0].export_center
        second = self.open_dialog()
        self.assertEqual(second.dx.value(), -168)
        self.apply(second)
        self.assertEqual(self.window.frames[0].export_center, center)
        self.assertEqual(len(self.window.undo_stack), 1)
        third = self.open_dialog()
        third.dx.setValue(-170)
        self.apply(third)
        self.assertEqual(self.window.frames[0].export_center[0], center[0] + 2)
        self.window.undo()
        self.assertEqual(self.open_dialog().dx.value(), -168)
        self.window.redo()
        self.assertEqual(self.open_dialog().dx.value(), -170)

    def test_cancel_leaves_previous_values_and_reference_unchanged(self):
        first = self.open_dialog()
        first.begin_reference()
        first.pick_anchor(QPoint(35, 84))
        first.dx.setValue(-168)
        self.apply(first)
        second = self.open_dialog()
        self.assertEqual(second.canvas.anchor, QPoint(35, 84))
        self.assertIsNotNone(second.canvas.target)
        reference = second.canvas.reference.composite().copy()
        second.dx.setValue(42)
        second.begin_reference()
        second.pick_anchor(QPoint(63, 86))
        self.apply(second, accepted=False)
        third = self.open_dialog()
        self.assertEqual(third.dx.value(), -168)
        self.assertEqual(third.canvas.anchor, QPoint(35, 84))
        self.assertEqual(third.canvas.reference.composite(), reference)
        # Editing the project later must not alter the frozen reference snapshot.
        self.window.frames[0].layers[0].image.fill(QColor("blue"))
        self.window.frames[0].mark_dirty()
        self.assertEqual(third.canvas.reference.composite(), reference)

    def test_reset_restores_initial_baseline_after_reopen(self):
        first = self.open_dialog()
        first.dx.setValue(-168)
        self.apply(first)
        second = self.open_dialog()
        second.reset_current()
        self.assertEqual(second.dx.value(), 0)
        self.apply(second)
        self.assertEqual(self.window.frames[0].export_center, (50, 50))

    def test_metadata_follows_reorder_clone_and_workspace_expansion(self):
        first = self.open_dialog()
        first.begin_reference()
        first.pick_anchor(QPoint(35, 84))
        first.dx.setValue(-168)
        self.apply(first)
        self.window.frames.reverse()
        self.assertEqual(self.open_dialog(1).dx.value(), -168)
        self.window.frames = [frame.clone() for frame in self.window.frames]
        self.window.expand_workspace(12, 7, 0, 0)
        reopened = self.open_dialog(1)
        self.assertEqual(reopened.dx.value(), -168)
        self.assertEqual(reopened.canvas.anchor, QPoint(47, 91))

    def test_exit_editor_and_new_project_clear_session(self):
        first = self.open_dialog()
        first.auto_anchor(True)
        self.apply(first)
        self.assertIsNotNone(self.window._alignment_session)
        self.window.reset_editor_for_video_import()
        self.assertIsNone(self.window._alignment_session)
        self.assertEqual(self.window.frames, [])
        self.window.replace_with_sprite_frames([silhouette()])
        self.assertEqual(self.open_dialog().dx.value(), 0)
        dialog = self.open_dialog()
        dialog.auto_anchor()
        self.apply(dialog)
        self.window.close()
        self.assertIsNone(self.window._alignment_session)
        self.assertIsNone(self.window.frames[0].alignment_anchor)

    def test_auto_estimates_both_feet_and_ignores_disconnected_noise(self):
        image = silhouette()
        image.setPixelColor(5, 98, QColor("white"))
        left = detect_foot_anchor(image, 0)
        right = detect_foot_anchor(image, 1)
        middle = detect_foot_anchor(image, 2)
        self.assertTrue(30 <= left.x() <= 41)
        self.assertEqual(left.y(), 84)
        self.assertTrue(58 <= right.x() <= 69)
        self.assertEqual(right.y(), 86)
        self.assertEqual(middle.y(), 86)
        self.assertTrue(left.x() < middle.x() < right.x())

    def test_auto_all_aligns_shifted_silhouettes_and_keeps_manual_points(self):
        dialog = self.open_dialog()
        dialog.auto_anchor(True)
        self.assertEqual(dialog.frames[1].export_center, (58, 54))
        self.assertEqual(dialog.dx.value(), 0)
        self.apply(dialog)
        reopened = self.open_dialog(1)
        self.assertEqual(reopened.dx.value(), -8)
        self.assertEqual(reopened.dy.value(), -4)
        before = dict(reopened.anchors)
        reopened.auto_side.setCurrentIndex(1)
        reopened.auto_anchor(True)
        self.assertEqual(reopened.anchors, before)

    def test_auto_skips_blank_or_opaque_background_without_mutation(self):
        blank = make_blank_image(100, 100)
        opaque = blank.copy()
        opaque.fill(QColor("black"))
        self.assertIsNone(detect_foot_anchor(blank))
        self.assertIsNone(detect_foot_anchor(opaque))
        self.window.frames.append(frame_from_qimage(blank, "blank"))
        dialog = self.open_dialog()
        dialog.auto_anchor(True)
        self.assertNotIn(2, dialog.anchors)
        self.assertEqual(dialog.frames[2].export_center, (50, 50))


if __name__ == "__main__":
    unittest.main()
