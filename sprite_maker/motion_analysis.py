from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional, Sequence

import cv2
import numpy as np
from PySide6.QtGui import QImage

from .image_ops import qimage_to_array


@dataclass(frozen=True)
class MotionRange:
    start: int
    end: int
    confidence: float
    score: float
    period: Optional[int] = None

    def clamped(self, frame_count: int) -> "MotionRange":
        if frame_count <= 0:
            return MotionRange(0, 0, self.confidence, self.score, self.period)
        start = max(0, min(int(self.start), frame_count - 1))
        end = max(start, min(int(self.end), frame_count - 1))
        return MotionRange(start, end, self.confidence, self.score, self.period)


@dataclass(frozen=True)
class MotionAnalysisResult:
    mode: str
    recommended: Optional[MotionRange]
    loop_candidates: tuple[MotionRange, ...]
    one_shot: Optional[MotionRange]
    jolt_indices: tuple[int, ...]
    drift_x_per_frame: float
    drift_y_per_frame: float
    confidence: float
    frame_count: int

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "recommended": asdict(self.recommended) if self.recommended else None,
            "loop_candidates": [asdict(item) for item in self.loop_candidates],
            "one_shot": asdict(self.one_shot) if self.one_shot else None,
            "jolt_indices": list(self.jolt_indices),
            "drift_x_per_frame": self.drift_x_per_frame,
            "drift_y_per_frame": self.drift_y_per_frame,
            "confidence": self.confidence,
            "frame_count": self.frame_count,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "MotionAnalysisResult":
        def parse_range(value) -> Optional[MotionRange]:
            if not isinstance(value, dict):
                return None
            return MotionRange(
                start=int(value.get("start", 0)),
                end=int(value.get("end", 0)),
                confidence=float(value.get("confidence", 0.0)),
                score=float(value.get("score", 0.0)),
                period=(None if value.get("period") is None else int(value["period"])),
            )

        loop_candidates = tuple(
            item for item in (parse_range(value) for value in payload.get("loop_candidates", [])) if item is not None
        )
        return cls(
            mode=str(payload.get("mode", "auto")),
            recommended=parse_range(payload.get("recommended")),
            loop_candidates=loop_candidates,
            one_shot=parse_range(payload.get("one_shot")),
            jolt_indices=tuple(int(value) for value in payload.get("jolt_indices", [])),
            drift_x_per_frame=float(payload.get("drift_x_per_frame", 0.0)),
            drift_y_per_frame=float(payload.get("drift_y_per_frame", 0.0)),
            confidence=float(payload.get("confidence", 0.0)),
            frame_count=int(payload.get("frame_count", 0)),
        )


def _border_pixels(rgb: np.ndarray) -> np.ndarray:
    if rgb.shape[0] < 2 or rgb.shape[1] < 2:
        return rgb.reshape(-1, 3)
    return np.concatenate((rgb[0], rgb[-1], rgb[1:-1, 0], rgb[1:-1, -1]), axis=0)


def _foreground_mask(pixels: np.ndarray) -> np.ndarray:
    alpha = pixels[:, :, 3].astype(np.uint8)
    if np.count_nonzero(alpha < 250) > alpha.size * 0.02:
        return alpha >= 24

    rgb = pixels[:, :, :3].astype(np.float32)
    border = _border_pixels(rgb)
    background = np.median(border, axis=0)
    border_distance = np.sqrt(np.sum((border - background) ** 2, axis=1))
    noise = float(np.percentile(border_distance, 90)) if border_distance.size else 0.0
    threshold = max(14.0, min(70.0, noise * 2.4 + 8.0))
    distance = np.sqrt(np.sum((rgb - background) ** 2, axis=2))
    mask = distance >= threshold

    labels_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if labels_count <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(areas.max(initial=0))
    minimum = max(6, int(largest * 0.015))
    valid_labels = np.flatnonzero(stats[:, cv2.CC_STAT_AREA] >= minimum)
    valid_labels = valid_labels[valid_labels != 0]
    return np.isin(labels, valid_labels)


