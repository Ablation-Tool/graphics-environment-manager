from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from .texture_cognition import _single_source_costs

CENTERS = (2, 3, 4)
OFFSETS = (3, 4)
ANGLES = (0, 45, 90, 135)
SALIENCY_SCALE = 4
MAX_IMAGE_SIDE = 256
MAX_SOURCE_PIXELS = 16_777_216
MAX_SOURCE_BYTES = 32 * 1024 * 1024
ITTI_REFERENCE = "https://ilab.usc.edu/publications/doc/Itti_etal98pami.pdf"
ILAB_THEORY = "https://ilab.usc.edu/bu/theory/index.html"


def rgb_values(image):
    values = np.asarray(image, dtype=np.float64)
    if values.ndim != 3 or values.shape[2] != 3 or any(
        not 16 <= size <= MAX_IMAGE_SIDE for size in values.shape[:2]
    ):
        raise ValueError(f"RGB input must have shape HxWx3 with both dimensions from 16 to {MAX_IMAGE_SIDE}")
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("RGB values must be finite and nonnegative")
    maximum = float(np.max(values))
    return values / maximum if maximum else values.copy()


def load_rgb(path):
    source = Path(path).expanduser().resolve(strict=True)
    if source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("RGB image exceeds the 32 MiB limit")
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError("image-file perception requires the cognition optional dependencies") from error
    with Image.open(source) as image:
        if image.width * image.height > MAX_SOURCE_PIXELS:
            raise ValueError("RGB image exceeds the 16777216-pixel source limit")
        original_shape = [image.height, image.width]
        rgb = image.convert("RGB")
        rgb.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
        values = np.asarray(rgb, dtype=np.uint8)
    rgb_values(values)
    return values, {
        "kind": "image_file",
        "path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "original_shape": original_shape,
        "processed_shape": list(values.shape[:2]),
        "resampling": "Pillow Lanczos within 256 pixels per side",
        "live_camera": False,
    }


def prototype_image():
    image = np.full((64, 64, 3), .08, dtype=np.float64)
    image[44:52, 12:20] = (.12, .12, .80)
    image[12:20, 44:52] = (.75, .75, .75)
    return image


def _filter2d(image, kernel):
    kernel = np.asarray(kernel, dtype=np.float64)
    if kernel.ndim == 1:
        kernel = kernel.reshape(1, -1)
    radius_y, radius_x = kernel.shape[0] // 2, kernel.shape[1] // 2
    padded = np.pad(image, ((radius_y, radius_y), (radius_x, radius_x)), mode="reflect")
    result = np.zeros_like(image, dtype=np.float64)
    for row in range(kernel.shape[0]):
        for column in range(kernel.shape[1]):
            result += kernel[row, column] * padded[
                row:row + image.shape[0], column:column + image.shape[1]
            ]
    return result


def _gaussian_pyramid(image):
    kernel = np.asarray([1, 8, 28, 56, 70, 56, 28, 8, 1], dtype=np.float64) / 256
    levels = [np.asarray(image, dtype=np.float64)]
    for _ in range(8):
        smoothed = _filter2d(_filter2d(levels[-1], kernel), kernel.reshape(-1, 1))
        levels.append(smoothed[::2, ::2])
    return levels


def _resize(image, shape):
    if image.shape == shape:
        return image.copy()
    height, width = shape
    x = np.linspace(0, image.shape[1] - 1, width)
    y = np.linspace(0, image.shape[0] - 1, height)
    left = np.floor(x).astype(int)
    top = np.floor(y).astype(int)
    right = np.minimum(left + 1, image.shape[1] - 1)
    bottom = np.minimum(top + 1, image.shape[0] - 1)
    dx = x - left
    dy = y - top
    horizontal = image[:, left] * (1 - dx) + image[:, right] * dx
    return horizontal[top] * (1 - dy[:, None]) + horizontal[bottom] * dy[:, None]


