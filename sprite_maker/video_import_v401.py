from __future__ import annotations

from .video_import_v4 import VideoImportDialogV4


class VideoImportDialogV401(VideoImportDialogV4):
    """4.0.1 integration fixes layered on the 4.x importer."""

    def _with_programmatic_item_updates(self, callback) -> None:
        """Run QListWidget metadata changes without treating them as user selection edits."""
        previous_suppression = self._suppress_timeline_invalidation
        self._suppress_timeline_invalidation = True
        try:
            callback()
        finally:
            self._suppress_timeline_invalidation = previous_suppression

    def refresh_frame_list(self) -> None:
        # QListWidget can emit itemChanged while thumbnails are reconstructed.
        # A visual rebuild is not a semantic frame-selection change, so preserve
        # the combat timeline here. Real user check/uncheck events still flow
        # through on_frame_check_changed with suppression disabled.
        self._with_programmatic_item_updates(super().refresh_frame_list)

    def _apply_combat_item_roles(self) -> None:
        # setData() itself emits itemChanged. S/A/R/HIT/C badges are presentation
        # metadata, not a frame check-state edit, and must not invalidate the
        # timeline they describe.
        self._with_programmatic_item_updates(super()._apply_combat_item_roles)

    def _apply_motion_item_roles(self) -> None:
        # Motion QA badges use the same QListWidget data channel and therefore
        # require the same guard when a combat timeline already exists.
        self._with_programmatic_item_updates(super()._apply_motion_item_roles)