def _frame_feature(image: QImage, side: int = 48) -> tuple[np.ndarray, tuple[float, float]]:
    pixels = qimage_to_array(image)
    if pixels.size == 0:
        return np.zeros(side * side * 2, dtype=np.float32), (0.0, 0.0)

    mask = _foreground_mask(pixels)
    ys, xs = np.nonzero(mask)
    if len(xs):
        centroid = (float(xs.mean()), float(ys.mean()))
    else:
        centroid = (pixels.shape[1] / 2.0, pixels.shape[0] / 2.0)

    rgb = pixels[:, :, :3].astype(np.float32) / 255.0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    masked_gray = gray * mask.astype(np.float32)
    mask_small = cv2.resize(mask.astype(np.float32), (side, side), interpolation=cv2.INTER_AREA)
    gray_small = cv2.resize(masked_gray, (side, side), interpolation=cv2.INTER_AREA)

    feature = np.concatenate((mask_small.reshape(-1) * 0.72, gray_small.reshape(-1) * 0.28)).astype(np.float32)
    mean = float(feature.mean())
    std = float(feature.std())
    if std > 1e-6:
        feature = (feature - mean) / std
    else:
        feature = feature - mean
    norm = float(np.linalg.norm(feature))
    if norm > 1e-6:
        feature /= norm
    return feature, centroid


def _feature_matrix(images: Sequence[QImage]) -> tuple[np.ndarray, np.ndarray]:
    features = []
    centroids = []
    for image in images:
        feature, centroid = _frame_feature(image)
        features.append(feature)
        centroids.append(centroid)
    if not features:
        return np.empty((0, 0), dtype=np.float32), np.empty((0, 2), dtype=np.float32)
    return np.stack(features), np.asarray(centroids, dtype=np.float32)


def _distance_matrix(features: np.ndarray) -> np.ndarray:
    if features.size == 0:
        return np.empty((0, 0), dtype=np.float32)
    similarity = np.clip(features @ features.T, -1.0, 1.0)
    return np.sqrt(np.maximum(0.0, 2.0 - 2.0 * similarity)).astype(np.float32)


def _period_profile(distance: np.ndarray, min_period: int, max_period: int) -> list[tuple[int, float]]:
    frame_count = distance.shape[0]
    output: list[tuple[int, float]] = []
    for period in range(min_period, max_period + 1):
        count = frame_count - period
        if count <= 1:
            continue
        values = distance[np.arange(count), np.arange(period, frame_count)]
        output.append((period, float(np.mean(values))))
    return output


def _cycle_for_period(distance: np.ndarray, period: int) -> Optional[MotionRange]:
    frame_count = distance.shape[0]
    if period < 2 or frame_count <= period:
        return None
    adjacent = np.diag(distance, k=1)
    normal_motion = max(1e-5, float(np.median(adjacent))) if adjacent.size else 1.0
    candidates = []
    for start in range(0, frame_count - period):
        end = start + period
        seam = float(distance[start, end])
        interior = distance[start, start + 1:end + 1]
        excursion = float(np.percentile(interior, 85)) if interior.size else 0.0
        activity = min(2.0, excursion / normal_motion)
        score = seam / normal_motion - min(1.0, activity) * 0.35
        candidates.append((score, seam, excursion, start, end))
    if not candidates:
        return None
    score, seam, excursion, start, end = min(candidates, key=lambda item: (item[0], item[1], item[3]))
    seam_quality = 1.0 / (1.0 + max(0.0, seam / normal_motion))
    excursion_quality = min(1.0, excursion / max(normal_motion * 2.0, 1e-5))
    confidence = float(np.clip(seam_quality * 0.72 + excursion_quality * 0.28, 0.0, 1.0))
    return MotionRange(start=start, end=end - 1, confidence=confidence, score=float(score), period=period)


