from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import cv2
from PySide6.QtGui import QImage

from .models import RGBA_FORMAT


@dataclass
class VideoMetadata:
    path: Path
    fps: float
    frame_count: int
    duration: float
    width: int
    height: int


@dataclass
class ExtractedVideoFrame:
    image: QImage
    timestamp: float
    source_index: int


def read_video_metadata(path: Path) -> VideoMetadata:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {path}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frame_count / fps if fps > 0 else 0.0
        return VideoMetadata(
            path=path,
            fps=fps,
            frame_count=frame_count,
            duration=duration,
            width=width,
            height=height,
        )
    finally:
        capture.release()


def build_sample_times(start: float, end: float, target_fps: float) -> List[float]:
    start = max(0.0, float(start))
    end = max(start, float(end))
    target_fps = max(0.1, float(target_fps))
    step = 1.0 / target_fps
    times: List[float] = []
    t = start
    while t <= end + 0.0001:
        times.append(round(t, 6))
        t += step
    return times


def cv_frame_to_qimage(frame) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
    return image.copy().convertToFormat(RGBA_FORMAT)


def extract_video_frames(path: Path, start: float, end: float, target_fps: float) -> List[ExtractedVideoFrame]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {path}")

    frames: List[ExtractedVideoFrame] = []
    try:
        native_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        for index, timestamp in enumerate(build_sample_times(start, end, target_fps)):
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            source_index = round(timestamp * native_fps) if native_fps > 0 else index
            frames.append(
                ExtractedVideoFrame(
                    image=cv_frame_to_qimage(frame),
                    timestamp=timestamp,
                    source_index=source_index,
                )
            )
    finally:
        capture.release()
    return frames
