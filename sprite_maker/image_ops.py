from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, Mapping, Optional, Tuple

import numpy as np
from PySide6.QtGui import QColor, QImage

from .models import RGBA_FORMAT


def qimage_to_array(image: QImage) -> np.ndarray:
    img = image.convertToFormat(RGBA_FORMAT)
    width = img.width()
    height = img.height()
    ptr = img.bits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=img.sizeInBytes())
    arr = arr.reshape((height, img.bytesPerLine()))
    return arr[:, : width * 4].reshape((height, width, 4)).copy()


def array_to_qimage(arr: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(arr.astype(np.uint8))
    height, width, _ = arr.shape
    image = QImage(arr.data, width, height, width * 4, RGBA_FORMAT)
    return image.copy()


def qcolor_to_rgba(color: QColor) -> Tuple[int, int, int, int]:
    return color.red(), color.green(), color.blue(), color.alpha()


def color_distance_mask(arr: np.ndarray, rgba: Iterable[int], tolerance: int) -> np.ndarray:
    target = np.array(tuple(rgba), dtype=np.int32)
    rgb_delta = arr[:, :, :3].astype(np.int32) - target[:3]
    rgb_dist_sq = np.sum(rgb_delta * rgb_delta, axis=2)
    alpha_dist = np.abs(arr[:, :, 3].astype(np.int32) - int(target[3]))
    return (rgb_dist_sq <= tolerance * tolerance * 3) & (alpha_dist <= tolerance)


def rgb_similarity_to_color(rgb: np.ndarray, spill_rgb: np.ndarray, tolerance: int) -> np.ndarray:
    delta = rgb.astype(np.float32) - spill_rgb.astype(np.float32)
    distance = np.sqrt(np.mean(delta * delta, axis=-1))
    if tolerance <= 0:
        return (distance <= 0.0).astype(np.float32)
    return np.clip(1.0 - (distance / float(tolerance)), 0.0, 1.0)


def channel_bias_similarity(rgb: np.ndarray, spill_rgb: np.ndarray) -> np.ndarray:
    spill = spill_rgb.astype(np.float32)
    dominant = int(np.argmax(spill))
    others = [index for index in range(3) if index != dominant]
    if spill[dominant] < max(spill[others]) + 20:
        return np.zeros(rgb.shape[:2], dtype=np.float32)

    rgb_f = rgb.astype(np.float32)
    dominant_value = rgb_f[:, :, dominant]
    bias = (dominant_value > rgb_f[:, :, others[0]] + 10) & (dominant_value > rgb_f[:, :, others[1]] + 10)
    dominance = np.minimum(dominant_value - rgb_f[:, :, others[0]], dominant_value - rgb_f[:, :, others[1]])
    return np.where(bias, np.clip(dominance / 120.0, 0.3, 0.6), 0.0).astype(np.float32)


def similarity_with_channel_bias(
    rgb: np.ndarray,
    spill_rgb: np.ndarray,
    tolerance: int,
    candidate_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    similarity = rgb_similarity_to_color(rgb, spill_rgb, tolerance)
    bias = channel_bias_similarity(rgb, spill_rgb)
    if candidate_mask is not None:
        bias = np.where(candidate_mask, bias, 0.0)
    return np.maximum(similarity, bias)


def shift_mask(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    shifted = np.zeros_like(mask, dtype=bool)
    src_y0 = max(0, -dy)
    src_y1 = mask.shape[0] - max(0, dy)
    src_x0 = max(0, -dx)
    src_x1 = mask.shape[1] - max(0, dx)
    dst_y0 = max(0, dy)
    dst_y1 = mask.shape[0] - max(0, -dy)
    dst_x0 = max(0, dx)
    dst_x1 = mask.shape[1] - max(0, -dx)
    if src_y0 < src_y1 and src_x0 < src_x1:
        shifted[dst_y0:dst_y1, dst_x0:dst_x1] = mask[src_y0:src_y1, src_x0:src_x1]
    return shifted


def dilate_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return mask.copy()
    output = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            output |= shift_mask(mask, dx, dy)
    return output


def erode_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return mask.copy()
    output = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            output &= shift_mask(mask, dx, dy)
    return output


def box_blur_channel(channel: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return channel.copy()
    height, width = channel.shape
    padded = np.pad(channel.astype(np.float32), radius, mode="edge")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    size = radius * 2 + 1
    total = (
        integral[size : size + height, size : size + width]
        - integral[:height, size : size + width]
        - integral[size : size + height, :width]
        + integral[:height, :width]
    )
    return total / float(size * size)


def findNearbyCleanInnerColor(
    x: int,
    y: int,
    originalImageData: np.ndarray,
    mask: np.ndarray,
    contaminatedMask: np.ndarray,
    innerEdgeBand: np.ndarray,
    outerPaddingBand: np.ndarray,
    selectedColor: np.ndarray,
    colorTolerance: int,
    radius: int,
    alphaThreshold: int,
    edgeFactor: Optional[np.ndarray] = None,
) -> Optional[np.ndarray]:
    height, width, _ = originalImageData.shape
    y0 = max(0, y - radius)
    y1 = min(height, y + radius + 1)
    x0 = max(0, x - radius)
    x1 = min(width, x + radius + 1)

    local_rgb = originalImageData[y0:y1, x0:x1, :3]
    local_alpha = originalImageData[y0:y1, x0:x1, 3].astype(np.int16)
    local_similarity = similarity_with_channel_bias(local_rgb, selectedColor, colorTolerance)
    local_mask = (
        mask[y0:y1, x0:x1]
        & ~contaminatedMask[y0:y1, x0:x1]
        & ~outerPaddingBand[y0:y1, x0:x1]
        & (local_alpha > alphaThreshold)
        & (local_similarity <= 0.0)
    )
    if not np.any(local_mask):
        local_mask = (
            mask[y0:y1, x0:x1]
            & ~contaminatedMask[y0:y1, x0:x1]
            & ~outerPaddingBand[y0:y1, x0:x1]
            & (local_alpha > alphaThreshold)
            & (local_similarity < 0.35)
        )
    if y0 <= y < y1 and x0 <= x < x1:
        local_mask[y - y0, x - x0] = False
    if not np.any(local_mask):
        return None

    yy, xx = np.nonzero(local_mask)
    global_y = yy + y0
    global_x = xx + x0
    distance = np.sqrt((global_y - y) * (global_y - y) + (global_x - x) * (global_x - x)).astype(np.float32)
    weights = 1.0 / (distance + 1.0)
    alpha_weight = originalImageData[global_y, global_x, 3].astype(np.float32) / 255.0
    inner_weight = np.where(innerEdgeBand[global_y, global_x], 0.5, 1.5).astype(np.float32)
    weights *= alpha_weight * inner_weight
    if edgeFactor is not None:
        inside_bonus = 1.0 + (1.0 - np.clip(edgeFactor[global_y, global_x], 0.0, 1.0))
        weights *= inside_bonus

    colors = originalImageData[global_y, global_x, :3].astype(np.float32)
    total_weight = float(np.sum(weights))
    if total_weight <= 0.0:
        return None
    return np.sum(colors * weights[:, None], axis=0) / total_weight


def fallback_despill_color(original: np.ndarray, spill_rgb: np.ndarray, weight: float) -> np.ndarray:
    gray = np.full(3, float(np.mean(original)), dtype=np.float32)
    opposite = np.clip(original.astype(np.float32) + (original.astype(np.float32) - spill_rgb.astype(np.float32)) * 0.25, 0, 255)
    fallback = (gray + opposite) * 0.5
    return original.astype(np.float32) * (1.0 - weight) + fallback * weight


def rgba_sums(arr: np.ndarray) -> Dict[str, int]:
    return {
        "RGBSum": int(np.sum(arr[:, :, :3].astype(np.uint64))),
        "AlphaSum": int(np.sum(arr[:, :, 3].astype(np.uint64))),
    }


def option_selection_mask(value: object, height: int, width: int) -> Tuple[np.ndarray, bool]:
    """Convert an optional editor selection mask into an image-sized boolean mask."""
    if value is None:
        return np.ones((height, width), dtype=bool), False

    if isinstance(value, QImage):
        source = qimage_to_array(value)[:, :, 3] > 0
    elif isinstance(value, np.ndarray):
        source = value.astype(bool)
        if source.ndim == 3:
            source = source[:, :, 0]
    else:
        return np.ones((height, width), dtype=bool), False

    selection = np.zeros((height, width), dtype=bool)
    copy_height = min(height, source.shape[0])
    copy_width = min(width, source.shape[1])
    if copy_height > 0 and copy_width > 0:
        selection[:copy_height, :copy_width] = source[:copy_height, :copy_width]
    return selection, True


def debug_overlay_image(width: int, height: int, masks: Mapping[str, np.ndarray], mode: str) -> QImage:
    overlay = np.zeros((height, width, 4), dtype=np.uint8)

    def paint(mask_name: str, color: Tuple[int, int, int, int]) -> None:
        mask = masks.get(mask_name)
        if mask is not None and np.any(mask):
            overlay[mask] = np.array(color, dtype=np.uint8)

    if mode == "innerEdgeBand":
        paint("innerEdgeBand", (0, 96, 255, 120))
    elif mode == "outerPaddingBand":
        paint("outerPaddingBand", (0, 255, 80, 120))
    elif mode == "semiTransparentBand":
        paint("semiTransparentBand", (255, 220, 0, 140))
    elif mode == "contaminatedMask":
        paint("contaminatedMask", (255, 0, 0, 160))
    elif mode == "lookupFallback":
        paint("lookupFallback", (255, 0, 255, 190))
    elif mode == "actualChangedPixels":
        paint("actualChangedPixels", (0, 220, 255, 170))
    else:
        paint("innerEdgeBand", (0, 96, 255, 95))
        paint("outerPaddingBand", (0, 255, 80, 90))
        paint("semiTransparentBand", (255, 220, 0, 110))
        paint("contaminatedMask", (255, 0, 0, 165))
        paint("lookupFallback", (255, 0, 255, 210))
        paint("actualChangedPixels", (0, 220, 255, 190))
    return array_to_qimage(overlay)


def applyColorSpillCleanupToImageData(imageData: QImage, options: Mapping[str, object]):
    spill_color = options.get("spillColor", (0, 255, 0, 255))
    if isinstance(spill_color, QColor):
        spill_rgba = qcolor_to_rgba(spill_color)
    else:
        spill_rgba = tuple(spill_color)  # type: ignore[arg-type]
    spill_rgb = np.array(spill_rgba[:3], dtype=np.float32)

    color_tolerance = int(options.get("colorTolerance", 15))
    despill_strength = float(options.get("despillStrength", 0.8))
    edge_width = max(1, int(options.get("edgeWidth", 3)))
    erode_pixels = max(0, int(options.get("erodePixels", 0)))
    feather = max(0, int(options.get("feather", 0)))
    enable_color_bleeding = bool(options.get("enableColorBleeding", True))
    alpha_threshold = int(options.get("alphaThreshold", 8))
    semi_transparent_threshold = int(options.get("semiTransparentThreshold", 128))
    process_transparent_padding = bool(options.get("processTransparentPadding", True))
    return_debug_data = bool(options.get("returnDebugData", False))
    debug_overlay_mode = str(options.get("debugOverlayMode", "allDebugMasks"))
    test_paint_contaminated = bool(options.get("testPaintContaminated", False))
    detect_only = bool(options.get("detectOnly", False))

    original_arr = qimage_to_array(imageData)
    before_sums = rgba_sums(original_arr)
    if original_arr.size == 0:
        result = imageData.copy()
        if return_debug_data:
            return result, {"stats": {}, "overlay": QImage()}
        return result

    height, width, _ = original_arr.shape
    selection_mask, selection_applied = option_selection_mask(options.get("selectionMask"), height, width)
    mask = original_arr[:, :, 3].astype(np.int16) > alpha_threshold
    if not np.any(mask):
        result = imageData.copy()
        if return_debug_data:
            return result, {"stats": {"maskPixelCount": 0}, "overlay": QImage()}
        return result

    eroded_for_edge = erode_mask(mask, edge_width)
    inner_edge_band = mask & ~eroded_for_edge
    dilated = dilate_mask(mask, edge_width)
    outer_padding_band = dilated & ~mask
    alpha = original_arr[:, :, 3].astype(np.int16)
    semi_transparent_band = (alpha > 0) & (alpha < semi_transparent_threshold)
    low_alpha_edge_band = (alpha > 0) & (alpha <= 64)

    candidate_mask = (inner_edge_band | semi_transparent_band | low_alpha_edge_band | outer_padding_band) & selection_mask
    if not np.any(candidate_mask):
        result = imageData.copy()
        if return_debug_data:
            return result, {"stats": {"candidatePixelCount": 0}, "overlay": QImage()}
        return result

    rgb = original_arr[:, :, :3].astype(np.float32)
    similarity = similarity_with_channel_bias(rgb, spill_rgb, color_tolerance, candidate_mask)

    edge_factor = np.zeros(mask.shape, dtype=np.float32)
    current = mask.copy()
    for distance in range(edge_width):
        eroded = erode_mask(current, 1)
        ring = current & ~eroded
        edge_factor[ring] = max(0.0, (edge_width - distance) / float(edge_width))
        current = eroded
        if not np.any(current):
            break
    edge_factor = np.where(semi_transparent_band | low_alpha_edge_band, np.maximum(edge_factor, 1.0), edge_factor)
    edge_factor = np.where(outer_padding_band, np.maximum(edge_factor, 1.0), edge_factor)

    alpha_norm = alpha.astype(np.float32) / 255.0
    alpha_factor = np.where(
        semi_transparent_band | low_alpha_edge_band,
        1.0,
        np.clip(1.05 - alpha_norm * 0.35, 0.70, 1.0),
    )
    spill_weight = np.clip(similarity * edge_factor * alpha_factor * despill_strength, 0.0, 1.0)
    contaminated_mask = (
        candidate_mask
        & (alpha > 0)
        & (similarity > 0.0)
        & (spill_weight > 0.0)
    )
    boosted_weight = edge_factor * despill_strength * np.clip(similarity + 0.25, 0.0, 1.0) * 0.85
    spill_weight = np.where(contaminated_mask, np.maximum(spill_weight, boosted_weight), spill_weight)
    if feather > 0:
        spill_weight = np.where(contaminated_mask, box_blur_channel(spill_weight, feather), 0.0)
    search_radius = max(edge_width * 2 + 4, 12)
    search_radius_2 = max(edge_width * 4 + 8, 24)

    repaired = original_arr.astype(np.float32)
    lookup_fallback_mask = np.zeros(mask.shape, dtype=bool)
    recolored_mask = np.zeros(mask.shape, dtype=bool)
    clean_success = 0
    clean_fallback = 0
    applied_weights = []

    for y, x in np.argwhere(contaminated_mask):
        weight = float(spill_weight[y, x])
        inner_color = findNearbyCleanInnerColor(
            int(x),
            int(y),
            original_arr,
            mask,
            contaminated_mask,
            inner_edge_band,
            outer_padding_band,
            spill_rgb,
            color_tolerance,
            search_radius,
            alpha_threshold,
            edge_factor,
        )
        if inner_color is None:
            inner_color = findNearbyCleanInnerColor(
                int(x),
                int(y),
                original_arr,
                mask,
                contaminated_mask,
                inner_edge_band,
                outer_padding_band,
                spill_rgb,
                color_tolerance,
                search_radius_2,
                alpha_threshold,
                edge_factor,
            )
        if inner_color is None:
            inner_color = fallback_despill_color(original_arr[y, x, :3], spill_rgb, min(0.25, weight * 0.35))
            weight = min(weight, 0.25)
            clean_fallback += 1
            lookup_fallback_mask[y, x] = True
        else:
            clean_success += 1
        applied_weights.append(weight)

        if test_paint_contaminated:
            repaired[y, x, :3] = np.array((255, 0, 0), dtype=np.float32)
        else:
            repaired[y, x, :3] = original_arr[y, x, :3].astype(np.float32) * (1.0 - weight) + inner_color * weight
        repaired[y, x, 3] = original_arr[y, x, 3]
        if np.any(np.abs(repaired[y, x, :3] - original_arr[y, x, :3].astype(np.float32)) >= 1.0):
            recolored_mask[y, x] = True

    if enable_color_bleeding and process_transparent_padding and np.any(outer_padding_band):
        padding_mask = outer_padding_band & selection_mask & (alpha <= alpha_threshold)
        for y, x in np.argwhere(padding_mask):
            inner_color = findNearbyCleanInnerColor(
                int(x),
                int(y),
                original_arr,
                mask,
                contaminated_mask,
                inner_edge_band,
                outer_padding_band,
                spill_rgb,
                color_tolerance,
                search_radius,
                alpha_threshold,
                edge_factor,
            )
            if inner_color is None:
                inner_color = findNearbyCleanInnerColor(
                    int(x),
                    int(y),
                    original_arr,
                    mask,
                    contaminated_mask,
                    inner_edge_band,
                    outer_padding_band,
                    spill_rgb,
                    color_tolerance,
                    search_radius_2,
                    alpha_threshold,
                    edge_factor,
                )
            if inner_color is not None:
                repaired[y, x, :3] = inner_color
                repaired[y, x, 3] = original_arr[y, x, 3]
            else:
                lookup_fallback_mask[y, x] = True

    if erode_pixels > 0:
        eroded_alpha = erode_mask(mask, erode_pixels)
        repaired[mask & selection_mask & ~eroded_alpha, 3] = 0
    else:
        repaired[:, :, 3] = original_arr[:, :, 3]

    result_arr = original_arr.copy() if detect_only else np.clip(repaired, 0, 255).astype(np.uint8)
    if detect_only:
        result_arr[:, :, 3] = original_arr[:, :, 3]
    rgb_changed_mask = np.any(result_arr[:, :, :3].astype(np.int16) != original_arr[:, :, :3].astype(np.int16), axis=2)
    alpha_changed_mask = result_arr[:, :, 3] != original_arr[:, :, 3]
    rgb_delta = np.sqrt(np.mean((result_arr[:, :, :3].astype(np.float32) - original_arr[:, :, :3].astype(np.float32)) ** 2, axis=2))
    changed_delta = rgb_delta[rgb_changed_mask]
    after_sums = rgba_sums(result_arr)

    masks = {
        "innerEdgeBand": inner_edge_band & selection_mask,
        "outerPaddingBand": outer_padding_band & selection_mask,
        "semiTransparentBand": semi_transparent_band & selection_mask,
        "contaminatedMask": contaminated_mask,
        "lookupFallback": lookup_fallback_mask,
        "actualChangedPixels": rgb_changed_mask,
    }
    stats = {
        "width": int(original_arr.shape[1]),
        "height": int(original_arr.shape[0]),
        "selectionApplied": selection_applied,
        "selectionPixelCount": int(np.count_nonzero(selection_mask)) if selection_applied else int(height * width),
        "spillColor": f"#{int(spill_rgb[0]):02X}{int(spill_rgb[1]):02X}{int(spill_rgb[2]):02X}",
        "colorTolerance": color_tolerance,
        "despillStrength": despill_strength,
        "edgeWidth": edge_width,
        "alphaThreshold": alpha_threshold,
        "maskPixelCount": int(np.count_nonzero(mask)),
        "innerEdgeBandPixelCount": int(np.count_nonzero(inner_edge_band & selection_mask)),
        "outerPaddingBandPixelCount": int(np.count_nonzero(outer_padding_band & selection_mask)),
        "semiTransparentPixelCount": int(np.count_nonzero(semi_transparent_band & selection_mask)),
        "candidatePixelCount": int(np.count_nonzero(candidate_mask)),
        "contaminatedMaskPixelCount": int(np.count_nonzero(contaminated_mask)),
        "contaminatedInnerEdgeCount": int(np.count_nonzero(contaminated_mask & inner_edge_band)),
        "contaminatedSemiTransparentCount": int(np.count_nonzero(contaminated_mask & semi_transparent_band)),
        "contaminatedOuterPaddingCount": int(np.count_nonzero(outer_padding_band & selection_mask & ((alpha <= alpha_threshold) | (similarity > 0.0)))),
        "cleanColorLookupSuccessCount": clean_success,
        "cleanColorLookupFallbackCount": clean_fallback,
        "recoloredPixelCount": int(np.count_nonzero(recolored_mask)),
        "transparentPaddedPixelCount": int(np.count_nonzero(rgb_changed_mask & outer_padding_band & (alpha <= alpha_threshold))),
        "alphaModifiedPixelCount": int(np.count_nonzero(alpha_changed_mask)),
        "totalRGBChangedPixelCount": int(np.count_nonzero(rgb_changed_mask)),
        "totalAlphaChangedPixelCount": int(np.count_nonzero(alpha_changed_mask)),
        "averageColorDelta": float(np.mean(changed_delta)) if changed_delta.size else 0.0,
        "averageRepairWeight": float(np.mean(applied_weights)) if applied_weights else 0.0,
        "maxRepairWeight": float(np.max(applied_weights)) if applied_weights else 0.0,
        "beforeRGBSum": before_sums["RGBSum"],
        "afterRGBSum": after_sums["RGBSum"],
        "beforeAlphaSum": before_sums["AlphaSum"],
        "afterAlphaSum": after_sums["AlphaSum"],
        "detectOnly": detect_only,
        "testPaintContaminated": test_paint_contaminated,
    }
    result = array_to_qimage(result_arr)
    if return_debug_data:
        return result, {
            "stats": stats,
            "overlay": debug_overlay_image(original_arr.shape[1], original_arr.shape[0], masks, debug_overlay_mode),
            "masks": masks,
        }
    return result


def erase_matching_color(image: QImage, x: int, y: int, tolerance: int, contiguous: bool) -> QImage:
    arr = qimage_to_array(image)
    height, width, _ = arr.shape
    if x < 0 or y < 0 or x >= width or y >= height:
        return image.copy()

    target = arr[y, x].copy()
    if target[3] == 0:
        return image.copy()

    return erase_color(image, target, tolerance, contiguous, x, y)


def erase_color(
    image: QImage,
    rgba: Iterable[int],
    tolerance: int,
    contiguous: bool = False,
    start_x: int = 0,
    start_y: int = 0,
) -> QImage:
    arr = qimage_to_array(image)
    mask = color_distance_mask(arr, rgba, tolerance)
    if contiguous:
        height, width = mask.shape
        if start_x < 0 or start_y < 0 or start_x >= width or start_y >= height:
            return image.copy()
        mask = contiguous_region(mask, start_x, start_y)
    arr[mask, 3] = 0
    return array_to_qimage(arr)


def flood_fill(
    image: QImage,
    x: int,
    y: int,
    color: QColor,
    tolerance: int,
    selection_mask_image: Optional[QImage] = None,
) -> QImage:
    arr = qimage_to_array(image)
    height, width, _ = arr.shape
    if x < 0 or y < 0 or x >= width or y >= height:
        return image.copy()

    selection_mask, selection_applied = option_selection_mask(selection_mask_image, height, width)
    if selection_applied and not selection_mask[y, x]:
        return image.copy()

    target = arr[y, x].copy()
    replacement = np.array(qcolor_to_rgba(color), dtype=np.uint8)
    if np.all(np.abs(target.astype(np.int16) - replacement.astype(np.int16)) <= 1):
        return image.copy()

    base_mask = color_distance_mask(arr, target, tolerance) & selection_mask
    fill_mask = contiguous_region(base_mask, x, y)
    arr[fill_mask] = replacement
    return array_to_qimage(arr)


def contiguous_region(mask: np.ndarray, start_x: int, start_y: int) -> np.ndarray:
    height, width = mask.shape
    if not mask[start_y, start_x]:
        return np.zeros_like(mask, dtype=bool)

    visited = np.zeros_like(mask, dtype=bool)
    queue = deque([(start_x, start_y)])
    visited[start_y, start_x] = True

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            if visited[ny, nx] or not mask[ny, nx]:
                continue
            visited[ny, nx] = True
            queue.append((nx, ny))

    return visited


def add_outline(image: QImage, color: QColor, thickness: int = 1) -> QImage:
    arr = qimage_to_array(image)
    alpha = arr[:, :, 3] > 0
    if not np.any(alpha):
        return image.copy()

    outline = np.zeros_like(alpha)
    for dy in range(-thickness, thickness + 1):
        for dx in range(-thickness, thickness + 1):
            if dx == 0 and dy == 0:
                continue
            shifted = np.zeros_like(alpha)
            src_y0 = max(0, -dy)
            src_y1 = alpha.shape[0] - max(0, dy)
            src_x0 = max(0, -dx)
            src_x1 = alpha.shape[1] - max(0, dx)
            dst_y0 = max(0, dy)
            dst_y1 = alpha.shape[0] - max(0, -dy)
            dst_x0 = max(0, dx)
            dst_x1 = alpha.shape[1] - max(0, -dx)
            shifted[dst_y0:dst_y1, dst_x0:dst_x1] = alpha[src_y0:src_y1, src_x0:src_x1]
            outline |= shifted & ~alpha

    rgba = np.array(qcolor_to_rgba(color), dtype=np.uint8)
    arr[outline] = rgba
    return array_to_qimage(arr)


def trim_alpha_edges(image: QImage, pixels: int = 1) -> QImage:
    if pixels <= 0:
        return image.copy()

    arr = qimage_to_array(image)
    alpha = arr[:, :, 3] > 0
    original_alpha = alpha.copy()

    for _ in range(pixels):
        keep = alpha.copy()
        # A square 3x3 kernel removes two staircase levels from 45-degree
        # contours. Four-connected erosion removes exactly one pixel layer.
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            keep &= shift_mask(alpha, dx, dy)
        alpha = keep

    arr[original_alpha & ~alpha, 3] = 0
    return array_to_qimage(arr)
