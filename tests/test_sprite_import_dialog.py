import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from sprite_maker.models import RGBA_FORMAT
from sprite_maker.sprite_import_dialog import SpriteImportDialog


class SpriteImportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_sheet(self, path: Path, width: int = 4, height: int = 4) -> None:
        image = QImage(width, height, RGBA_FORMAT)
        image.fill(Qt.GlobalColor.transparent)
        colors = [QColor("red"), QColor("green"), QColor("blue"), QColor("yellow")]
        for index, color in enumerate(colors):
            left = (index % 2) * 2
            top = (index // 2) * 2
            for y in range(top, min(top + 2, height)):
                for x in range(left, min(left + 2, width)):
                    image.setPixelColor(x, y, color)
        self.assertTrue(image.save(str(path), "PNG"))

    def test_unchecked_cells_are_not_returned(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sheet.png"
            self.make_sheet(path)
            dialog = SpriteImportDialog(initial_directory=path.parent)
            dialog.columns_spin.setValue(2)
            dialog.rows_spin.setValue(2)

            self.assertTrue(dialog.load_sheet(path))
            dialog.frame_list.item(1).setCheckState(Qt.CheckState.Unchecked)

            self.assertEqual(dialog.selected_indices(), [0, 2, 3])
            dialog.accept_split()
            self.assertEqual(len(dialog.import_images), 3)
            self.assertEqual(
                [image.pixelColor(0, 0).name() for image in dialog.import_images],
                ["#ff0000", "#0000ff", "#ffff00"],
            )
            dialog.close()

    def test_non_divisible_sheet_reports_transparent_padding(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "odd-sheet.png"
            self.make_sheet(path, width=5, height=3)
            dialog = SpriteImportDialog(initial_directory=path.parent)
            dialog.columns_spin.setValue(2)
            dialog.rows_spin.setValue(2)

            self.assertTrue(dialog.load_sheet(path))

            self.assertIsNotNone(dialog.geometry)
            self.assertEqual((dialog.geometry.padding_right, dialog.geometry.padding_bottom), (1, 1))
            self.assertEqual(dialog.frames[-1].pixelColor(2, 1).alpha(), 0)
            dialog.close()


if __name__ == "__main__":
    unittest.main()
