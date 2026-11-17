from __future__ import annotations

from copy import deepcopy
import math

from .scene_utils import _ellipse, _line, _rectangle, _scene, _text

CAPABILITIES = ("perception", "thinking", "learning", "action")
POSITIONS = ((960, 275), (1435, 555), (960, 835), (485, 555))
ANGLES = (-90, 0, 90, 180)
DEFAULT_TEMPLATE = {
    "schema_version": 1,
    "title": "ZOE / CYCLIC FIELD",
    "subtitle": "Observe. Imagine. Learn. Navigate. Repeat.",
    "cycle": list(CAPABILITIES),
    "labels": {
        "perception": "PERCEPTION",
        "thinking": "THINKING",
        "learning": "LEARNING",
        "action": "ACTION",
        "center": "SHARED GEOMETRY",
        "vividness": "VIVIDNESS",
    },
    "palette": {
        "perception": "cyan",
        "thinking": "magenta",
        "learning": "yellow",
        "action": "orange",
        "center": "cyan",
    },
    "transitions": ["proposals", "feedback", "weights", "observations"],
}
PALETTE_NAMES = {"white", "black", "red", "green", "blue", "cyan", "yellow", "magenta", "orange", "gray", "lightgray"}


def _bounded_text(value, label, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} must be printable text with 1-{maximum} characters")
    return value


def network_template(document=None):
    if document is None:
        return deepcopy(DEFAULT_TEMPLATE)
    if not isinstance(document, dict) or set(document) != set(DEFAULT_TEMPLATE):
        raise ValueError("cyclic template must contain exactly the default template fields")
    if document["schema_version"] != 1:
        raise ValueError("cyclic template schema_version must be 1")
    result = deepcopy(document)
    _bounded_text(result["title"], "template title", 80)
    _bounded_text(result["subtitle"], "template subtitle", 160)
    if not isinstance(result["cycle"], list) or len(result["cycle"]) != 4 or set(result["cycle"]) != set(CAPABILITIES):
        raise ValueError("template cycle must contain each capability exactly once")
    if set(result["labels"]) != set(DEFAULT_TEMPLATE["labels"]):
        raise ValueError("template labels must match the default label keys")
    for key, value in result["labels"].items():
        _bounded_text(value, f"label {key}", 40)
    if set(result["palette"]) != set(DEFAULT_TEMPLATE["palette"]):
        raise ValueError("template palette must match the default palette keys")
    for key, value in result["palette"].items():
        if value not in PALETTE_NAMES:
            raise ValueError(f"unsupported template color for {key}: {value}")
    if not isinstance(result["transitions"], list) or len(result["transitions"]) != 4:
        raise ValueError("template transitions must contain four labels")
    for value in result["transitions"]:
        _bounded_text(value, "transition label", 40)
    return result


def _centered(identifier, x, y, text, size, color):
    return _text(identifier, [x - len(text) * size * .275, y], text, size, color)


