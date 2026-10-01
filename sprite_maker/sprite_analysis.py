"""Background masks and conservative regular-grid inference (no image mutation)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from .image_ops import qimage_to_array


@dataclass(frozen=True)
class BackgroundSettings:
    mode: str = "transparent"
    alpha_threshold: int = 10
    color: tuple[int, int, int] = (0, 255, 0)
    tolerance: float = 20.0


@dataclass(frozen=True)
class AxisDetection:
    count: Optional[int]
    start: Optional[int]
    end: Optional[int]
    spacing: Optional[int]
    confidence: float


@dataclass(frozen=True)
class SpriteSheetDetectionResult:
    columns: Optional[int]
    rows: Optional[int]
    grid_x: Optional[int]
    grid_y: Optional[int]
    grid_width: Optional[int]
    grid_height: Optional[int]
    horizontal_spacing: Optional[int]
    vertical_spacing: Optional[int]
    confidence: float
    warnings: tuple[str, ...]


def background_mask(image: QImage, settings: BackgroundSettings = BackgroundSettings()) -> np.ndarray:
    if image.isNull():
        raise ValueError("Sprite sheet image is empty.")
    if settings.mode not in ("transparent", "color"):
        raise ValueError("Unknown background mode.")
    if not 0 <= settings.alpha_threshold <= 255 or not 0 <= settings.tolerance <= 442:
        raise ValueError("Background threshold is out of range.")
    pixels = qimage_to_array(image)
    mask = pixels[:, :, 3] <= settings.alpha_threshold
    if settings.mode == "color":
        # Float arithmetic avoids uint8 subtraction and squared-distance overflow.
        delta = pixels[:, :, :3].astype(np.float32) - np.asarray(settings.color, dtype=np.float32)
        mask |= np.sum(delta * delta, axis=2) <= settings.tolerance ** 2
    return mask


def _runs(values: np.ndarray) -> np.ndarray:
    edges = np.flatnonzero(np.diff(np.r_[False, values, False].astype(np.int8)))
    return edges.reshape(-1, 2)


def detect_axis_layout(background_ratio: np.ndarray, separator_ratio: float = 0.995) -> AxisDetection:
    """Fit regularly spaced groups of occupied runs, not individual blank lines.

    Grouping permits holes inside a sprite. Competing regular groupings reduce
    confidence because projections alone cannot resolve repeated internal detail.
    Bounds are the observed foreground envelope, not inferred invisible padding.
    """
    ratio = np.asarray(background_ratio, dtype=float)
    unknown = AxisDetection(None, None, None, None, 0.0)
    if ratio.ndim != 1 or ratio.size == 0:
        return unknown
    occupied = _runs(ratio < separator_ratio)
    if not len(occupied):
        return unknown
    start, end = int(occupied[0, 0]), int(occupied[-1, 1])
    if len(occupied) == 1:
        # With no separator there is no evidence for a multi-cell grid.
        return unknown
    candidates = []
    gap_starts, gap_ends = occupied[:-1, 1], occupied[1:, 0]
    gap_centers = (gap_starts + gap_ends) / 2
    gap_widths = gap_ends - gap_starts
    values, frequencies = np.unique(gap_widths, return_counts=True)
    # Bound search cost on noisy inputs. Common gap widths plus the median
    # provide separation hypotheses; internal holes need not occur equally often.
    spacings = set(int(v) for v in values[np.argsort(frequencies)[-32:]])
    spacings.add(int(np.floor(np.median(gap_widths) + 0.5)))
    for count in range(2, min(128, len(occupied)) + 1):
        best = None
        for spacing in sorted(spacings):
            usable = end - start - spacing * (count - 1)
            if usable < count:
                continue
            cell_width = usable / count
            predicted = start + np.arange(1, count) * (cell_width + spacing) - spacing / 2
            nearest = np.searchsorted(gap_centers, predicted).clip(0, len(gap_centers) - 1)
            previous = (nearest - 1).clip(0)
            nearest = np.where(abs(gap_centers[previous] - predicted) < abs(gap_centers[nearest] - predicted), previous, nearest)
            if len(np.unique(nearest)) != count - 1:
                continue
            starts = np.r_[start, gap_ends[nearest]]
            ends = np.r_[gap_starts[nearest], end]
            widths = ends - starts
            gaps = gap_widths[nearest]
            inferred_spacing = int(np.floor(np.median(gaps) + 0.5))
            if spacing != inferred_spacing:
                continue
            periods = np.diff(starts)
            mean_width = float(np.mean(widths))
            width_error = float(np.max(np.abs(widths - mean_width))) / max(1.0, mean_width)
            gap_error = float(np.max(np.abs(gaps - spacing))) / max(2.0, float(spacing))
            period_error = float(np.max(np.abs(periods - np.mean(periods)))) / max(1.0, float(np.mean(periods)))
            position_error = float(np.max(np.abs(gap_centers[nearest] - predicted)))
            if (width_error > 0.18 or gap_error > 0.4 or period_error > 0.12
                    or position_error > max(1.5, mean_width * 0.06)):
                continue
            grouping_penalty = 0.15 * np.log2(len(occupied) / count)
            score = max(0.0, 1.0 - width_error - gap_error * 0.3 - period_error - grouping_penalty)
            if best is None or score > best[0]:
                best = (score, count, spacing)
        if best is not None:
            candidates.append(best)
    if not candidates:
        return unknown
    candidates.sort(reverse=True)
    score, count, spacing = candidates[0]
    if len(candidates) > 1 and candidates[1][0] >= score - 0.08:
        score = min(score, 0.45)
    return AxisDetection(count, start, end, spacing, score)


def detect_spritesheet(image: QImage, settings: BackgroundSettings = BackgroundSettings()) -> SpriteSheetDetectionResult:
    mask = background_mask(image, settings)
    if mask.all():
        return SpriteSheetDetectionResult(*([None] * 8), 0.0, ("No foreground detected.",))
    x = detect_axis_layout(mask.mean(axis=0))
    y = detect_axis_layout(mask.mean(axis=1))
    warnings = []
    if x.count is not None and y.count is not None and x.count * y.count > 4096:
        return SpriteSheetDetectionResult(*([None] * 8), 0.0, ("Detected grid exceeds 4096 cells.",))
    if x.count is None or y.count is None:
        warnings.append("Unable to determine a regular sprite grid.")
        if x.count is None:
            warnings.append("Columns unknown; horizontal settings were preserved.")
        if y.count is None:
            warnings.append("Rows unknown; vertical settings were preserved.")
    confidence = min(x.confidence, y.confidence)
    if confidence < 0.5:
        warnings.append("自動辨識結果可信度較低，請手動調整網格。")
    warnings.append("Grid edges follow visible content; verify any padding inside frames.")
    return SpriteSheetDetectionResult(
        x.count, y.count, x.start, y.start,
        None if x.start is None else x.end - x.start,
        None if y.start is None else y.end - y.start,
        x.spacing, y.spacing, confidence, tuple(warnings),
    )


def detect_empty_frames(mask: np.ndarray, cell_rects: Sequence[QRect], empty_threshold: float = 0.001) -> list[bool]:
    """Measure source cells, excluding synthetic output padding; retain every index."""
    if not 0 <= empty_threshold <= 1:
        raise ValueError("Empty threshold must be between 0 and 1.")
    bounds = QRect(0, 0, mask.shape[1], mask.shape[0])
    empty = []
    for rect in cell_rects:
        cell_pixels = rect.width() * rect.height()
        rect = rect.intersected(bounds)
        region = mask[rect.y():rect.y() + rect.height(), rect.x():rect.x() + rect.width()]
        foreground_count = region.size - np.count_nonzero(region)
        empty.append(bool(region.size == 0 or foreground_count <= cell_pixels * empty_threshold))
    return empty
