from __future__ import annotations

import json
import unittest

from gem.abacus_cognition import Soroban
from gem.ecology_cognition import ecology_report, ecology_scene, observation_at
from gem.geometry import verify
from gem.runner import verify_vdi


class EcologyCase(unittest.TestCase):
    def test_sensorimotor_history_and_gain_updates(self):
        report = ecology_report()
        history = report["history"]
        self.assertEqual(len(history), 8)
        self.assertEqual([item["position_after"] for item in history], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual([item["gain_after"] for item in history], [0, 1, 1, 0, 1, 0, 0, 0])
        for item in history:
            self.assertEqual(item["actual_energy"], observation_at(item["position_after"], item["step"])["energy"])
            self.assertEqual(item["prediction_error"], abs(item["predicted_energy"] - item["actual_energy"]))
            self.assertEqual(item["after"]["position"], item["position_after"])
            self.assertEqual(item["after"]["cycles"], item["step"])
        self.assertTrue(report["checks"]["actual_prediction_error_used"])
        self.assertTrue(report["checks"]["gain_updated"])
        self.assertTrue(report["checks"]["action_changes_later_perception"])
        self.assertFalse(report["checks"]["biological_calibration_performed"])
        self.assertFalse(report["physical_hardware_actuated"])
        self.assertEqual(report["external_actions"], 0)

    def test_prediction_error_changes_gain_in_both_directions(self):
        history = ecology_report()["history"]
        self.assertEqual(history[0]["predicted_energy"], 4)
        self.assertEqual(history[0]["actual_energy"], 1)
        self.assertEqual(history[0]["prediction_error"], 3)
        self.assertEqual(history[1]["gain_after"], 1)
        self.assertTrue(history[1]["learning_updated"])
        self.assertTrue(any(item["gain_before"] > item["gain_after"] for item in history))

    def test_bounded_trajectory_and_checkpoint(self):
        report = ecology_report(steps=16)
        self.assertEqual(report["final"]["position"]["value"], 9)
        self.assertEqual(report["final"]["cycles"]["value"], 16)
        restored = Soroban.from_snapshot(report["checkpoint"]["energy"], 16)
        self.assertEqual(restored.value(), 5)
        self.assertTrue(report["reversible"])
        json.dumps(report, allow_nan=False)

    def test_scene_replay_and_input_validation(self):
        scene, _ = ecology_scene(ecology_report())
        self.assertTrue(verify(scene).passed, verify(scene).text())
        self.assertTrue(verify_vdi(scene).passed, verify_vdi(scene).text())
        for steps in (True, 0, 65):
            with self.assertRaises(ValueError):
                ecology_report(steps=steps)
        with self.assertRaises(ValueError):
            observation_at(-1, 0)
        with self.assertRaises(ValueError):
            observation_at(0, -1)


if __name__ == "__main__":
    unittest.main()
