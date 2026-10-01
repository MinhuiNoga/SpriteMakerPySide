import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtWidgets import QApplication

from sprite_maker.models import RGBA_FORMAT
from sprite_maker.sprite_grid_preview import SpriteGridPreviewWidget
from sprite_maker.sprite_ops import SpriteSheetLayout


class SpriteGridPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_control_wheel_preserves_source_rect(self):
        widget = SpriteGridPreviewWidget()
        self.addCleanup(widget.close)
        image = QImage(500, 400, RGBA_FORMAT)
        image.fill(Qt.GlobalColor.transparent)
        widget.setImage(image)
        widget.setGrid(SpriteSheetLayout(4, 4, 10, 20, 300, 300))
        rect = widget.grid_rect
        event = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(widget, event)
        self.assertGreater(widget._zoom, 1.0)
        self.assertEqual(widget.grid_rect, rect)
        point = QPointF(23, 45)
        self.assertAlmostEqual(widget._image_point(widget.imageToWidget(point)).x(), point.x())


if __name__ == "__main__":
    unittest.main()
