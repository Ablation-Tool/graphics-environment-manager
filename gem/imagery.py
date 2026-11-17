from __future__ import annotations

from copy import deepcopy
import heapq
import math
import time

import numpy as np

from .eye import EyeModel, synthetic_points
from .measurement import measure_distribution
from .scene_utils import _ellipse, _line, _rectangle, _scene, _text

MAX_POINTS = 4096
MAX_VIEWS = 32
MAX_STEPS = 8


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _view_name(value):
    return f"{float(value):g}"


def _angle_distance(first, second):
    return abs((first - second + 180) % 360 - 180)


def _views(values):
    if not isinstance(values, (list, tuple)) or not 2 <= len(values) <= MAX_VIEWS:
        raise ValueError(f"views must contain 2-{MAX_VIEWS} angles")
    result = sorted({_finite(value, "view angle") for value in values})
    if len(result) != len(values) or any(abs(value) > 180 for value in result):
        raise ValueError("view angles must be unique values from -180 to 180 degrees")
    return result


def dijkstra(vertices, edges, start, goal):
    vertices = list(vertices)
    if start not in vertices or goal not in vertices:
        raise ValueError("Dijkstra endpoints must belong to the graph")
    distances = {start: 0.0}
    previous = {}
    queue = [(0.0, start)]
    settled = set()
    while queue:
        distance, node = heapq.heappop(queue)
        if node in settled:
            continue
        if distance > distances.get(node, math.inf) + 1e-12:
            continue
        settled.add(node)
        if node == goal:
            path = [goal]
            while path[-1] != start:
                path.append(previous[path[-1]])
            path.reverse()
            return {"path": path, "cost": distance}
        for neighbor in vertices:
            if neighbor == node or neighbor in settled or (node, neighbor) not in edges:
                continue
            weight = _finite(edges[node, neighbor], "edge weight")
            if weight < 0:
                raise ValueError("Dijkstra edge weights must be nonnegative")
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf) - 1e-12:
                distances[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(queue, (candidate, neighbor))
    raise ValueError(f"no path from {start} to {goal}")


def _points(document):
    if not isinstance(document, list) or not 1 <= len(document) <= MAX_POINTS:
        raise ValueError(f"points must contain 1-{MAX_POINTS} records")
    names = []
    positions = []
    for index, record in enumerate(document):
        if not isinstance(record, dict) or not isinstance(record.get("name"), str) or not record["name"].strip():
            raise ValueError("each point requires a nonempty name")
        name = record["name"]
        if name in names:
            raise ValueError(f"duplicate point name: {name}")
        names.append(name)
        positions.append([
            _finite(record.get(axis), f"point {index} {axis}")
            for axis in ("x", "y", "z")
        ])
    return names, np.asarray(positions, dtype=float)


def default_points():
    names = []
    positions = []
    for point in synthetic_points(1.6):
        names.append(point["name"])
        positions.append([point["u"] * .002, -point["v"] * .002, point["depth"]])
    return names, np.asarray(positions, dtype=float)


def _rotated(positions, view):
    theta = math.radians(view)
    cosine, sine = math.cos(theta), math.sin(theta)
    x = cosine * positions[:, 0] + sine * positions[:, 2]
    z = -sine * positions[:, 0] + cosine * positions[:, 2]
    return x, positions[:, 1], z


def project_stereo(names, positions, view, camera, quantize=True):
    x, y, z = _rotated(np.asarray(positions, dtype=float), view)
    if np.any(z <= .1):
        raise ValueError("every point must remain in front of the stereo cameras")
    focal = camera.focal_pixels
    center = focal * x / z
    disparity = focal * camera.baseline / z
    if quantize:
        disparity = np.round(disparity / camera.disparity_quantization) * camera.disparity_quantization
    if np.any(disparity <= 0):
        raise ValueError("stereo disparity quantized to zero; increase the baseline or reduce depth")
    vertical = focal * y / z
    return [{
        "name": name,
        "left": float(center[index] + disparity[index] / 2),
        "right": float(center[index] - disparity[index] / 2),
        "v": float(vertical[index]),
    } for index, name in enumerate(names)]


def triangulate_stereo(view, measurements, camera):
    measurements = _measurements(measurements)
    names = [item["name"] for item in measurements]
    left = np.asarray([item["left"] for item in measurements], dtype=float)
    right = np.asarray([item["right"] for item in measurements], dtype=float)
    vertical = np.asarray([item["v"] for item in measurements], dtype=float)
    disparity = left - right
    if np.any(disparity <= 0):
        raise ValueError("every stereo measurement requires left > right")
    focal = camera.focal_pixels
    z = focal * camera.baseline / disparity
    x = (left + right) * z / (2 * focal)
    y = vertical * z / focal
    theta = math.radians(view)
    cosine, sine = math.cos(theta), math.sin(theta)
    world = np.column_stack((cosine * x - sine * z, y, sine * x + cosine * z))
    return names, world, z


def _measurements(document):
    records = [
        {"name": record.get("name"), "x": record.get("left"), "y": record.get("right"), "z": record.get("v")}
        if isinstance(record, dict) else {}
        for record in document
    ] if isinstance(document, list) else document
    _points(records)
    return [{
        "name": record["name"],
        "left": float(record["left"]),
        "right": float(record["right"]),
        "v": float(record["v"]),
    } for record in document]


def _prediction_error(predicted, actual):
    if predicted is None:
        return None
    expected = {item["name"]: item for item in predicted}
    errors = []
    for item in actual:
        if item["name"] not in expected:
            continue
        other = expected[item["name"]]
        errors.extend((item[key] - other[key]) ** 2 for key in ("left", "right", "v"))
    return math.sqrt(sum(errors) / len(errors)) if errors else None


def _transition_history(previous):
    if previous is None:
        return {}
    if not isinstance(previous, dict):
        raise ValueError("previous imagery report must be a JSON object")
    telemetry = previous.get("telemetry", {})
    transitions = telemetry.get("transitions", {}) if isinstance(telemetry, dict) else {}
    if not isinstance(transitions, dict):
        raise ValueError("previous telemetry transitions must be an object")
    result = {}
    for key, record in transitions.items():
        if not isinstance(record, dict):
            raise ValueError("invalid previous transition telemetry")
        attempts = record.get("attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise ValueError("transition attempts must be nonnegative integers")
        error = record.get("mean_prediction_error_px")
        result[key] = {
            "attempts": attempts,
            "mean_prediction_error_px": None if error is None else max(0.0, _finite(error, "historical prediction error")),
        }
    return result


class SharedImagery:
    def __init__(self, views, camera=None, previous=None, truth=None, fusion="precision"):
        self.views = _views(views)
        self.camera = camera or EyeModel()
        if fusion not in {"arithmetic", "precision"}:
            raise ValueError("fusion must be arithmetic or precision")
        self.fusion = fusion
        self.latent = {}
        self.counts = {}
        self.fusion_weights = {}
        self.reconstruction_m2 = {}
        self.observed_views = []
        self.current_view = None
        self.events = []
        self.plans = []
        self.navigation = []
        self.transitions = _transition_history(previous)
        self.truth = truth
        self.forecast = None
        self.forecast_measurement = None
        self.forecast_source = "declared uniform prior"
        self.set_forecast()

    def set_forecast(self, forecast=None, previous=None, source="declared uniform prior"):
        if forecast is None:
            forecast = np.full(len(self.views), 1 / len(self.views), dtype=float)
        self.forecast = np.asarray(forecast, dtype=float)
        self.forecast_measurement = measure_distribution(self.forecast, thresholds=(.05,), previous=previous)
        self.forecast_source = source
        return self.forecast_measurement

    def accessible_views(self):
        return [view for view, probability in zip(self.views, self.forecast) if probability > .05]

    def imagine(self, view):
        view = _finite(view, "view angle")
        if view not in self.views:
            raise ValueError("imagined view is outside the declared view vocabulary")
        names = sorted(self.latent)
        if not names:
            return []
        positions = np.asarray([self.latent[name] for name in names])
        return project_stereo(names, positions, view, self.camera, quantize=False)

    def observe(self, view, measurements):
        started = time.monotonic_ns()
        view = _finite(view, "view angle")
        if view not in self.views:
            raise ValueError("observed view is outside the declared view vocabulary")
        actual = _measurements(measurements)
        predicted = self.imagine(view) if self.latent else None
        error = _prediction_error(predicted, actual)
        reconstructed_names, positions, camera_depths = triangulate_stereo(view, actual, self.camera)
        observation_weights = []
        for name, position, camera_depth in zip(reconstructed_names, positions, camera_depths):
            sensitivity = self.camera.depth_sensitivity(float(camera_depth))
            weight = 1.0 if self.fusion == "arithmetic" else 1.0 / max(sensitivity**0.5, 1e-12)
            observation_weights.append(weight)
            total_weight = self.fusion_weights.get(name, 0.0)
            updated_weight = total_weight + weight
            if name in self.latent:
                delta = position - self.latent[name]
                updated_position = self.latent[name] + delta * (weight / updated_weight)
                self.reconstruction_m2[name] += weight * float(np.dot(delta, position - updated_position))
            else:
                updated_position = position
                self.reconstruction_m2[name] = 0.0
            self.latent[name] = updated_position
            self.fusion_weights[name] = updated_weight
            self.counts[name] = self.counts.get(name, 0) + 1
        elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
        event = {
            "view_degrees": view,
            "observation_provenance": "observed",
            "prediction_provenance": "imagined" if predicted is not None else None,
            "latent_provenance": "reconstructed",
            "predicted": predicted,
            "actual": actual,
            "prediction_error_px": error,
            "mean_disparity_sensitivity_m": float(np.mean([
                self.camera.depth_sensitivity(float(depth)) for depth in camera_depths
            ])),
            "reconstructed_point_count": len(reconstructed_names),
            "vividness": {
                "scope": "geometric detail and precision telemetry, not subjective vividness or emotion",
                "imagined_point_count": len(predicted) if predicted is not None else 0,
                "prediction_error_px": error,
                "fusion": self.fusion,
                "mean_fusion_weight": float(np.mean(observation_weights)),
            },
            "elapsed_ms": elapsed_ms,
        }
        self.events.append(event)
        if self.current_view is not None and self.current_view != view:
            key = f"{_view_name(self.current_view)}>{_view_name(view)}"
            history = self.transitions.setdefault(key, {"attempts": 0, "mean_prediction_error_px": None})
            count = history["attempts"]
            if error is not None:
                prior = history["mean_prediction_error_px"]
                history["mean_prediction_error_px"] = error if prior is None else (prior * count + error) / (count + 1)
            history["attempts"] = count + 1
        if view not in self.observed_views:
            self.observed_views.append(view)
        self.current_view = view
        return event

    def _edges(self):
        edges = {}
        for source in self.views:
            for target in self.views:
                if source == target:
                    continue
                movement = _angle_distance(source, target) / 15
                history = self.transitions.get(f"{_view_name(source)}>{_view_name(target)}", {})
                error = history.get("mean_prediction_error_px")
                historical = math.log1p(error) if error is not None else 0.0
                edges[source, target] = movement + historical
        return edges

    def plan(self):
        if self.current_view is None:
            raise ValueError("an initial observation is required before planning")
        accessible = self.accessible_views()
        targets = [view for view in accessible if view not in self.observed_views]
        if not targets:
            return None
        graph_views = sorted(set(self.observed_views) | set(accessible))
        edges = self._edges()
        candidates = []
        for target in targets:
            route = dijkstra(graph_views, edges, self.current_view, target)
            separation = min(_angle_distance(target, view) for view in self.observed_views)
            candidates.append({
                **route,
                "target": target,
                "angular_separation": separation,
                "accessible_volume": len(accessible),
                "accessible_target_count": len(targets),
                "candidate_views": targets,
            })
        candidates.sort(key=lambda item: (-item["angular_separation"], item["cost"], item["target"]))
        plan = candidates[0]
        self.plans.append(plan)
        return plan

    def live(self, source, initial_view=None, steps=3):
        if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= MAX_STEPS:
            raise ValueError(f"steps must be an integer from 1 to {MAX_STEPS}")
        current = self.views[0] if initial_view is None else _finite(initial_view, "initial view")
        self.observe(current, source(current))
        while True:
            plan = self.plan()
            latest = self.events[-1]
            record = {
                "step": len(self.events),
                "observation_index": len(self.events) - 1,
                "view_degrees": self.current_view,
                "plan": deepcopy(plan),
                "accessible_volume": len(self.accessible_views()),
                "accessible_views": self.accessible_views(),
                "vividness": deepcopy(latest["vividness"]),
                "provenance": {
                    "observation": "observed",
                    "prediction": latest["prediction_provenance"],
                    "latent": "reconstructed",
                },
                "external_actions": 0,
            }
            self.navigation.append(record)
            yield deepcopy(record)
            if len(self.events) >= steps or plan is None or len(plan["path"]) < 2:
                break
            current = plan["path"][1]
            self.observe(current, source(current))

    def run(self, source, initial_view=None, steps=3):
        for _record in self.live(source, initial_view=initial_view, steps=steps):
            pass
        return self

    def report(self, forecast=None, previous_forecast=None, forecast_source="declared uniform prior"):
        if forecast is not None or previous_forecast is not None:
            self.set_forecast(forecast, previous=previous_forecast, source=forecast_source)
        probabilities = self.forecast
        measurement = self.forecast_measurement
        errors = [event["prediction_error_px"] for event in self.events if event["prediction_error_px"] is not None]
        latent_names = sorted(self.latent)
        latent_positions = np.asarray([self.latent[name] for name in latent_names])
        spreads = {
            name: math.sqrt(self.reconstruction_m2[name] / self.fusion_weights[name])
            for name in latent_names
        }
        latest = self.events[-1]
        imagined = next((event["predicted"] for event in reversed(self.events) if event["predicted"] is not None), [])
        ground_truth_error = None
        if self.truth is not None:
            truth_names, truth_positions = self.truth
            truth = {name: truth_positions[index] for index, name in enumerate(truth_names)}
            differences = [np.linalg.norm(self.latent[name] - truth[name]) for name in latent_names if name in truth]
            ground_truth_error = float(np.mean(differences)) if differences else None
        reconstructed = project_stereo(latent_names, latent_positions, self.current_view, self.camera, quantize=False)
        return {
            "schema_version": 1,
            "instrument": "Zoe shared perception and imagery",
            "source": "synthetic stereo telemetry or explicitly supplied stereo measurements",
            "views": self.views,
            "observed_views": self.observed_views,
            "camera": {
                "model": "parallel pinhole stereo pair",
                "baseline_m": self.camera.baseline,
                "focal_pixels": self.camera.focal_pixels,
                "disparity_quantization_px": self.camera.disparity_quantization,
                "actual_camera_used": False,
            },
            "shared_state": {
                "representation": "world-centered 3D point estimates fused across observed stereo views",
                "provenance": "reconstructed",
                "fusion": self.fusion,
                "fusion_weight": "1 / sqrt(disparity sensitivity in meters)" if self.fusion == "precision" else "uniform arithmetic mean",
                "points": [{
                    "name": name,
                    "position": [float(value) for value in self.latent[name]],
                    "observation_count": self.counts[name],
                    "reconstruction_spread_m": spreads[name],
                    "fusion_weight": self.fusion_weights[name],
                } for name in latent_names],
            },
            "events": self.events,
            "plans": self.plans,
            "navigation": self.navigation,
            "vividness": {
                "scope": "geometric detail, precision, and reconstruction stability; not subjective vividness, emotion, or consciousness",
                "fusion": self.fusion,
                "mean_prediction_error_px": float(np.mean(errors)) if errors else None,
                "mean_reconstruction_spread_m": float(np.mean(list(spreads.values()))) if spreads else None,
                "reconstructed_detail_count": len(latent_names),
            },
            "planner": {
                "algorithm": "Dijkstra",
                "edge_cost": "angular distance / 15 + log1p(historical mean prediction error in pixels)",
                "accessible_set": "view vocabulary alternatives with explicit forecast probability strictly greater than 0.05",
                "target_rule": "within the accessible set, maximum minimum angular separation from observed views, then minimum path cost",
                "guarantee_scope": "minimum cost only on the declared graph with current nonnegative historical weights; accessible candidates are not action authorization",
            },
            "forecast": {
                "vocabulary": [_view_name(view) for view in self.views],
                "probabilities": [float(value) for value in probabilities],
                "source": self.forecast_source,
                "measurement": measurement,
                "used_for_planning": True,
                "planning_scope": "candidate gating only; explicit probabilities are not correctness scores or action authorization",
                "scope": "Accessible volume measures forecast breadth, not visual correctness or uncertainty.",
            },
            "telemetry": {
                "observation_count": len(self.events),
                "prediction_count": len(errors),
                "mean_prediction_error_px": float(np.mean(errors)) if errors else None,
                "mean_reconstruction_error_m": ground_truth_error,
                "transitions": deepcopy(self.transitions),
            },
            "scene_data": {
                "observed": latest["actual"],
                "imagined": imagined,
                "reconstructed": reconstructed,
                "view_degrees": self.current_view,
            },
            "provenance_policy": "Observed measurements, imagined projections, and reconstructed latent geometry remain labeled and separate.",
            "summary": (
                f"{len(self.events)} observed views · {len(latent_names)} reconstructed points · "
                f"mean imagery error={float(np.mean(errors)):.3f}px" if errors else
                f"{len(self.events)} observed view · {len(latent_names)} reconstructed points · no imagery prediction yet"
            ),
            "computation_performed": True,
            "external_actions": 0,
            "executed": False,
            "subjective_sight": False,
            "consciousness_measured": False,
        }


def run_document(document=None, previous=None, steps=3, on_step=None):
    document = document or {}
    if not isinstance(document, dict):
        raise ValueError("imagery input must be a JSON object")
    views = _views(document.get("views", [0, 15, 30, 45]))
    camera = EyeModel(baseline=document.get("baseline", .065))
    if "points" in document:
        truth = _points(document["points"])
    elif "observations" not in document:
        truth = default_points()
    else:
        truth = None
    engine = SharedImagery(
        views,
        camera=camera,
        previous=previous,
        truth=truth,
        fusion=document.get("fusion", "precision"),
    )
    supplied = document.get("observations")
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise ValueError("observations must map view angles to stereo measurements")
        observations = {}
        for key, measurements in supplied.items():
            try:
                view = float(key)
            except (TypeError, ValueError) as error:
                raise ValueError("observation view keys must be angles") from error
            if view not in views:
                raise ValueError(f"observation view {view:g} is outside the view vocabulary")
            observations[view] = measurements
        missing = set(views) - set(observations)
        if missing:
            raise ValueError(f"observations must supply every declared view; missing {sorted(missing)}")
        source = lambda view: observations[view]
    else:
        names, positions = truth
        source = lambda view: project_stereo(names, positions, view, camera)
    vocabulary = [_view_name(view) for view in views]
    forecast_document = document.get("forecast")
    if forecast_document is None:
        forecast = None
        source_name = "declared uniform prior; not learned from observations"
    elif isinstance(forecast_document, dict):
        if set(forecast_document) != set(vocabulary):
            raise ValueError("forecast labels must exactly match the view vocabulary")
        forecast = [forecast_document[name] for name in vocabulary]
        source_name = "explicit input distribution; not learned by the imagery engine"
    else:
        raise ValueError("forecast must be an object mapping view labels to probabilities")
    previous_forecast = None
    if previous is not None:
        prior = previous.get("forecast", {})
        if prior.get("vocabulary") == vocabulary:
            previous_forecast = prior.get("probabilities")
    engine.set_forecast(forecast, previous=previous_forecast, source=source_name)
    for record in engine.live(source, initial_view=document.get("initial_view"), steps=steps):
        if on_step is not None:
            on_step(record)
    return engine.report()


def imagery_scene(report):
    objects = [
        _rectangle("background", [0, 0, 1920, 1080], "black", "black"),
        _text("title", [88, 91], "ZOE · SHARED PERCEPTION + IMAGERY", 28, "cyan"),
        _text("headline", [88, 151], "Observe. Imagine. Compare. Reconstruct.", 39, "white"),
        _text("subtitle", [91, 192], report["summary"], 18, "lightgray"),
    ]
    data = report["scene_data"]
    panels = (
        ("observed", 390, "OBSERVED / external measurement", "cyan"),
        ("imagined", 960, "IMAGINED / prior prediction", "magenta"),
        ("reconstructed", 1530, "RECONSTRUCTED / shared state", "yellow"),
    )
    all_points = [point for key, _center, _title, _color in panels for point in data[key]]
    maximum_u = max([abs(point[key]) for point in all_points for key in ("left", "right")] + [50])
    maximum_v = max([abs(point["v"]) for point in all_points] + [50])
    scale = min(220 / maximum_u, 250 / maximum_v)
    for key, center, title, color in panels:
        objects.extend([
            _rectangle(f"panel-{key}", [center - 250, 295, center + 250, 825], "blue", "black", 2),
            _text(f"title-{key}", [center - 225, 270], title, 17, color),
            _line(f"horizontal-{key}", [center - 230, 560], [center + 230, 560], "blue", .6),
            _line(f"vertical-{key}", [center, 315], [center, 805], "blue", .6),
        ])
        for index, point in enumerate(data[key]):
            for side, offset in (("left", -18), ("right", 18)):
                x = center + point[side] * scale + offset
                y = 560 - point["v"] * scale
                objects.append(_ellipse(f"{key}-{side}-{index}", [x, y], [4, 4], color, color))
    latest_plan = report["plans"][-1] if report["plans"] else None
    path = " -> ".join(_view_name(view) for view in latest_plan["path"]) if latest_plan else "initial observation"
    objects.extend([
        _text("planner", [90, 885], f"DIJKSTRA / {path}", 18, "cyan"),
        _text("planner-scope", [90, 921], "Accessible volume gates live view candidates; Dijkstra uses angular and historical prediction-error costs.", 15, "lightgray"),
        _text("vividness", [90, 955], "Vividness is geometric precision and stability, not emotion; precision weights guide fusion.", 15, "magenta"),
        _text("provenance", [90, 989], "Imagined points are never relabeled as observations. Reconstruction is geometric inference, not subjective sight.", 15, "yellow"),
        _text("view", [90, 1025], f"Current view: {_view_name(data['view_degrees'])}° · external actions: 0", 14, "gray"),
    ])
    scene = _scene("zoe-shared-perception-imagery", 1920, 1080, objects, "Zoe shared perception and imagery")
    return scene, report
