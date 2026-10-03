from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Optional, Sequence

import cv2
import numpy as np
from PySide6.QtGui import QImage

from .image_ops import qimage_to_array


@dataclass(frozen=True)
class CombatTimeline:
    """Runtime-oriented timing metadata for one ordered animation clip.

    All frame indices are zero-based. ``startup_end`` and ``active_end`` are
    exclusive boundaries so the three phases are always contiguous:

    startup  = [0, startup_end)
    active   = [startup_end, active_end)
    recovery = [active_end, frame_count)
    """

    frame_count: int
    startup_end: int
    active_end: int
    hit_frames: tuple[int, ...] = ()
    cancel_frame: Optional[int] = None
    animation_name: str = "animation"
    fps: float = 12.0
    loop: bool = False

    def validate(self) -> "CombatTimeline":
        if self.frame_count <= 0:
            raise ValueError("frame_count 必須大於 0。")
        if not 0 <= self.startup_end < self.active_end <= self.frame_count:
            raise ValueError("Startup / Active / Recovery 邊界無效。")
        if self.fps <= 0:
            raise ValueError("FPS 必須大於 0。")
        hits = tuple(sorted(set(int(value) for value in self.hit_frames)))
        for value in hits:
            if not 0 <= value < self.frame_count:
                raise ValueError(f"Hit frame {value + 1} 超出動畫範圍。")
            if not self.startup_end <= value < self.active_end:
                raise ValueError(f"Hit frame {value + 1} 必須位於 Active 區間。")
        cancel = self.cancel_frame
        if cancel is not None and not 0 <= int(cancel) < self.frame_count:
            raise ValueError("Cancel frame 超出動畫範圍。")
        name = self.animation_name.strip() or "animation"
        return replace(
            self,
            hit_frames=hits,
            cancel_frame=None if cancel is None else int(cancel),
            animation_name=name,
            fps=float(self.fps),
            loop=bool(self.loop),
        )

    def phase_for_index(self, index: int) -> Optional[str]:
        if not 0 <= index < self.frame_count:
            return None
        if index < self.startup_end:
            return "startup"
        if index < self.active_end:
            return "active"
        return "recovery"

    def phase_ranges(self) -> dict[str, dict[str, int]]:
        return {
            "startup": {"start": 0, "end_exclusive": self.startup_end},
            "active": {"start": self.startup_end, "end_exclusive": self.active_end},
            "recovery": {"start": self.active_end, "end_exclusive": self.frame_count},
        }

    def to_dict(self) -> dict:
        value = asdict(self.validate())
        value["hit_frames"] = list(value["hit_frames"])
        return value

    @classmethod
    def from_dict(cls, payload: dict) -> "CombatTimeline":
        cancel = payload.get("cancel_frame")
        return cls(
            frame_count=int(payload.get("frame_count", 0)),
            startup_end=int(payload.get("startup_end", 0)),
            active_end=int(payload.get("active_end", 0)),
            hit_frames=tuple(int(value) for value in payload.get("hit_frames", [])),
            cancel_frame=None if cancel is None else int(cancel),
            animation_name=str(payload.get("animation_name", "animation")),
            fps=float(payload.get("fps", 12.0)),
            loop=bool(payload.get("loop", False)),
        ).validate()


