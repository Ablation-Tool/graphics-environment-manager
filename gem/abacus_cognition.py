from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re

from .scene_utils import _ellipse, _line, _rectangle, _scene, _text


@dataclass(frozen=True)
class Rod:
    lower: int = 0
    upper: int = 0

    def __post_init__(self):
        if isinstance(self.lower, bool) or not isinstance(self.lower, int) or not 0 <= self.lower <= 4:
            raise ValueError("each rod requires 0-4 active earth beads")
        if isinstance(self.upper, bool) or not isinstance(self.upper, int) or self.upper not in {0, 1}:
            raise ValueError("each rod requires 0 or 1 active heaven bead")

    @property
    def digit(self):
        return self.lower + 5 * self.upper

    @classmethod
    def from_digit(cls, digit):
        if isinstance(digit, bool) or not isinstance(digit, int) or not 0 <= digit <= 9:
            raise ValueError("a rod digit must be an integer from 0 to 9")
        return cls(lower=digit % 5, upper=int(digit >= 5))

    def document(self):
        return {"lower": self.lower, "upper": self.upper}


class Soroban:
    def __init__(self, value=0, rod_count=16):
        if isinstance(rod_count, bool) or not isinstance(rod_count, int) or not 1 <= rod_count <= 64:
            raise ValueError("rod_count must be an integer from 1 to 64")
        self.rod_count = rod_count
        self.rods = [Rod() for _ in range(rod_count)]
        self.history = []
        self.set(value)

    def snapshot(self):
        return {"rods": [rod.document() for rod in self.rods]}

    def document(self):
        return {
            "rod_count": self.rod_count,
            "value": self.value(),
            "rods": self.snapshot()["rods"],
            "history": deepcopy(self.history),
        }

    @classmethod
    def from_snapshot(cls, snapshot, rod_count):
        result = cls(0, rod_count)
        result.restore(snapshot)
        result.history = []
        return result

    def restore(self, snapshot):
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("rods"), list) or len(snapshot["rods"]) != self.rod_count:
            raise ValueError("checkpoint must contain one bead record per rod")
        self.rods = [Rod(lower=item["lower"], upper=item["upper"]) for item in snapshot["rods"]]

    def value(self):
        return sum(rod.digit * 10**index for index, rod in enumerate(self.rods))

    def clear(self):
        before = self.snapshot()
        self.rods = [Rod() for _ in range(self.rod_count)]
        self.history.append({"operation": "clear", "before": before, "after": self.snapshot()})

    def set(self, value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value >= 10**self.rod_count:
            raise ValueError("value must be a nonnegative integer that fits the rods")
        before = self.snapshot()
        self.rods = [Rod() for _ in range(self.rod_count)]
        remaining = value
        for index in range(self.rod_count):
            self.rods[index] = Rod.from_digit(remaining % 10)
            remaining //= 10
        self.history.append({"operation": "set", "before": before, "after": self.snapshot(), "value": value})

    def compare(self, other):
        self._compatible(other)
        for index in range(self.rod_count - 1, -1, -1):
            if self.rods[index].digit < other.rods[index].digit:
                return -1
            if self.rods[index].digit > other.rods[index].digit:
                return 1
        return 0

    def _compatible(self, other):
        if not isinstance(other, Soroban) or other.rod_count != self.rod_count:
            raise ValueError("both operands must be Soroban instances with the same rod count")

    def _increment_rod(self, index):
        rod = self.rods[index]
        before = rod.document()
        digit = rod.digit
        carry = False
        if digit < 4:
            self.rods[index] = Rod(lower=rod.lower + 1, upper=rod.upper)
        elif digit == 4:
            self.rods[index] = Rod(lower=0, upper=1)
        elif digit == 5:
            self.rods[index] = Rod(lower=1, upper=1)
        elif digit < 9:
            self.rods[index] = Rod(lower=rod.lower + 1, upper=rod.upper)
        else:
            if index + 1 >= self.rod_count:
                raise OverflowError("addition exceeds the available rods")
            self.rods[index] = Rod()
            carry = True
        return {"rod": index, "before": before, "after": self.rods[index].document(), "carry": carry}

    def _decrement_rod(self, index):
        rod = self.rods[index]
        before = rod.document()
        digit = rod.digit
        borrow = False
        if digit == 0:
            if index + 1 >= self.rod_count:
                raise ValueError("subtraction would make the value negative")
            self.rods[index] = Rod.from_digit(9)
            borrow = True
        elif digit == 1:
            self.rods[index] = Rod()
        elif digit <= 4:
            self.rods[index] = Rod(lower=rod.lower - 1, upper=rod.upper)
        elif digit == 5:
            self.rods[index] = Rod(lower=4, upper=0)
        elif digit == 6:
            self.rods[index] = Rod(lower=0, upper=1)
        else:
            self.rods[index] = Rod(lower=rod.lower - 1, upper=rod.upper)
        return {"rod": index, "before": before, "after": self.rods[index].document(), "borrow": borrow}

    def _add_state(self, other):
        self._compatible(other)
        moves = []
        for index, rod in enumerate(other.rods):
            for _ in range(rod.digit):
                current = index
                while True:
                    move = self._increment_rod(current)
                    moves.append(move)
                    if not move["carry"]:
                        break
                    current += 1
        return moves

    def _subtract_state(self, other):
        self._compatible(other)
        moves = []
        for index, rod in enumerate(other.rods):
            for _ in range(rod.digit):
                current = index
                while True:
                    move = self._decrement_rod(current)
                    moves.append(move)
                    if not move["borrow"]:
                        break
                    current += 1
        return moves

    def add(self, other):
        self._compatible(other)
        before = self.snapshot()
        work = deepcopy(self)
        moves = work._add_state(other)
        self.rods = work.rods
        self.history.append({"operation": "add", "operand": other.value(), "before": before, "after": self.snapshot(), "moves": moves})
        return self

    def subtract(self, other):
        self._compatible(other)
        if self.compare(other) < 0:
            raise ValueError("subtraction would make the value negative")
        before = self.snapshot()
        work = deepcopy(self)
        moves = work._subtract_state(other)
        self.rods = work.rods
        self.history.append({"operation": "subtract", "operand": other.value(), "before": before, "after": self.snapshot(), "moves": moves})
        return self

    def _shifted(self, places):
        if isinstance(places, bool) or not isinstance(places, int) or places < 0:
            raise ValueError("shift places must be a nonnegative integer")
        result = Soroban(0, self.rod_count)
        for index, rod in enumerate(self.rods):
            target = index + places
            if rod.digit and target >= self.rod_count:
                raise OverflowError("place-value shift exceeds the available rods")
            if target < self.rod_count:
                result.rods[target] = rod
        return result

    def shift_left(self, places):
        before = self.snapshot()
        shifted = self._shifted(places)
        self.rods = shifted.rods
        self.history.append({"operation": "shift_left", "places": places, "before": before, "after": self.snapshot()})
        return self

    def multiply(self, other):
        self._compatible(other)
        before = self.snapshot()
        work = Soroban(0, self.rod_count)
        moves = []
        for place, rod in enumerate(other.rods):
            addend = self._shifted(place) if rod.digit else None
            for _ in range(rod.digit):
                moves.extend(work._add_state(addend))
        self.rods = work.rods
        self.history.append({"operation": "multiply", "operand": other.value(), "before": before, "after": self.snapshot(), "moves": moves})
        return self

    def divide(self, other):
        self._compatible(other)
        if all(rod.digit == 0 for rod in other.rods):
            raise ValueError("division by zero is undefined")
        before = self.snapshot()
        remainder = deepcopy(self)
        quotient = Soroban(0, self.rod_count)
        moves = []
        for place in range(self.rod_count - 1, -1, -1):
            try:
                shifted = other._shifted(place)
            except OverflowError:
                continue
            digit = 0
            while remainder.compare(shifted) >= 0 and digit < 10:
                moves.extend(remainder._subtract_state(shifted))
                digit += 1
            if digit == 10:
                raise ValueError("long division did not terminate at a rod digit")
            quotient.rods[place] = Rod.from_digit(digit)
        self.rods = quotient.rods
        self.history.append({
            "operation": "divide", "operand": other.value(), "before": before,
            "after": self.snapshot(), "remainder": remainder.snapshot(), "moves": moves,
        })
        return remainder

    def undo(self):
        if not self.history:
            raise ValueError("no operation is available to undo")
        last = self.history[-1]
        before = self.snapshot()
        self.restore(last["before"])
        self.history.append({"operation": "undo", "undone": last["operation"], "before": before, "after": self.snapshot()})
        return self


def abacus_report(initial, operations, rod_count=16):
    engine = Soroban(initial, rod_count)
    initial_document = engine.document()
    for operation, operand in operations:
        if operation == "undo":
            if operand is not None:
                raise ValueError("undo does not take an operand")
            engine.undo()
            continue
        if operation not in {"add", "subtract", "multiply", "divide"}:
            raise ValueError("operation must be add, subtract, multiply, divide, or undo")
        other = Soroban(operand, rod_count)
        if operation == "add":
            engine.add(other)
        elif operation == "subtract":
            engine.subtract(other)
        elif operation == "multiply":
            engine.multiply(other)
        else:
            engine.divide(other)
    return {
        "schema_version": 1,
        "instrument": "Zoe physical-rule soroban working memory",
        "initial": initial_document,
        "final": engine.document(),
        "operations": deepcopy(engine.history),
        "representation": "rod[0] is ones; lower active earth beads are 1 each and the active heaven bead is 5",
        "arithmetic": "direct bead moves, carries, borrows, place-shifted addition, and repeated-subtraction long division",
        "integer_decode_used_for_addition_or_subtraction": False,
        "reversible": True,
        "physical_hardware_actuated": False,
        "external_actions": 0,
    }


def expression_report(expression, rod_count=16, undo=False):
    match = re.fullmatch(r"\s*(\d+)\s*([+\-*/])\s*(\d+)\s*", expression or "")
    if not match:
        raise ValueError("abacus expression must be a nonnegative integer, an operator, and another integer")
    initial, operator, operand = match.groups()
    operation = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide"}[operator]
    operations = [(operation, int(operand))]
    if undo:
        operations.append(("undo", None))
    report = abacus_report(int(initial), operations, rod_count)
    report["expression"] = expression
    return report


def _snapshot_value(snapshot):
    return sum((rod["lower"] + 5 * rod["upper"]) * 10**index for index, rod in enumerate(snapshot["rods"]))


def abacus_scene(report):
    final = report["final"]
    rods = final["rods"]
    highest = max((index for index, rod in enumerate(rods) if rod["lower"] + rod["upper"] > 0), default=0)
    visible = max(3, min(12, highest + 1))
    spacing = min(180, 1360 // visible)
    objects = [
        _rectangle("background", [0, 0, 1600, 1000], "black", "black"),
        _text("title", [60, 55], "ZOE / SOROBAN WORKING MEMORY", 28, "cyan"),
        _text("subtitle", [60, 92], f"{report['initial']['value']} -> {final['value']} · exact bead moves · reversible checkpoints", 17, "lightgray"),
        _text("legend", [60, 130], "Earth beads = 1 · heaven bead = 5 · active beads touch the reckoning bar", 15, "gray"),
        _text("visible-rods", [1250, 130], f"{visible} of {len(rods)} rods", 14, "gray"),
        _rectangle("frame", [50, 160, 1540, 680], "yellow", "black", 2),
        _line("reckoning-bar", [55, 365], [1535, 365], "white", 3),
    ]
    for display_index, rod_index in enumerate(range(visible - 1, -1, -1)):
        rod = rods[rod_index]
        x = 800 - ((visible - 1) * spacing) / 2 + display_index * spacing
        objects.append(_line(f"rod-{rod_index}", [x, 180], [x, 650], "gray", 2))
        heaven_y = 325 if rod["upper"] else 215
        objects.append(_ellipse(f"heaven-{rod_index}", [x, heaven_y], [18, 13], "magenta" if rod["upper"] else "gray", "magenta" if rod["upper"] else "black", 2))
        for bead in range(4):
            y = 395 + bead * 48 if bead < rod["lower"] else 610 - bead * 48
            objects.append(_ellipse(f"earth-{rod_index}-{bead}", [x, y], [18, 13], "cyan" if bead < rod["lower"] else "gray", "cyan" if bead < rod["lower"] else "black", 2))
        objects.extend([
            _text(f"digit-{rod_index}", [x - 12, 704], str(rod["lower"] + 5 * rod["upper"]), 21, "white"),
            _text(f"place-{rod_index}", [x - 28, 730], f"10^{rod_index}", 12, "gray"),
        ])
    objects.append(_text("operation-title", [60, 790], "REVERSIBLE OPERATION HISTORY", 17, "yellow"))
    for index, operation in enumerate(report["operations"][-4:]):
        before = _snapshot_value(operation["before"])
        after = _snapshot_value(operation["after"])
        label = f"{operation['operation']}: {before} -> {after}"
        if "remainder" in operation:
            label += f" · remainder {_snapshot_value(operation['remainder'])}"
        objects.append(_text(f"operation-{index}", [60, 825 + index * 31], label, 15, "lightgray"))
    objects.extend([
        _text("checks", [60, 958], "Direct bead transitions · no integer decode in add/subtract · physical hardware actuated = false", 14, "green"),
    ])
    scene = _scene("zoe-soroban", 1600, 1000, objects, "Zoe physical-rule soroban working memory")
    return scene, report
