from __future__ import annotations

from collections import deque
from typing import Iterable, Tuple

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


def flood_fill(image: QImage, x: int, y: int, color: QColor, tolerance: int) -> QImage:
    arr = qimage_to_array(image)
    height, width, _ = arr.shape
    if x < 0 or y < 0 or x >= width or y >= height:
        return image.copy()

    target = arr[y, x].copy()
    replacement = np.array(qcolor_to_rgba(color), dtype=np.uint8)
    if np.all(np.abs(target.astype(np.int16) - replacement.astype(np.int16)) <= 1):
        return image.copy()

    base_mask = color_distance_mask(arr, target, tolerance)
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
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
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
                keep &= shifted
        alpha = keep

    arr[original_alpha & ~alpha, 3] = 0
    return array_to_qimage(arr)