def _analysis_gray(image: QImage, size: int = 96) -> np.ndarray:
    pixels = qimage_to_array(image)
    rgb = pixels[:, :, :3]
    alpha = pixels[:, :, 3].astype(np.float32) / 255.0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    if np.count_nonzero(alpha < 0.98) > alpha.size * 0.02:
        gray *= alpha
    height, width = gray.shape
    if max(height, width) > size:
        scale = size / float(max(height, width))
        gray = cv2.resize(
            gray,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return gray


def motion_step_scores(images: Sequence[QImage]) -> np.ndarray:
    """Return one robust motion score for each transition ending at frame i+1."""
    if len(images) < 2:
        return np.empty(0, dtype=np.float32)
    samples = [_analysis_gray(image) for image in images]
    scores: list[float] = []
    for previous, current in zip(samples, samples[1:]):
        if previous.shape != current.shape:
            current = cv2.resize(current, (previous.shape[1], previous.shape[0]), interpolation=cv2.INTER_AREA)
        delta = np.abs(current - previous).reshape(-1)
        if not delta.size:
            scores.append(0.0)
            continue
        # The high percentile makes a moving character matter even on a mostly static background.
        scores.append(float(np.percentile(delta, 92)))
    values = np.asarray(scores, dtype=np.float32)
    if values.size >= 3:
        values = np.convolve(values, np.asarray([0.2, 0.6, 0.2], dtype=np.float32), mode="same")
    return values


def suggest_combat_timeline(
    images: Sequence[QImage],
    fps: float = 12.0,
    animation_name: str = "animation",
) -> CombatTimeline:
    """Suggest Startup/Active/Recovery boundaries without mutating frames."""
    frame_count = len(images)
    if frame_count <= 0:
        raise ValueError("沒有可分析的 frame。")
    if frame_count == 1:
        return CombatTimeline(
            frame_count=1,
            startup_end=0,
            active_end=1,
            hit_frames=(0,),
            cancel_frame=None,
            animation_name=animation_name,
            fps=fps,
            loop=False,
        ).validate()

    scores = motion_step_scores(images)
    if not scores.size or float(scores.max(initial=0.0)) <= 1e-7:
        active_center = frame_count // 2
    else:
        # scores[i] is the transition from frame i to frame i+1.
        active_center = int(np.argmax(scores)) + 1

    if frame_count >= 5:
        active_start = max(1, active_center - 1)
        active_end = min(frame_count - 1, active_center + 2)
    elif frame_count >= 3:
        active_start = max(1, active_center)
        active_start = min(active_start, frame_count - 2)
        active_end = min(frame_count, active_start + 1)
    else:
        active_start = 0
        active_end = frame_count

    if active_end <= active_start:
        active_end = min(frame_count, active_start + 1)
    hit = min(max(active_center, active_start), active_end - 1)
    cancel = active_end if active_end < frame_count else None
    return CombatTimeline(
        frame_count=frame_count,
        startup_end=active_start,
        active_end=active_end,
        hit_frames=(hit,),
        cancel_frame=cancel,
        animation_name=animation_name,
        fps=fps,
        loop=False,
    ).validate()


def build_animation_manifest(
    timeline: CombatTimeline,
    extraction_indices: Sequence[int],
    source_indices: Sequence[int],
    timestamps: Sequence[float],
    motion_analysis: Optional[dict] = None,
) -> dict:
    timeline = timeline.validate()
    frame_count = timeline.frame_count
    if not (len(extraction_indices) == len(source_indices) == len(timestamps) == frame_count):
        raise ValueError("動畫 metadata 的 frame 對應數量不一致。")

    frames = []
    for output_index, (extraction_index, source_index, timestamp) in enumerate(
        zip(extraction_indices, source_indices, timestamps)
    ):
        frames.append(
            {
                "index": output_index,
                "extraction_index": int(extraction_index),
                "source_index": int(source_index),
                "timestamp": float(timestamp),
                "phase": timeline.phase_for_index(output_index),
                "hit": output_index in timeline.hit_frames,
                "cancel": timeline.cancel_frame == output_index,
            }
        )

    duration = frame_count / timeline.fps
    manifest = {
        "schema": "SpriteMakerPySide.animation",
        "schema_version": 1,
        "app_version": "4.0.1",
        "index_base": 0,
        "animation": {
            "name": timeline.animation_name,
            "fps": timeline.fps,
            "loop": timeline.loop,
            "frame_count": frame_count,
            "duration_seconds": duration,
        },
        "phases": timeline.phase_ranges(),
        "hit_frames": list(timeline.hit_frames),
        "cancel_frame": timeline.cancel_frame,
        "frames": frames,
    }
    if motion_analysis is not None:
        manifest["motion_analysis"] = motion_analysis
    return manifest