def _arrow(identifier, points, color):
    objects = [{"id": identifier, "type": "polyline", "points": points, "stroke": color, "fill": "none", "width": 2.2}]
    tip = points[-1]
    previous = points[-2]
    dx, dy = tip[0] - previous[0], tip[1] - previous[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    base = (tip[0] - ux * 18, tip[1] - uy * 18)
    perpendicular = (-uy * 7, ux * 7)
    objects.append({
        "id": f"{identifier}-head",
        "type": "polygon",
        "points": [tip, [base[0] + perpendicular[0], base[1] + perpendicular[1]], [base[0] - perpendicular[0], base[1] - perpendicular[1]]],
        "stroke": color,
        "fill": color,
        "width": 1,
    })
    return objects


def _metric(value, digits, suffix):
    return f"{value:.{digits}f}{suffix}" if value is not None else f"pending{suffix}"


def cyclic_flow_scene(report, template=None):
    template = network_template(template)
    palette = template["palette"]
    labels = template["labels"]
    telemetry = report["telemetry"]
    vividness = report["vividness"]
    accessible = report["forecast"]["measurement"]["threshold_sweep"][0]["accessible_volume"]
    detail_count = vividness["reconstructed_detail_count"]
    view_count = len(report["observed_views"])
    prediction = _metric(telemetry["mean_prediction_error_px"], 3, " px")
    spread = _metric(vividness["mean_reconstruction_spread_m"], 5, " m")
    latest_plan = report["plans"][-1] if report["plans"] else None
    path = " -> ".join(f"{view:g}" for view in latest_plan["path"]) if latest_plan else "accessible set complete"
    details = {
        "perception": ["Observe / stereo triangulation", f"{detail_count} points · {view_count} views"],
        "thinking": ["Imagine / candidate futures", f"accessible volume = {accessible}"],
        "learning": ["Remember / precision feedback", f"{prediction} · {vividness['fusion']}"],
        "action": ["Navigate / Dijkstra", path],
    }
    native = report.get("native_cognition")
    if native is not None:
        details["perception"] = [
            "Observe / stereo + SPU structure",
            f"{detail_count} pts · {native['spu_instruction_count']} ops",
        ]
        details["thinking"] = [
            "Imagine / SPU + candidate futures",
            f"AV={accessible} · H={native['texture_entropy_bits']:.2f} bits",
        ]
        details["learning"] = [
            "Memory / ISA + precision feedback",
            f"{native['execution_backend']} · {native['spu_timing_known_ratio']:.1%} timing · {vividness['fusion']}",
        ]
    objects = [
        _rectangle("background", [0, 0, 1920, 1080], "black", "black"),
        _text("title", [88, 91], template["title"], 30, palette["center"]),
        _text("subtitle", [91, 137], template["subtitle"], 18, "lightgray"),
        _text("live", [1580, 91], "LIVE EVIDENCE / CYCLIC TEMPLATE", 14, "gray"),
    ]
    for index in range(48):
        angle = math.tau * index / 48
        radius_x, radius_y = 535, 385
        color = palette[template["cycle"][index // 12]]
        objects.append(_ellipse(
            f"orbit-{index}",
            [960 + radius_x * math.cos(angle), 555 + radius_y * math.sin(angle)],
            [2.2 if index % 12 else 4, 2.2 if index % 12 else 4],
            color,
            color,
            .4,
        ))
    for index, start in enumerate(ANGLES):
        points = []
        for step in range(13):
            angle = math.radians(start + 18 + step * 54 / 12)
            points.append([960 + 490 * math.cos(angle), 555 + 330 * math.sin(angle)])
        objects.extend(_arrow(f"cycle-{index}", points, palette[template["cycle"][(index + 1) % 4]]))
    for index, capability in enumerate(template["cycle"]):
        x, y = POSITIONS[index]
        color = palette[capability]
        objects.extend([
            _line(f"spoke-{capability}", [960, 555], [x, y], color, .65),
            _rectangle(f"card-{capability}", [x - 190, y - 82, x + 190, y + 82], color, "black", 1.8),
            _line(f"accent-{capability}", [x - 175, y - 65], [x - 65, y - 65], color, 4),
            _centered(f"number-{capability}", x + 143, y - 51, f"0{index + 1}", 13, color),
            _centered(f"label-{capability}", x, y - 29, labels[capability], 25, color),
            _centered(f"detail-{capability}", x, y + 15, details[capability][0], 16, "white"),
            _centered(f"metric-{capability}", x, y + 48, details[capability][1], 15, "lightgray"),
        ])
        transition_angle = math.radians(ANGLES[index] + 45)
        transition_x = 960 + 560 * math.cos(transition_angle)
        transition_y = 555 + 350 * math.sin(transition_angle)
        objects.append(_centered(
            f"transition-{index}", transition_x, transition_y,
            template["transitions"][index], 13, color,
        ))
    objects.extend([
        _ellipse("core-outer", [960, 555], [238, 163], palette["center"], "black", 1.5),
        _ellipse("core-inner", [960, 555], [204, 132], "magenta", "black", 1.1),
        _centered("core-label", 960, 493, labels["center"], 22, palette["center"]),
        _centered("core-points", 960, 532, f"{native['spu_instruction_count']} SPU ops · {detail_count} points" if native is not None else f"{detail_count} reconstructed points", 17, "white"),
        _centered("core-provenance", 960, 565, "observed / imagined / reconstructed", 14, "lightgray"),
        _centered("vividness-label", 960, 613, labels["vividness"], 17, "magenta"),
        _centered("vividness-metrics", 960, 644, f"{native['execution_gflops']:.2f} GF/s · {prediction}" if native is not None else f"{prediction} prediction · {spread} spread", 14, "yellow"),
        _centered("footer", 960, 1006, "Geometric vividness, not emotion · explicit provenance · external actions = 0", 15, "lightgray"),
        _centered("signature", 960, 1041, "A remixable instrument for seeing, imagining, learning, and making paths.", 14, "gray"),
    ])
    scene = _scene("zoe-cyclic-field", 1920, 1080, objects, f"{template['title']} · shared perception and imagery")
    augmented = deepcopy(report)
    augmented["creative_template"] = template
    augmented["visual_layout"] = "cyclic"
    return scene, augmented
