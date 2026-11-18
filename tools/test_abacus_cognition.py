from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from gem.abacus_cognition import Rod, Soroban, abacus_report, abacus_scene, expression_report
from gem.cli import main as gem_main
from gem.geometry import verify
from gem.runner import verify_vdi


class BeadStateCase(unittest.TestCase):
    def test_digit_encoding_and_physical_carry_borrow(self):
        for digit in range(10):
            rod = Rod.from_digit(digit)
            self.assertEqual(rod.digit, digit)
            self.assertEqual(rod.lower, digit % 5)
            self.assertEqual(rod.upper, int(digit >= 5))
        engine = Soroban(9)
        engine.add(Soroban(1))
        self.assertEqual(engine.value(), 10)
        self.assertEqual((engine.rods[0].lower, engine.rods[0].upper), (0, 0))
        self.assertEqual((engine.rods[1].lower, engine.rods[1].upper), (1, 0))
        engine = Soroban(10)
        engine.subtract(Soroban(3))
        self.assertEqual(engine.value(), 7)
        self.assertEqual((engine.rods[0].lower, engine.rods[0].upper), (2, 1))
        self.assertEqual((engine.rods[1].lower, engine.rods[1].upper), (0, 0))

    def test_exhaustive_small_addition_and_subtraction(self):
        for left in range(100):
            for right in range(100):
                engine = Soroban(left)
                engine.add(Soroban(right))
                self.assertEqual(engine.value(), left + right, (left, right))
                if left >= right:
                    engine = Soroban(left)
                    engine.subtract(Soroban(right))
                    self.assertEqual(engine.value(), left - right, (left, right))

    def test_exhaustive_small_multiplication_and_division(self):
        for left in range(21):
            for right in range(21):
                engine = Soroban(left)
                engine.multiply(Soroban(right))
                self.assertEqual(engine.value(), left * right, (left, right))
                if right:
                    engine = Soroban(left)
                    remainder = engine.divide(Soroban(right))
                    self.assertEqual(engine.value(), left // right, (left, right))
                    self.assertEqual(remainder.value(), left % right, (left, right))

    def test_place_shift_comparison_and_overflow(self):
        engine = Soroban(23)
        engine.shift_left(2)
        self.assertEqual(engine.value(), 2300)
        self.assertEqual(engine.compare(Soroban(2301)), -1)
        self.assertEqual(engine.compare(Soroban(2299)), 1)
        self.assertEqual(engine.compare(Soroban(2300)), 0)
        with self.assertRaises(OverflowError):
            engine.shift_left(15)
        self.assertEqual(engine.value(), 2300)
        engine = Soroban(9, rod_count=1)
        with self.assertRaises(OverflowError):
            engine.add(Soroban(1, rod_count=1))
        self.assertEqual(engine.value(), 9)
        engine = Soroban(99, rod_count=2)
        with self.assertRaises(OverflowError):
            engine.multiply(Soroban(99, rod_count=2))
        self.assertEqual(engine.value(), 99)

    def test_negative_subtraction_and_zero_division_are_rejected(self):
        engine = Soroban(2)
        with self.assertRaises(ValueError):
            engine.subtract(Soroban(3))
        self.assertEqual(engine.value(), 2)
        with self.assertRaises(ValueError):
            engine.divide(Soroban(0))
        self.assertEqual(engine.value(), 2)

    def test_undo_and_checkpoint_validation(self):
        engine = Soroban(538)
        engine.add(Soroban(279))
        self.assertEqual(engine.value(), 817)
        engine.undo()
        self.assertEqual(engine.value(), 538)
        engine.multiply(Soroban(4))
        self.assertEqual(engine.value(), 2152)
        engine.undo()
        self.assertEqual(engine.value(), 538)
        with self.assertRaises(ValueError):
            engine.restore({"rods": [{"lower": 5, "upper": 0}] * 16})
        with self.assertRaises(ValueError):
            Rod(lower=5)
        with self.assertRaises(ValueError):
            Soroban(-1)
        with self.assertRaises(ValueError):
            Soroban(True)

    def test_expression_chain_and_scene_replay(self):
        report = expression_report("538+279")
        self.assertEqual(report["final"]["value"], 817)
        self.assertFalse(report["integer_decode_used_for_addition_or_subtraction"])
        self.assertFalse(report["physical_hardware_actuated"])
        scene, _ = abacus_scene(report)
        self.assertTrue(verify(scene).passed, verify(scene).text())
        self.assertTrue(verify_vdi(scene).passed, verify_vdi(scene).text())
        json.dumps(report, allow_nan=False)

    def test_cli_export_undo_and_shared_cognition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "abacus.json"
            svg = root / "abacus.svg"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gem_main(["abacus", "538", "--add", "279", "--output", str(output)]), 0)
                self.assertEqual(gem_main(["abacus", "538", "--add", "279", "--output", str(svg)]), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["final"]["value"], 817)
            self.assertIn("ZOE / SOROBAN WORKING MEMORY", svg.read_text(encoding="utf-8"))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gem_main(["abacus", "538", "--add", "279", "--output", str(output)]), 2)
            undone = root / "undone.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gem_main(["abacus", "--expression", "538+279", "--undo", "--output", str(undone)]), 0)
            self.assertEqual(json.loads(undone.read_text(encoding="utf-8"))["final"]["value"], 538)
            cognition = root / "cognition.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gem_main([
                    "cognition", "--abacus-expression", "10-3", "--ecology-steps", "2", "--output", str(cognition),
                ]), 0)
            combined = json.loads(cognition.read_text(encoding="utf-8"))
            self.assertEqual(combined["abacus"]["final"]["value"], 7)
            self.assertEqual(combined["native_cognition"]["abacus_value"], 7)
            self.assertEqual(combined["native_cognition"]["ecology_learning_updates"], 1)
            self.assertEqual(len(combined["ecology"]["history"]), 2)

    def test_complete_reversible_operation_chain(self):
        report = abacus_report(538, [("add", 279), ("subtract", 17), ("multiply", 2), ("divide", 7), ("undo", None)])
        self.assertEqual(report["final"]["value"], 1600)
        divide = next(item for item in report["operations"] if item["operation"] == "divide")
        self.assertEqual(divide["after"]["rods"][0], {"lower": 3, "upper": 1})
        self.assertEqual(divide["after"]["rods"][1], {"lower": 2, "upper": 0})
        self.assertEqual(divide["after"]["rods"][2], {"lower": 2, "upper": 0})
        self.assertEqual(divide["remainder"]["rods"][0]["lower"], 4)
        self.assertEqual(report["operations"][-1]["operation"], "undo")


if __name__ == "__main__":
    unittest.main()
