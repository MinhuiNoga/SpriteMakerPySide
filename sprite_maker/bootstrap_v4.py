from __future__ import annotations


def install(app_module) -> None:
    """Install 4.0.1 UI extensions without modifying the 3.x editor core."""
    from .video_import_v401 import VideoImportDialogV401

    app_module.VideoImportDialog = VideoImportDialogV401
