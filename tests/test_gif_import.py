import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from sprite_maker.video_import_dialog import VideoImportDialog
from sprite_maker.video_ops import (
    extract_video_frames,
    gif_frame_index_at,
    is_animated_gif,
    read_gif_animation,
    read_video_metadata,
)


def make_gif(path: Path, durations=(100, 300, 200)) -> None:
    colors = [(220, 20, 20, 255), (20, 220, 20, 255), (20, 20, 220, 255)]
    frames = []
    for color in colors[: len(durations)]:
        frame = Image.new("RGBA", (8, 6), (0, 0, 0, 0))
        frame.paste(color, (2, 1, 7, 5))
        frames.append(frame)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=list(durations),
        loop=0,
        disposal=2,
        transparency=0,
    )


class GifImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.gif_path = Path(self.temp_dir.name) / "timed.gif"
        make_gif(self.gif_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_reads_rgba_frames_and_variable_timing(self) -> None:
        animation = read_gif_animation(self.gif_path)

        self.assertEqual(len(animation.frames), 3)
        self.assertEqual(animation.frame_starts, [0.0, 0.1, 0.4])
        self.assertAlmostEqual(animation.duration, 0.6)
        self.assertEqual(animation.frames[0].pixelColor(0, 0).alpha(), 0)
        self.assertGreater(animation.frames[1].pixelColor(3, 2).green(), 180)
        self.assertEqual(gif_frame_index_at(animation, 0.099), 0)
        self.assertEqual(gif_frame_index_at(animation, 0.1), 1)
        self.assertEqual(gif_frame_index_at(animation, 0.399), 1)
        self.assertEqual(gif_frame_index_at(animation, 0.4), 2)

    def test_metadata_uses_average_fps_without_losing_delays(self) -> None:
        metadata = read_video_metadata(self.gif_path)

        self.assertEqual(metadata.frame_count, 3)
        self.assertAlmostEqual(metadata.duration, 0.6)
        self.assertAlmostEqual(metadata.fps, 5.0)
        self.assertEqual((metadata.width, metadata.height), (8, 6))

    def test_target_fps_sampling_holds_authored_gif_frames(self) -> None:
        progress = []
        frames = extract_video_frames(
            self.gif_path,
            start=0.0,
            end=0.5,
            target_fps=10.0,
            mode="sharp",
            progress_callback=lambda done, total: progress.append((done, total)),
        )

        self.assertEqual([frame.source_index for frame in frames], [0, 1, 1, 1, 2, 2])
        self.assertEqual([frame.extraction_mode for frame in frames], ["exact"] * 6)
        self.assertEqual([round(frame.target_timestamp, 1) for frame in frames], [0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertEqual(progress[-1], (6, 6))

    def test_distinguishes_animated_and_single_frame_gif(self) -> None:
        static_path = Path(self.temp_dir.name) / "static.gif"
        Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(static_path)

        self.assertTrue(is_animated_gif(self.gif_path))
        self.assertFalse(is_animated_gif(static_path))

    def test_import_dialog_uses_gif_preview_and_exact_extraction(self) -> None:
        dialog = VideoImportDialog()
        try:
            self.assertTrue(dialog.load_video(self.gif_path))
            self.assertIsNotNone(dialog.gif_animation)
            self.assertFalse(dialog.extraction_mode_combo.isEnabled())
            self.assertEqual(dialog.extraction_mode_combo.currentData(), "exact")
            dialog.seek_preview_to(0.2)
            self.assertGreater(dialog.current_video_image.pixelColor(3, 2).green(), 180)
            self.assertEqual(dialog.range_slider.playhead_value, 0.2)
        finally:
            dialog.reject()


if __name__ == "__main__":
    unittest.main()
