import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sprite_maker.models import RGBA_FORMAT
from sprite_maker.sprite_import_dialog import SpriteImportDialog
from test_sprite_analysis import make_sheet


class SpriteImportDialogTests(unittest.TestCase):
    def drop_files(self, widget, urls):
        mime = QMimeData()
        mime.setUrls(urls)
        enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(widget, enter)
        drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(widget, drop)
        return enter.isAccepted(), drop.isAccepted()

    def test_drop_on_dialog_and_child_surfaces_loads_first_supported_image(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sheet.PNG"
            other = Path(directory) / "other.png"
            self.make_sheet(path)
            self.make_sheet(other)
            dialog = SpriteImportDialog()
            self.addCleanup(dialog.close)
            for widget in (dialog, dialog.sheet_preview, dialog.animation_preview,
                           dialog.frame_list.viewport(), dialog.grid_x_spin):
                with self.subTest(widget=type(widget).__name__):
                    dialog.source_path = None
                    with patch.object(dialog, "load_sheet", wraps=dialog.load_sheet) as load:
                        accepted = self.drop_files(widget, [QUrl("https://example.com/no.png"),
                            QUrl.fromLocalFile(str(path)), QUrl.fromLocalFile(str(other))])
                        self.assertEqual(accepted, (True, True))
                        self.assertEqual(load.call_count, 0)
                        self.app.processEvents()
                        self.assertEqual(load.call_count, 1)
                        self.assertEqual(dialog.source_path, path)
                        self.assertEqual(len(dialog.frames), 16)

    def test_drop_rejects_nonimages_and_missing_files(self):
        dialog = SpriteImportDialog()
        self.addCleanup(dialog.close)
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "folder.png"
            folder.mkdir()
            for url in (QUrl.fromLocalFile(str(folder)), QUrl("https://example.com/a.png"),
                        QUrl.fromLocalFile(str(folder / "missing.png")), QUrl.fromLocalFile(str(folder / "video.mp4"))):
                self.assertEqual(self.drop_files(dialog, [url]), (False, False))
            self.assertFalse(dialog.drop_timer.isActive())

    def test_corrupt_drop_preserves_source_and_closing_cancels_pending_drop(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sheet.png"
            corrupt = Path(directory) / "broken.png"
            self.make_sheet(path)
            corrupt.write_bytes(b"not an image")
            dialog = SpriteImportDialog()
            self.addCleanup(dialog.close)
            dialog.load_sheet(path)
            previous = dialog.source_image.copy()
            with patch("sprite_maker.sprite_import_dialog.QMessageBox.warning") as warning:
                self.drop_files(dialog, [QUrl.fromLocalFile(str(corrupt))])
                self.app.processEvents()
                warning.assert_called_once()
            self.assertEqual(dialog.source_path, path)
            self.assertEqual(dialog.source_image, previous)
            with patch.object(dialog, "load_sheet") as load:
                self.drop_files(dialog, [QUrl.fromLocalFile(str(path))])
                dialog.reject()
                self.app.processEvents()
                load.assert_not_called()

    def test_window_controls_fullscreen_escape_restore_maximized(self):
        dialog = SpriteImportDialog()
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint)
        self.assertTrue(dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint)
        self.assertTrue(dialog.isSizeGripEnabled())
        dialog.show()
        self.app.processEvents()
        dialog.fullscreen_action.trigger()
        self.app.processEvents()
        self.assertTrue(dialog.isFullScreen())
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(dialog.isFullScreen())
        self.assertTrue(dialog.isVisible())
        dialog.showMaximized()
        dialog.toggle_fullscreen()
        self.assertTrue(dialog.isFullScreen())
        dialog.toggle_fullscreen()
        self.assertTrue(dialog.isMaximized())
        dialog.showMinimized()
        self.assertTrue(dialog.isMinimized())

    def test_collapsed_settings_free_preview_space_and_preserve_values(self):
        dialog = SpriteImportDialog()
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        dialog.grid_x_spin.setValue(-15)
        before = dialog.content_splitter.height()
        dialog.settings_button.click()
        self.app.processEvents()
        self.assertFalse(dialog.settings_tabs.isVisible())
        self.assertGreater(dialog.content_splitter.height(), before)
        dialog.settings_button.click()
        self.assertTrue(dialog.settings_tabs.isVisible())
        self.assertEqual(dialog.grid_x_spin.value(), -15)
        self.assertFalse(dialog.split_button.autoDefault())

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

    def test_auto_detect_single_refresh_empty_recheck_and_manual_recompute(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "auto.png"
            make_sheet((0, 255, 0)).save(str(path))
            dialog = SpriteImportDialog()
            self.addCleanup(dialog.close)
            dialog.load_sheet(path)
            dialog.background_combo.setCurrentIndex(1)
            with patch.object(dialog, "refresh_split", wraps=dialog.refresh_split) as refresh:
                dialog.auto_detect_grid()
                self.assertEqual(refresh.call_count, 1)
                self.assertFalse(dialog.refresh_timer.isActive())
            layout = dialog.current_layout()
            self.assertEqual((layout.grid_x, layout.grid_y, layout.grid_width, layout.grid_height), (7, 9, 92, 98))
            self.assertEqual(dialog.sheet_preview.grid_rect, QRect(7, 9, 92, 98))
            self.assertEqual(dialog.frame_list.count(), 16)
            self.assertIn("EMPTY", dialog.frame_list.item(6).text())
            self.assertNotIn(6, dialog.selected_indices())
            dialog.frame_list.item(6).setCheckState(Qt.CheckState.Checked)
            self.assertIn(6, dialog.selected_indices())
            dialog.refresh_split()
            self.assertIn(6, dialog.selected_indices())
            # Move a single manual cell into an entirely green region.
            dialog._set_values(dict(columns=1, rows=1, grid_x=0, grid_y=0, grid_width=5, grid_height=5))
            dialog.refresh_split()
            self.assertEqual(dialog.empty_frames, [True])
            self.assertEqual(dialog.selected_indices(), [])
            dialog.grid_x_spin.setValue(7)
            dialog.grid_y_spin.setValue(9)
            dialog.refresh_split()
            self.assertEqual(dialog.empty_frames, [False])
            self.assertEqual(dialog.selected_indices(), [0])

    def test_failed_detection_preserves_manual_parameters(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "blank.png"
            image = QImage(40, 40, RGBA_FORMAT)
            image.fill(Qt.GlobalColor.transparent)
            image.save(str(path))
            dialog = SpriteImportDialog()
            self.addCleanup(dialog.close)
            dialog.load_sheet(path)
            before = dialog.current_layout()
            dialog.auto_detect_grid()
            self.assertEqual(dialog.current_layout(), before)
            self.assertIn("No foreground", dialog.warnings_label.text())

    def test_drag_resize_all_handles_zoom_clamp_and_no_thumbnail_rebuild_during_move(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "large.png"
            image = QImage(500, 400, RGBA_FORMAT)
            image.fill(QColor("red"))
            image.save(str(path))
            dialog = SpriteImportDialog()
            self.addCleanup(dialog.close)
            dialog.load_sheet(path)
            preview = dialog.sheet_preview
            cases = {
                "expand_lt": ((50, 50), (-90, -80), QRect(-40, -30, 290, 240)),
                "expand_rb": ((250, 210), (300, 250), QRect(50, 50, 500, 410)),
                "move": ((150, 120), (20, 10), QRect(70, 60, 200, 160)),
                "l": ((50, 130), (20, 0), QRect(70, 50, 180, 160)),
                "r": ((250, 130), (20, 0), QRect(50, 50, 220, 160)),
                "t": ((150, 50), (0, 10), QRect(50, 60, 200, 150)),
                "b": ((150, 210), (0, 10), QRect(50, 50, 200, 170)),
                "lt": ((50, 50), (20, 10), QRect(70, 60, 180, 150)),
                "rt": ((250, 50), (20, 10), QRect(50, 60, 220, 150)),
                "lb": ((50, 210), (20, 10), QRect(70, 50, 180, 170)),
                "rb": ((250, 210), (20, 10), QRect(50, 50, 220, 170)),
                "outside": ((150, 120), (-1000, -1000), QRect(-950, -950, 200, 160)),
                "minimum": ((250, 210), (-1000, -1000), QRect(50, 50, 4, 4)),
            }
            for zoom in (0.5, 1, 2):
                for name, (start, delta, expected) in cases.items():
                    with self.subTest(zoom=zoom, handle=name):
                        dialog._set_values(dict(grid_x=50, grid_y=50, grid_width=200, grid_height=160))
                        dialog.refresh_split()
                        preview.setZoom(zoom)
                        start = preview.imageToWidget(QPointF(*start)).toPoint()
                        end = start + (QPointF(*delta) * zoom).toPoint()
                        with patch.object(dialog, "populate_frame_list", wraps=dialog.populate_frame_list) as populate:
                            QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=start)
                            move = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(end),
                                               Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                            self.app.sendEvent(preview, move)
                            self.assertEqual(populate.call_count, 0)
                            self.assertFalse(dialog.refresh_timer.isActive())
                            QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=end)
                            self.assertEqual(populate.call_count, 1)
                        self.assertEqual(preview.grid_rect, expected)
                        self.assertEqual(dialog.grid_x_spin.value(), expected.x())
                        self.assertEqual(dialog.grid_y_spin.value(), expected.y())
                        self.assertEqual(dialog.grid_width_spin.value(), expected.width())
                        self.assertEqual(dialog.grid_height_spin.value(), expected.height())
            dialog.grid_width_spin.setValue(100)
            self.assertEqual(preview.grid_rect.width(), 100)

    def test_accept_flushes_pending_geometry(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sheet.png"
            self.make_sheet(path)
            dialog = SpriteImportDialog()
            self.addCleanup(dialog.close)
            dialog.load_sheet(path)
            dialog.columns_spin.setValue(2)
            dialog.rows_spin.setValue(2)
            dialog.accept_split()
            self.assertEqual(len(dialog.import_images), 4)
            self.assertEqual(dialog.import_images[0].width(), 2)

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

    def test_horizontal_and_vertical_spacing_accept_negative_values(self) -> None:
        dialog = SpriteImportDialog()

        dialog.horizontal_spacing_spin.setValue(-12)
        dialog.vertical_spacing_spin.setValue(-8)

        self.assertEqual(dialog.horizontal_spacing_spin.value(), -12)
        self.assertEqual(dialog.vertical_spacing_spin.value(), -8)
        self.assertEqual(dialog.horizontal_spacing_spin.minimum(), -4096)
        self.assertEqual(dialog.vertical_spacing_spin.minimum(), -4096)
        self.assertEqual(dialog.current_layout().horizontal_spacing, -12)
        self.assertEqual(dialog.current_layout().vertical_spacing, -8)
        self.assertEqual(dialog.grid_x_spin.minimum(), -1000000)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
