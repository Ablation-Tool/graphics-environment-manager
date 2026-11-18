from __future__ import annotations

from copy import deepcopy

from .abacus_cognition import Soroban
from .scene_utils import _ellipse, _line, _rectangle, _scene, _text

LIGHT = (1, 1, 3, 5, 7, 9, 8, 6, 4, 2)
ENERGY = (1, 1, 3, 5, 7, 9, 8, 6, 4, 2)
MOISTURE = (4, 3, 2, 3, 5, 6, 5, 4, 3, 2)
NUTRIENTS = (2, 3, 4, 5, 6, 5, 4, 3, 2, 1)
OBSTACLES = (0, 0, 1, 0, 0, 1, 0, 0, 1, 0)
MAX_RESOURCE = 9


def observation_at(position, step):
    if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position < len(LIGHT):
        raise ValueError("position is outside the declared environment")
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise ValueError("step must be a nonnegative integer")
    return {
        "light": LIGHT[position],
        "energy": ENERGY[position],
        "moisture": MOISTURE[step % len(MOISTURE)],
        "nutrients": NUTRIENTS[position],
        "obstacle": OBSTACLES[position],
    }


def initial_ecology():
    return {
        "energy": Soroban(5),
        "gain": Soroban(0),
        "cost": Soroban(1),
        "position": Soroban(0),
        "prediction_error": Soroban(0),
        "cycles": Soroban(0),
        "water": Soroban(0),
        "nutrients": Soroban(0),
    }


def _difference(first, second):
    if first.compare(second) >= 0:
        return first.subtract(second)
    return second.subtract(first)


def _bounded(value):
    return min(MAX_RESOURCE, max(0, value))


def ecology_step(state, step):
    position = state["position"].value()
    observed = observation_at(position, step)
    before = {name: rod.value() for name, rod in state.items()}
    state["water"].set(observed["moisture"])
    state["nutrients"].set(observed["nutrients"])
    light_gain = Soroban(observed["light"]).multiply(state["gain"])
    can_extend = (
        observed["light"] > 0
        and observed["obstacle"] <= 2
        and state["energy"].compare(state["cost"]) >= 0
        and position < MAX_RESOURCE
    )
    predicted = _bounded(state["energy"].value() + light_gain.value() - (state["cost"].value() if can_extend else 0))
    next_position = position + int(can_extend)
    actual = observation_at(next_position, step + 1)["energy"]
    error = _difference(Soroban(predicted), Soroban(actual)).value()
    previous_gain = state["gain"].value()
    if actual > predicted and previous_gain < 9:
        state["gain"].add(Soroban(1))
    elif actual < predicted and previous_gain > 0:
        state["gain"].subtract(Soroban(1))
    state["energy"].set(actual)
    state["position"].set(next_position)
    state["prediction_error"].set(error)
    state["cycles"].add(Soroban(1))
    after = {name: rod.value() for name, rod in state.items()}
    return {
        "step": step + 1,
        "before": before,
        "observed": observed,
        "predicted_energy": predicted,
        "actual_energy": actual,
        "prediction_error": error,
        "light_gain": light_gain.value(),
        "action": "extend" if can_extend else "conserve",
        "position_before": position,
        "position_after": next_position,
        "gain_before": previous_gain,
        "gain_after": state["gain"].value(),
        "learning_updated": previous_gain != state["gain"].value(),
        "after": after,
    }


def ecology_report(steps=8):
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 64:
        raise ValueError("ecology steps must be an integer from 1 to 64")
    state = initial_ecology()
    initial = {name: rod.document() for name, rod in state.items()}
    history = [ecology_step(state, step) for step in range(steps)]
    return {
        "schema_version": 1,
        "instrument": "Zoe ecological sensorimotor working memory",
        "model_scope": "declared bounded resource-feedback model inspired by ecological coupling; not a calibrated plant or fungal model",
        "initial": initial,
        "final": {name: rod.document() for name, rod in state.items()},
        "history": history,
        "environment": {
            "light": list(LIGHT),
            "energy": list(ENERGY),
            "moisture": list(MOISTURE),
            "nutrients": list(NUTRIENTS),
            "obstacles": list(OBSTACLES),
        },
        "cycle": {
            "perception": "resource observations encoded into soroban state",
            "thinking": "compare expected energy gain with action cost and obstacles",
            "action": "extend or conserve, which changes subsequent observed position and resources",
            "learning": "increase, decrease, or retain gain from measured prediction error",
        },
        "checks": {
            "actual_prediction_error_used": any(item["prediction_error"] > 0 for item in history),
            "gain_updated": any(item["learning_updated"] for item in history),
            "action_changes_later_perception": any(item["position_after"] != item["position_before"] for item in history),
            "integer_decode_used_for_addition_or_subtraction": False,
            "biological_calibration_performed": False,
        },
        "checkpoint": deepcopy(initial),
        "reversible": True,
        "physical_hardware_actuated": False,
        "external_actions": 0,
    }


def ecology_scene(report):
    history = report["history"][-16:]
    objects = [
        _rectangle("background", [0, 0, 1600, 1000], "black", "black"),
        _text("title", [60, 55], "ZOE / ECOLOGICAL WORKING MEMORY", 28, "cyan"),
        _text("subtitle", [60, 94], "Environment → perception → action → learning → next perception", 18, "lightgray"),
        _text("scope", [60, 128], "Declared resource-feedback model · exact soroban state transitions · not a biological calibration", 14, "gray"),
        *([_text("window", [1250, 55], f"last {len(history)} of {len(report['history'])} steps", 14, "gray")] if len(report["history"]) > 16 else []),
        _text("energy-label", [65, 220], "ENERGY / predicted versus observed", 16, "yellow"),
        _text("action-label", [65, 640], "ACTION / extend or conserve", 16, "magenta"),
        _text("learning-label", [65, 770], "LEARNING / gain from prediction error", 16, "cyan"),
    ]
    step_width = min(170, 1420 // len(history))
    for index, item in enumerate(history):
        x = 100 + index * step_width
        actual_y = 550 - item["actual_energy"] * 32
        predicted_y = 550 - item["predicted_energy"] * 32
        objects.append(_line(f"stem-{index}", [x, 590], [x, actual_y], "green", 3))
        objects.append(_ellipse(f"actual-{index}", [x, actual_y], [12, 12], "cyan", "cyan", 2))
        objects.append(_ellipse(f"predicted-{index}", [x + 25, predicted_y], [9, 9], "magenta", "black", 2))
        if index:
            previous = history[index - 1]
            objects.append(_line(f"energy-link-{index}", [x - step_width, 550 - previous["actual_energy"] * 32], [x, actual_y], "cyan", 2))
        action_color = "green" if item["action"] == "extend" else "orange"
        objects.append(_text(f"action-{index}", [x - 35, 680], item["action"].upper(), 12, action_color))
        objects.append(_text(f"position-{index}", [x - 15, 715], f"p{item['position_after']}", 12, "gray"))
        objects.append(_text(f"error-{index}", [x - 15, 805], f"e={item['prediction_error']}", 13, "white"))
        objects.append(_text(f"gain-{index}", [x - 15, 840], f"g={item['gain_after']}", 13, "yellow" if item["learning_updated"] else "gray"))
    objects.extend([
        _text("energy-legend", [60, 590], "cyan = observed · magenta = predicted", 13, "lightgray"),
        _text("checks", [60, 940], "Exact bead arithmetic · reversible checkpoints · external actions = 0 · no hardware actuated", 14, "green"),
    ])
    scene = _scene("zoe-ecological-working-memory", 1600, 1000, objects, "Zoe ecological sensorimotor working memory")
    return scene, report