def competitive_normalize(image):
    values = np.asarray(image, dtype=np.float64)
    if values.ndim != 2 or not 1 <= values.size <= MAX_IMAGE_SIDE**2:
        raise ValueError("normalization input must be a bounded 2D map")
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("normalization values must be finite and nonnegative")
    maximum = float(np.max(values))
    metadata = {
        "fixed_range": [0, 1],
        "global_maximum": maximum,
        "local_maximum_rule": "strictly greater than all eight neighbors",
        "other_local_maximum_mean": 0.0,
        "local_maximum_count": 0,
        "weight": 0.0,
    }
    if maximum == 0:
        metadata["reason"] = "empty_map"
        return np.zeros_like(values), metadata
    padded = np.pad(values, 1, constant_values=-np.inf)
    neighbors = np.maximum.reduce([
        padded[1 + dy:1 + dy + values.shape[0], 1 + dx:1 + dx + values.shape[1]]
        for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx
    ])
    peaks = values > neighbors
    peak_values = values[peaks]
    metadata["local_maximum_count"] = int(peak_values.size)
    if not peak_values.size:
        metadata["reason"] = "no_strict_local_maximum"
        return np.zeros_like(values), metadata
    others = peak_values[peak_values < maximum]
    mean = float(np.mean(others) / maximum) if others.size else 0.0
    weight = (1 - mean)**2
    metadata.update({
        "other_local_maximum_mean": float(np.mean(others)) if others.size else 0.0,
        "normalized_other_maximum_mean": mean,
        "weight": weight,
        "reason": "single_peak_promoted" if not others.size else "peak_competition",
    })
    return values / maximum * weight, metadata


def _gabor_pyramids(intensity_pyramid):
    coordinates = np.arange(9, dtype=np.float64) - 4
    yy, xx = np.meshgrid(coordinates, coordinates, indexing="ij")
    pyramids = {}
    for angle in ANGLES:
        theta = math.radians(angle + 90)
        u = xx * math.cos(theta) + yy * math.sin(theta)
        v = -xx * math.sin(theta) + yy * math.cos(theta)
        envelope = np.exp(-.5 * ((u / (7 / 3))**2 + (v / (7 / 3))**2))
        phase = math.tau * u / 7
        kernels = tuple(
            kernel - np.mean(kernel)
            for kernel in (envelope * np.cos(phase), envelope * np.sin(phase))
        )
        pyramids[angle] = [
            sum(np.abs(_filter2d(level, kernel)) for kernel in kernels)
            for level in intensity_pyramid
        ]
    return pyramids


def _conspicuity(features, shape):
    combined = np.zeros(shape, dtype=np.float64)
    records = []
    for kind, center, surround, angle, feature in features:
        normalized, normalization = competitive_normalize(feature)
        combined += _resize(normalized, shape)
        records.append({
            "kind": kind,
            "center": center,
            "surround": surround,
            "orientation_degrees": angle,
            "normalization": normalization,
        })
    normalized, normalization = competitive_normalize(combined)
    return normalized, records, normalization


def attention_scanpath(saliency, original_shape, steps=4):
    values = np.asarray(saliency, dtype=np.float64)
    if values.ndim != 2 or values.size == 0 or values.shape[0] > MAX_IMAGE_SIDE or values.shape[1] > MAX_IMAGE_SIDE:
        raise ValueError("saliency must be a nonempty bounded 2D map")
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("saliency values must be finite and nonnegative")
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 8:
        raise ValueError("attention steps must be an integer from 1 to 8")
    height, width = values.shape
    working = values.copy()
    radius = max(1, min(height, width) / 6)
    yy, xx = np.mgrid[:height, :width]
    scanpath = []
    for _ in range(steps):
        if not np.any(working > 0):
            break
        y, x = np.unravel_index(int(np.argmax(working)), working.shape)
        focus = {
            "sequence": len(scanpath) + 1,
            "map_xy": [int(x), int(y)],
            "source_xy": [
                min(original_shape[1] - 1, int(x * (2**SALIENCY_SCALE))),
                min(original_shape[0] - 1, int(y * (2**SALIENCY_SCALE))),
            ],
            "saliency": float(values[y, x]),
            "inhibition_radius_map_pixels": radius,
        }
        if scanpath:
            start = tuple(scanpath[-1]["map_xy"][::-1])
            goal = (int(y), int(x))
            costs, previous = _single_source_costs(
                values.shape,
                lambda first, second: math.hypot(second[0] - first[0], second[1] - first[1]) / max(float(values[second]), .001),
                start,
                lambda node: [
                    candidate for candidate in (
                        (node[0] - 1, node[1]), (node[0] + 1, node[1]),
                        (node[0], node[1] - 1), (node[0], node[1] + 1),
                    ) if 0 <= candidate[0] < height and 0 <= candidate[1] < width
                ],
            )
            path = [goal]
            while path[-1] != start:
                path.append(previous[path[-1]])
            path.reverse()
            focus["navigation"] = {
                "algorithm": "exact four-neighbor Dijkstra on the unchanged pre-inhibition saliency map",
                "cost": float(costs[goal]),
                "edge_cost": "Euclidean pixel distance divided by max(destination saliency, 0.001)",
                "map_path": [[int(px), int(py)] for py, px in path],
                "scope": "attention routing, not physical navigation or object identity",
            }
        scanpath.append(focus)
        working[(yy - y)**2 + (xx - x)**2 <= radius**2] = 0
    return scanpath


