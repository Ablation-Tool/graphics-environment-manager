from __future__ import annotations

import heapq
import math

import numpy as np

MAX_IMAGE_SIDE = 512
MAX_VOLUME_VOXELS = 262144


def _single_source_costs(shape, edge_cost, source, neighbors):
    distances = {source: 0.0}
    previous = {}
    queue = [(0.0, source)]
    settled = set()
    while queue:
        distance, node = heapq.heappop(queue)
        if node in settled:
            continue
        if distance > distances.get(node, math.inf) + 1e-12:
            continue
        settled.add(node)
        for neighbor in neighbors(node):
            if neighbor in settled:
                continue
            candidate = distance + float(edge_cost(node, neighbor))
            if candidate < distances.get(neighbor, math.inf) - 1e-12:
                distances[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(queue, (candidate, neighbor))
    return distances, previous


def _dct_features(histogram, count=400):
    size = histogram.shape[0]
    positions = np.arange(size)
    frequencies = np.arange(size)
    basis = np.cos(np.pi * (positions[:, None] + .5) * frequencies[None, :] / size)
    basis[:, 0] *= 1 / math.sqrt(2)
    coefficients = basis.T @ histogram @ basis
    order = np.argsort(np.abs(coefficients).reshape(-1))[::-1][:count]
    return [float(value) for value in coefficients.reshape(-1)[order]]


def texture_descriptor(image, pixel_range=255):
    values = np.asarray(image, dtype=float)
    if values.ndim != 2 or not 2 <= values.shape[0] <= MAX_IMAGE_SIDE or not 2 <= values.shape[1] <= MAX_IMAGE_SIDE:
        raise ValueError(f"texture input must be a 2D matrix with both dimensions from 2 to {MAX_IMAGE_SIDE}")
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("texture intensities must be finite and nonnegative")
    if isinstance(pixel_range, bool) or not isinstance(pixel_range, int) or not 1 <= pixel_range <= 4096:
        raise ValueError("pixel_range must be an integer from 1 to 4096")
    height, width = values.shape
    costs, _previous = _single_source_costs(
        values.shape,
        lambda first, second: abs(float(values[first] - values[second])),
        (0, 0),
        lambda node: [
            candidate for candidate in (
                (node[0] - 1, node[1]),
                (node[0] + 1, node[1]),
                (node[0], node[1] - 1),
                (node[0], node[1] + 1),
            ) if 0 <= candidate[0] < height and 0 <= candidate[1] < width
        ],
    )
    histogram = np.zeros((pixel_range, pixel_range), dtype=np.int64)
    ndc_values = []
    nln_values = []
    maximum_l1 = width + height - 2
    for y in range(height):
        for x in range(width):
            if (y, x) == (0, 0):
                continue
            geometric = y + x
            ndc = costs[y, x] / geometric
            nln = geometric / maximum_l1 * pixel_range
            ndc_values.append(ndc)
            nln_values.append(nln)
            x_bin = min(pixel_range - 1, max(0, int(nln)))
            y_bin = min(pixel_range - 1, max(0, int(ndc)))
            histogram[y_bin, x_bin] += 1
    total = int(histogram.sum())
    probabilities = histogram.reshape(-1) / total
    entropy = float(-np.sum(probabilities[probabilities > 0] * np.log2(probabilities[probabilities > 0])))
    return {
        "method": "Ghidoni-style normalized Dijkstra cost and normalized L1 distance histogram",
        "shape": [height, width],
        "seed": [0, 0],
        "seed_handling": "excluded because L1 is zero",
        "pixel_range": pixel_range,
        "histogram_shape": list(histogram.shape),
        "histogram_counts": int(total),
        "histogram": histogram.tolist(),
        "ndc_mean": float(np.mean(ndc_values)),
        "ndc_max": float(np.max(ndc_values)),
        "nln_mean": float(np.mean(nln_values)),
        "histogram_entropy_bits": entropy,
        "feature_vector": _dct_features(histogram),
        "feature_count": 400,
        "feature_method": "400 largest absolute 2D DCT coefficients, including DC",
        "costs": [[float(costs[y, x]) for x in range(width)] for y in range(height)],
    }


def skeletonize_volume(mask, boundary_distance, source):
    volume = np.asarray(mask, dtype=bool)
    distances = np.asarray(boundary_distance, dtype=float)
    if volume.ndim != 3 or volume.size > MAX_VOLUME_VOXELS or volume.shape != distances.shape:
        raise ValueError("volume and boundary distance must share one bounded 3D shape")
    if not np.all(np.isfinite(distances)) or np.any(distances <= 0):
        raise ValueError("boundary distances must be finite and positive")
    if not isinstance(source, tuple) or len(source) != 3 or any(
        not isinstance(index, int) or index < 0 or index >= volume.shape[axis]
        for axis, index in enumerate(source)
    ) or not volume[source]:
        raise ValueError("skeleton source must be an occupied voxel")
    occupied = set(zip(*np.nonzero(volume)))
    costs, previous = _single_source_costs(
        volume.shape,
        lambda first, second: 1 / float(distances[second]),
        source,
        lambda node: [
            candidate for candidate in (
                (node[0] - 1, node[1], node[2]), (node[0] + 1, node[1], node[2]),
                (node[0], node[1] - 1, node[2]), (node[0], node[1] + 1, node[2]),
                (node[0], node[1], node[2] - 1), (node[0], node[1], node[2] + 1),
            ) if candidate in occupied
        ],
    )
    distal = max(costs, key=lambda node: (costs[node], node))
    centerline = [distal]
    while centerline[-1] != source:
        centerline.append(previous[centerline[-1]])
    centerline.reverse()
    symbolic_edges = [{"parent": parent, "child": child} for child, parent in previous.items()]
    return {
        "method": "six-neighbor minimum-cost spanning tree with inverse boundary-distance weights",
        "source": source,
        "distal": distal,
        "max_distance_from_source": costs[distal],
        "centerline": centerline,
        "centerline_voxels": len(centerline),
        "symbolic_edges": symbolic_edges,
        "cycle_policy": "the original occupied graph remains cyclic; the Dijkstra predecessor tree is only a selected annotation",
    }
