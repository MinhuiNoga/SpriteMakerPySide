from __future__ import annotations

from .video_import_v4 import VideoImportDialogV4


class VideoImportDialogV401(VideoImportDialogV4):
    """4.0.1 integration fixes layered on the 4.x importer."""

    def refresh_frame_list(self) -> None:
        # QListWidget can emit itemChanged while thumbnails are reconstructed.
        # A visual rebuild is not a semantic frame-selection change, so preserve
        # the combat timeline here. Real user check/uncheck events still flow
        # through on_frame_check_changed with suppression disabled.
        previous_suppression = self._suppress_timeline_invalidation
        self._suppress_timeline_invalidation = True
        try:
            super().refresh_frame_list()
        finally:
            self._suppress_timeline_invalidation = previous_suppression
