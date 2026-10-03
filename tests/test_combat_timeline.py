import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication

from sprite_maker.combat_timeline import CombatTimeline, build_animation_manifest, suggest_combat_timeline
from sprite_maker.models import make_blank_image
from sprite_maker.video_import_dialog import ExtractedVideoFrame
from sprite_maker.video_import_v401 import VideoImportDialogV401


def motion_frame(x: int, width: int = 96, height: int = 64):
    image = make_blank_image(width, height)
    painter = QPainter(image)
    painter.fillRect(QRect(x, 20, 18, 28), QColor("white"))
    painter.end()
    return image


class CombatTimelineLogicTests(unittest.TestCase):
    def test_validate_requires_hit_frames_inside_active(self):
        with self.assertRaises(ValueError):
            CombatTimeline(8, 2, 5, hit_frames=(1,)).validate()
        timeline = CombatTimeline(8, 2, 5, hit_frames=(3, 4), cancel_frame=5).validate()
        self.assertEqual(timeline.phase_for_index(0), "startup")
        self.assertEqual(timeline.phase_for_index(2), "active")
        self.assertEqual(timeline.phase_for_index(6), "recovery")

    def test_suggestion_creates_contiguous_arpg_phases(self):
        images = [motion_frame(x) for x in (8, 8, 10, 18, 36, 48, 50, 50, 50)]
        timeline = suggest_combat_timeline(images, fps=12, animation_name="slash")
        self.assertEqual(timeline.frame_count, len(images))
        self.assertLess(timeline.startup_end, timeline.active_end)
        self.assertTrue(timeline.hit_frames)
        self.assertTrue(all(timeline.startup_end <= value < timeline.active_end for value in timeline.hit_frames))
        self.assertEqual(timeline.animation_name, "slash")

    def test_manifest_keeps_runtime_and_source_mapping(self):
        timeline = CombatTimeline(
            frame_count=5,
            startup_end=2,
            active_end=4,
            hit_frames=(2,),
            cancel_frame=4,
            animation_name="attack_01",
            fps=10,
        ).validate()
        manifest = build_animation_manifest(
            timeline,
            extraction_indices=[1, 3, 4, 8, 9],
            source_indices=[10, 30, 40, 80, 90],
            timestamps=[0.1, 0.3, 0.4, 0.8, 0.9],
        )
        self.assertEqual(manifest["app_version"], "4.0.1")
        self.assertEqual(manifest["index_base"], 0)
        self.assertEqual(manifest["phases"]["active"], {"start": 2, "end_exclusive": 4})
        self.assertTrue(manifest["frames"][2]["hit"])
        self.assertEqual(manifest["frames"][3]["source_index"], 80)


class CombatTimelineDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = VideoImportDialogV401()
        frames = []
        for index, x in enumerate((8, 8, 10, 18, 36, 48, 50, 50)):
            frames.append(
                ExtractedVideoFrame(
                    image=motion_frame(x),
                    timestamp=index / 12.0,
                    source_index=index,
                    target_timestamp=index / 12.0,
                )
            )
        self.dialog.on_extract_finished(frames)

    def tearDown(self):
        self.dialog.close()
        self.app.processEvents()

    def test_auto_timeline_is_saved_in_project_and_invalidated_by_reselection(self):
        self.dialog.animation_name_edit.setText("slash")
        self.dialog.auto_suggest_combat_timeline()
        self.assertIsNotNone(self.dialog.combat_timeline)
        payload = self.dialog._project_payload()
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["app_branch"], "4.0.1")
        self.assertEqual(payload["combat_timeline"]["animation_name"], "slash")

        first = self.dialog.frame_list.item(0)
        first.setCheckState(Qt.CheckState.Unchecked)
        self.app.processEvents()
        self.assertIsNone(self.dialog.combat_timeline)
        self.assertFalse(self.dialog.export_animation_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
