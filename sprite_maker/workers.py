from __future__ import annotations

from typing import List

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .image_ops import erase_color
from .models import Frame


class WorkerSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(list)
    failed = Signal(str)


class UniversalEraseWorker(QRunnable):
    def __init__(self, frames: List[Frame], target_rgba, tolerance: int):
        super().__init__()
        self.frames = [frame.clone() for frame in frames]
        self.target_rgba = target_rgba
        self.tolerance = tolerance
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            total = sum(len(frame.layers) for frame in self.frames)
            done = 0
            for frame in self.frames:
                for layer in frame.layers:
                    layer.image = erase_color(layer.image, self.target_rgba, self.tolerance, contiguous=False)
                    done += 1
                    self.signals.progress.emit(done, total)
                frame.mark_dirty()
            self.signals.finished.emit(self.frames)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