def saliency_report(image, source=None, steps=4):
    rgb = rgb_values(image)
    intensity = np.mean(rgb, axis=2)
    threshold = float(np.max(intensity)) / 10
    mask = intensity > threshold
    red, green, blue = (np.where(mask, rgb[:, :, index] / np.where(mask, intensity, 1), 0) for index in range(3))
    color_channels = (
        red - (green + blue) / 2,
        green - (red + blue) / 2,
        blue - (red + green) / 2,
        (red + green) / 2 - np.abs(red - green) / 2 - blue,
    )
    red, green, blue, yellow = (np.maximum(channel, 0) for channel in color_channels)
    intensity_pyramid = _gaussian_pyramid(intensity)
    color_pyramids = [_gaussian_pyramid(channel) for channel in (red, green, blue, yellow)]
    orientation_pyramids = _gabor_pyramids(intensity_pyramid)
    features = []
    for center in CENTERS:
        for offset in OFFSETS:
            surround = center + offset
            features.append((
                "intensity", center, surround, None,
                np.abs(intensity_pyramid[center] - _resize(intensity_pyramid[surround], intensity_pyramid[center].shape)),
            ))
    for center in CENTERS:
        for offset in OFFSETS:
            surround = center + offset
            for kind, first, second in (("red_green", 0, 1), ("blue_yellow", 2, 3)):
                fine = color_pyramids[first][center] - color_pyramids[second][center]
                coarse = color_pyramids[second][surround] - color_pyramids[first][surround]
                features.append((kind, center, surround, None, np.abs(fine - _resize(coarse, fine.shape))))
    for center in CENTERS:
        for offset in OFFSETS:
            surround = center + offset
            for angle in ANGLES:
                fine = orientation_pyramids[angle][center]
                coarse = _resize(orientation_pyramids[angle][surround], fine.shape)
                features.append(("orientation", center, surround, angle, np.abs(fine - coarse)))
    shape = rgb.shape[:2]
    scale_shape = intensity_pyramid[SALIENCY_SCALE].shape
    intensity_map, intensity_features, intensity_normalization = _conspicuity(
        [feature for feature in features if feature[0] == "intensity"], scale_shape,
    )
    color_map, color_features, color_normalization = _conspicuity(
        [feature for feature in features if feature[0] in {"red_green", "blue_yellow"}], scale_shape,
    )
    orientation_map = np.zeros(scale_shape, dtype=np.float64)
    orientation_features = []
    for angle in ANGLES:
        angle_map, angle_features, _ = _conspicuity(
            [feature for feature in features if feature[0] == "orientation" and feature[3] == angle], scale_shape,
        )
        orientation_map += angle_map
        orientation_features.extend(angle_features)
    orientation_map, orientation_normalization = competitive_normalize(orientation_map)
    saliency = (intensity_map + color_map + orientation_map) / 3
    scanpath = attention_scanpath(saliency, shape, steps)
    return {
        "schema_version": 1,
        "instrument": "Itti-Koch-Niebur multiscale saliency within Zoe's native cognitive field",
        "source": source or {"kind": "documented_synthetic_rgb_popout", "live_camera": False},
        "shape": list(shape),
        "scale": SALIENCY_SCALE,
        "pyramid_scales": 9,
        "center_scales": list(CENTERS),
        "surround_offsets": list(OFFSETS),
        "orientation_angles": list(ANGLES),
        "feature_map_counts": {"intensity": 6, "color": 12, "orientation": 24, "total": 42},
        "normalization": "N(X) = (X/M) * (1 - mean(other local maxima)/M)^2; strict eight-neighbor maxima",
        "feature_combination": "across-scale addition at scale four, then equal averaging of the three normalized conspicuity maps",
        "conspicuity": {
            "intensity": {"normalization": intensity_normalization, "map": intensity_map.tolist()},
            "color": {"normalization": color_normalization, "map": color_map.tolist()},
            "orientation": {"normalization": orientation_normalization, "map": orientation_map.tolist()},
        },
        "saliency_map": saliency.tolist(),
        "scanpath": scanpath,
        "feature_maps": intensity_features + color_features + orientation_features,
        "attention_mechanism": {
            "selection": "deterministic maximum with row-major tie breaking",
            "inhibition": "zero a disk of radius min(map height, map width)/6 after each selection",
            "continuous_neural_dynamics_simulated": False,
            "object_recognition_performed": False,
            "live_camera_control": False,
        },
        "references": [ITTI_REFERENCE, ILAB_THEORY],
        "scope": "Independent NumPy implementation of the published feature and attention equations; not the full iLab C++ toolkit or a human-fixation validation",
        "external_actions": 0,
        "executed": False,
    }
