import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog

from sprite_maker.app import MainWindow, ProjectState
from sprite_maker.models import RGBA_FORMAT, frame_from_qimage
from sprite_maker.startup_dialog import StartupDialog


def solid_image(color: str) -> QImage:
    image = QImage(3, 2, RGBA_FORMAT)
    image.fill(QColor(color))
    return image


class SpriteImportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_startup_dialog_exposes_sprite_workflow(self) -> None:
        dialog = StartupDialog()
        dialog.choose_sprite()

        self.assertEqual(dialog.choice, StartupDialog.SPRITE)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_replace_clears_history_and_renames_selected_frames(self) -> None:
        window = MainWindow()
        old_frame = frame_from_qimage(solid_image("black"), "old.png")
        window.frames = [old_frame]
        window.undo_stack = [ProjectState([old_frame.clone()], 0)]
        window.redo_stack = [ProjectState([old_frame.clone()], 0)]
        source_path = Path("C:/images/character-sheet.png")

        window.replace_with_sprite_frames(
            [solid_image("red"), solid_image("blue")],
            source_path,
        )

        self.assertEqual([frame.name for frame in window.frames], [
            "sprite_frame_0001.png",
            "sprite_frame_0002.png",
        ])
        self.assertEqual([frame.source_path for frame in window.frames], [source_path, source_path])
        self.assertEqual(window.undo_stack, [])
        self.assertEqual(window.redo_stack, [])
        self.assertEqual(window.current_index, 0)
        window.close()


if __name__ == "__main__":
    unittest.main()