def _loop_candidates(distance: np.ndarray, max_candidates: int = 3) -> tuple[MotionRange, ...]:
    frame_count = distance.shape[0]
    if frame_count < 6:
        return ()
    min_period = 2
    max_period = max(min_period, min(frame_count // 2, 180))
    profile = _period_profile(distance, min_period, max_period)
    if not profile:
        return ()

    values = np.asarray([value for _, value in profile], dtype=np.float32)
    local = []
    for index, (period, value) in enumerate(profile):
        left = values[index - 1] if index > 0 else np.inf
        right = values[index + 1] if index + 1 < len(values) else np.inf
        if value <= left and value <= right:
            local.append((period, float(value)))
    if not local:
        local = sorted(profile, key=lambda item: item[1])[: max_candidates * 3]
    else:
        local.sort(key=lambda item: item[1])

    selected_periods: list[int] = []
    profile_lookup = dict(profile)
    for period, value in local:
        doubled = period * 2
        if doubled <= max_period and profile_lookup.get(doubled, np.inf) <= value * 1.08:
            period = doubled
        if any(abs(period - existing) <= 1 for existing in selected_periods):
            continue
        selected_periods.append(period)
        if len(selected_periods) >= max_candidates * 2:
            break

    ranges = [candidate for period in selected_periods if (candidate := _cycle_for_period(distance, period)) is not None]
    ranges.sort(key=lambda item: (-item.confidence, item.score, -(item.period or 0)))
    deduped: list[MotionRange] = []
    for candidate in ranges:
        if any(candidate.period == item.period for item in deduped):
            continue
        deduped.append(candidate)
        if len(deduped) >= max_candidates:
            break
    return tuple(deduped)


def _one_shot_candidate(distance: np.ndarray) -> Optional[MotionRange]:
    frame_count = distance.shape[0]
    if frame_count < 6:
        return None
    adjacent = np.diag(distance, k=1)
    normal_motion = max(1e-5, float(np.median(adjacent))) if adjacent.size else 1.0
    min_span = max(4, frame_count // 5)
    start_limit = max(1, int(frame_count * 0.38))
    end_start = min(frame_count - 1, max(start_limit + 1, int(frame_count * 0.62)))
    best = None

    for start in range(start_limit):
        for end in range(max(start + min_span, end_start), frame_count):
            seam = float(distance[start, end])
            interior = distance[start, start + 1:end]
            if interior.size < 2:
                continue
            excursion = float(np.percentile(interior, 90))
            return_ratio = seam / max(excursion, 1e-5)
            activity = excursion / normal_motion
            span_ratio = (end - start + 1) / frame_count
            score = return_ratio - min(2.0, activity) * 0.20 + abs(span_ratio - 0.72) * 0.08
            candidate = (score, seam, excursion, start, end)
            if best is None or candidate < best:
                best = candidate

    if best is None:
        return None
    score, seam, excursion, start, end = best
    return_quality = float(np.clip(1.0 - seam / max(excursion, normal_motion, 1e-5), 0.0, 1.0))
    activity_quality = float(np.clip(excursion / max(normal_motion * 2.0, 1e-5), 0.0, 1.0))
    confidence = return_quality * 0.72 + activity_quality * 0.28
    return MotionRange(start=start, end=end, confidence=confidence, score=float(score), period=None)


def _jolt_indices(distance: np.ndarray) -> tuple[int, ...]:
    if distance.shape[0] < 3:
        return ()
    steps = np.diag(distance, k=1).astype(np.float64)
    if not steps.size:
        return ()
    median = float(np.median(steps))
    mad = float(np.median(np.abs(steps - median)))
    robust_sigma = max(1e-6, mad * 1.4826)
    threshold = max(median * 2.15, median + robust_sigma * 3.5)
    indices = np.flatnonzero(steps > threshold) + 1
    return tuple(int(index) for index in indices)


def _centroid_drift(centroids: np.ndarray) -> tuple[float, float]:
    if len(centroids) < 3:
        return 0.0, 0.0
    x = np.arange(len(centroids), dtype=np.float64)
    center_x = centroids[:, 0].astype(np.float64)
    center_y = centroids[:, 1].astype(np.float64)
    slope_x = float(np.polyfit(x, center_x, 1)[0])
    slope_y = float(np.polyfit(x, center_y, 1)[0])
    return slope_x, slope_y


def analyze_motion(images: Sequence[QImage], fps: float = 12.0, mode: str = "auto") -> MotionAnalysisResult:
    """Analyze extracted frames without mutating them."""
    mode = mode if mode in {"auto", "loop", "one_shot"} else "auto"
    frame_count = len(images)
    if frame_count == 0:
        return MotionAnalysisResult(mode, None, (), None, (), 0.0, 0.0, 0.0, 0)

    features, centroids = _feature_matrix(images)
    distance = _distance_matrix(features)
    loops = _loop_candidates(distance)
    one_shot = _one_shot_candidate(distance)
    jolts = _jolt_indices(distance)
    drift_x, drift_y = _centroid_drift(centroids)

    loop = loops[0] if loops else None
    if mode == "loop":
        recommended = loop
    elif mode == "one_shot":
        recommended = one_shot
    else:
        loop_conf = loop.confidence if loop else 0.0
        shot_conf = one_shot.confidence if one_shot else 0.0
        recommended = loop if loop_conf >= shot_conf + 0.08 else one_shot
        if recommended is None:
            recommended = loop or one_shot

    confidence = recommended.confidence if recommended else 0.0
    return MotionAnalysisResult(
        mode=mode,
        recommended=recommended,
        loop_candidates=loops,
        one_shot=one_shot,
        jolt_indices=jolts,
        drift_x_per_frame=drift_x,
        drift_y_per_frame=drift_y,
        confidence=confidence,
        frame_count=frame_count,
    )
