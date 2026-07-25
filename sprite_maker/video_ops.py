from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np
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
    target_timestamp: float = 0.0
    time_offset: float = 0.0
    sharpness: float = 0.0
    clarity_percentile: float = 100.0
    is_blurry: bool = False
    candidate_peak_sharpness: float = 0.0
    extraction_mode: str = "exact"


@dataclass
class _DecodedCandidate:
    frame: np.ndarray
    timestamp: float
    source_index: int
    sharpness: float
    histogram: np.ndarray


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


def cv_frame_to_qimage(frame: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
    return image.copy().convertToFormat(RGBA_FORMAT)


def measure_frame_sharpness(frame: np.ndarray, analysis_width: int = 640) -> float:
    sample = frame
    if frame.shape[1] > analysis_width:
        scale = analysis_width / float(frame.shape[1])
        sample = cv2.resize(
            frame,
            (analysis_width, max(1, round(frame.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    return float(laplacian.var())


def _frame_histogram(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    scale = min(1.0, 192.0 / max(1, width))
    sample = frame
    if scale < 1.0:
        sample = cv2.resize(
            frame,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
    cv2.normalize(histogram, histogram)
    return histogram


def _candidate_window(native_fps: float, target_fps: float, mode: str) -> float:
    native_period = 1.0 / native_fps if native_fps > 0 else 1.0 / max(1.0, target_fps)
    target_period = 1.0 / max(0.1, target_fps)
    if mode == "exact":
        return max(native_period * 0.55, 0.001)
    if mode == "sharp":
        return max(native_period, min(native_period * 4.0, target_period * 0.9))
    return max(native_period, min(native_period * 2.0, target_period * 0.45))


def _normalized_values(values: List[float]) -> List[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high - low <= 1e-6:
        return [0.5 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _select_candidate(
    candidates: List[_DecodedCandidate],
    target_timestamp: float,
    mode: str,
    window: float,
    last_source_index: int,
    expected_source_step: float,
) -> Optional[_DecodedCandidate]:
    available = [candidate for candidate in candidates if candidate.source_index > last_source_index]
    if not available:
        return None
    if mode == "exact":
        return min(available, key=lambda candidate: (abs(candidate.timestamp - target_timestamp), candidate.source_index))

    anchor = min(available, key=lambda candidate: abs(candidate.timestamp - target_timestamp))
    sharpness_values = _normalized_values([np.log1p(candidate.sharpness) for candidate in available])
    best_candidate = available[0]
    best_score = float("-inf")
    for candidate, clarity_score in zip(available, sharpness_values):
        time_score = max(0.0, 1.0 - abs(candidate.timestamp - target_timestamp) / max(window, 1e-6))
        if last_source_index < 0:
            spacing_score = time_score
        else:
            actual_step = candidate.source_index - last_source_index
            spacing_score = max(
                0.0,
                1.0 - abs(actual_step - expected_source_step) / max(1.0, expected_source_step),
            )
        scene_distance = float(
            cv2.compareHist(anchor.histogram, candidate.histogram, cv2.HISTCMP_BHATTACHARYYA)
        )
        if mode == "sharp":
            score = clarity_score * 0.76 + time_score * 0.12 + spacing_score * 0.12
        else:
            score = clarity_score * 0.56 + time_score * 0.30 + spacing_score * 0.14
        score -= min(1.0, scene_distance) * 0.45
        tie_break = -abs(candidate.timestamp - target_timestamp) * 1e-4
        if score + tie_break > best_score:
            best_score = score + tie_break
            best_candidate = candidate
    return best_candidate


def _classify_extracted_frames(frames: List[ExtractedVideoFrame]) -> None:
    if not frames:
        return
    values = np.asarray([frame.sharpness for frame in frames], dtype=np.float64)
    order = np.argsort(values, kind="stable")
    percentiles = np.empty(len(frames), dtype=np.float64)
    if len(frames) == 1:
        percentiles[0] = 100.0
    else:
        percentiles[order] = np.linspace(0.0, 100.0, len(frames))

    for index, frame in enumerate(frames):
        local_values = values[max(0, index - 2) : min(len(frames), index + 3)]
        local_reference = float(np.median(local_values)) if local_values.size else frame.sharpness
        threshold = max(20.0, local_reference * 0.42)
        frame.clarity_percentile = float(percentiles[index])
        frame.is_blurry = frame.sharpness < threshold


def extract_video_frames(
    path: Path,
    start: float,
    end: float,
    target_fps: float,
    mode: str = "balanced",
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[ExtractedVideoFrame]:
    mode = mode if mode in {"exact", "balanced", "sharp"} else "balanced"
    target_times = build_sample_times(start, end, target_fps)
    if not target_times:
        return []

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {path}")

    frames: List[ExtractedVideoFrame] = []
    try:
        native_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        native_period = 1.0 / native_fps if native_fps > 0 else 1.0 / max(1.0, target_fps)
        window = _candidate_window(native_fps, target_fps, mode)
        warmup = max(native_period * 2.0, window)
        decode_start = max(0.0, float(start) - warmup)
        decode_end = float(end) + window + native_period
        capture.set(cv2.CAP_PROP_POS_MSEC, decode_start * 1000.0)

        buffer: List[_DecodedCandidate] = []
        target_index = 0
        last_source_index = -1
        last_decoded_timestamp = -1.0
        last_decoded_source_index = -1
        decoded_count = 0
        expected_source_step = max(1.0, native_fps / max(0.1, target_fps)) if native_fps > 0 else 1.0

        def finalize_ready_targets(force: bool = False) -> None:
            nonlocal target_index, last_source_index, buffer
            while target_index < len(target_times):
                target = target_times[target_index]
                if not force and last_decoded_timestamp < target + window:
                    break
                candidates = [
                    candidate
                    for candidate in buffer
                    if abs(candidate.timestamp - target) <= window + native_period * 0.55
                ]
                if not candidates:
                    later_candidates = [
                        candidate
                        for candidate in buffer
                        if candidate.source_index > last_source_index
                    ]
                    if later_candidates:
                        candidates = [
                            min(
                                later_candidates,
                                key=lambda candidate: abs(candidate.timestamp - target),
                            )
                        ]
                selected = _select_candidate(
                    candidates,
                    target,
                    mode,
                    window + native_period * 0.55,
                    last_source_index,
                    expected_source_step,
                )
                if selected is not None:
                    peak_sharpness = max(candidate.sharpness for candidate in candidates)
                    frames.append(
                        ExtractedVideoFrame(
                            image=cv_frame_to_qimage(selected.frame),
                            timestamp=selected.timestamp,
                            source_index=selected.source_index,
                            target_timestamp=target,
                            time_offset=selected.timestamp - target,
                            sharpness=selected.sharpness,
                            candidate_peak_sharpness=peak_sharpness,
                            extraction_mode=mode,
                        )
                    )
                    last_source_index = selected.source_index
                target_index += 1
                if progress_callback is not None:
                    progress_callback(target_index, len(target_times))
                if target_index < len(target_times):
                    oldest_needed = target_times[target_index] - window - native_period
                    buffer = [
                        candidate
                        for candidate in buffer
                        if candidate.timestamp >= oldest_needed and candidate.source_index > last_source_index
                    ]

        while target_index < len(target_times):
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            source_position = float(capture.get(cv2.CAP_PROP_POS_FRAMES) or 0.0)
            estimated_source_index = (
                max(0, round(decode_start * native_fps) + decoded_count)
                if native_fps > 0
                else decoded_count
            )
            source_index = round(source_position) - 1 if source_position >= 1.0 else estimated_source_index
            if source_index <= last_decoded_source_index:
                source_index = last_decoded_source_index + 1
            reported_timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
            fallback_timestamp = source_index / native_fps if native_fps > 0 else last_decoded_timestamp + native_period
            timestamp = (
                reported_timestamp
                if reported_timestamp > 0.0 or decode_start <= 0.0
                else fallback_timestamp
            )
            if timestamp <= last_decoded_timestamp + 1e-7:
                timestamp = max(fallback_timestamp, last_decoded_timestamp + native_period)
            last_decoded_timestamp = timestamp
            last_decoded_source_index = source_index
            decoded_count += 1
            if timestamp >= decode_start - native_period:
                buffer.append(
                    _DecodedCandidate(
                        frame=frame,
                        timestamp=timestamp,
                        source_index=source_index,
                        sharpness=measure_frame_sharpness(frame),
                        histogram=_frame_histogram(frame),
                    )
                )
            finalize_ready_targets()
            if timestamp > decode_end and target_index >= len(target_times):
                break

        finalize_ready_targets(force=True)
    finally:
        capture.release()

    _classify_extracted_frames(frames)
    return frames
