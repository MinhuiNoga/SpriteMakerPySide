import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPainter

from sprite_maker.models import make_blank_image
from sprite_maker.motion_analysis import MotionAnalysisResult, analyze_motion


def pose(x: int, y: int = 10, extra: int = 0):
    image = make_blank_image(48, 48)
    painter = QPainter(image)
    painter.fillRect(QRect(x, y, 10, 22), QColor("white"))
    painter.fillRect(QRect(x + 2 + extra, y + 4, 4, 4), QColor("red"))
    painter.end()
    return image


class MotionAnalysisTests(unittest.TestCase):
    def test_repeated_unique_pose_sequence_produces_loop_candidate(self):
        cycle = [pose(5, extra=0), pose(10, extra=1), pose(15, extra=2), pose(20, extra=3)]
        result = analyze_motion(cycle * 3, fps=12, mode="loop")
        self.assertTrue(result.loop_candidates)
        self.assertIsNotNone(result.recommended)
        self.assertEqual(result.recommended.period, 4)
        self.assertGreater(result.recommended.confidence, 0.35)

    def test_departure_and_return_produces_one_shot_range(self):
        frames = [pose(5)] * 3 + [pose(9), pose(14), pose(20), pose(15), pose(10)] + [pose(5)] * 3
        result = analyze_motion(frames, fps=12, mode="one_shot")
        self.assertIsNotNone(result.one_shot)
        self.assertIsNotNone(result.recommended)
        self.assertLessEqual(result.recommended.start, 3)
        self.assertGreaterEqual(result.recommended.end, 7)

    def test_result_round_trip_is_lossless_for_project_json(self):
        cycle = [pose(5), pose(10), pose(15), pose(20)] * 2
        result = analyze_motion(cycle, fps=12, mode="auto")
        restored = MotionAnalysisResult.from_dict(result.to_dict())
        self.assertEqual(restored.mode, result.mode)
        self.assertEqual(restored.jolt_indices, result.jolt_indices)
        self.assertEqual(restored.frame_count, result.frame_count)
        self.assertEqual(restored.recommended, result.recommended)


if __name__ == "__main__":
    unittest.main()
