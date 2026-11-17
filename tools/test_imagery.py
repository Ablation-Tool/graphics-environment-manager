from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from gem.cli import main as gem_main
from gem.geometry import verify
from gem.imagery import (
    SharedImagery,
    default_points,
    dijkstra,
    imagery_scene,
    project_stereo,
    run_document,
)
from gem.runner import verify_vdi


class DijkstraCase(unittest.TestCase):
    def test_minimum_cost_path_and_validation(self):
        result = dijkstra(
            [0, 1, 2, 3],
            {
                (0, 3): 10, (0, 1): 2, (1, 2): 2, (2, 3): 2,
                (3, 0): 10, (1, 0): 2, (2, 1): 2, (3, 2): 2,
            },
            0,
            3,
        )
        self.assertEqual(result, {"path": [0, 1, 2, 3], "cost": 6})
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            dijkstra([0, 1], {(0, 1): -1}, 0, 1)
        with self.assertRaisesRegex(ValueError, "no path"):
            dijkstra([0, 1], {}, 0, 1)


class SharedImageryCase(unittest.TestCase):
    def test_stereo_reconstruction_imagery_and_provenance(self):
        names, positions = default_points()
        engine = SharedImagery([0, 15, 30])
        first = engine.observe(0, project_stereo(names, positions, 0, engine.camera))
        self.assertIsNone(first["predicted"])
        self.assertEqual(first["observation_provenance"], "observed")
        self.assertEqual(first["latent_provenance"], "reconstructed")
        second = engine.observe(30, project_stereo(names, positions, 30, engine.camera))
        self.assertEqual(second["prediction_provenance"], "imagined")
        self.assertIsNotNone(second["prediction_error_px"])
        self.assertGreaterEqual(second["prediction_error_px"], 0)
        self.assertNotEqual(second["predicted"], second["actual"])
        self.assertEqual(len(engine.latent), len(names))

    def test_multiple_views_reduce_reconstruction_error(self):
        initial = run_document(steps=1)
        complete = run_document(steps=4)
        self.assertLess(
            complete["telemetry"]["mean_reconstruction_error_m"],
            initial["telemetry"]["mean_reconstruction_error_m"],
        )
        self.assertEqual(complete["forecast"]["measurement"]["threshold_sweep"][0]["accessible_volume"], 4)
        self.assertTrue(complete["forecast"]["used_for_planning"])
        self.assertIn("candidate gating only", complete["forecast"]["planning_scope"])
        self.assertEqual(complete["external_actions"], 0)
        self.assertFalse(complete["subjective_sight"])

    def test_history_changes_dijkstra_route_without_changing_target(self):
        previous = run_document(steps=2)
        self.assertEqual(previous["plans"][0]["path"], [0, 45])
        engine = SharedImagery([0, 15, 30, 45], previous=previous)
        names, positions = default_points()
        engine.observe(0, project_stereo(names, positions, 0, engine.camera))
        plan = engine.plan()
        self.assertEqual(plan["target"], 45)
        self.assertNotEqual(plan["path"], [0, 45])
        self.assertEqual(plan["path"], [0, 15, 45])
        self.assertAlmostEqual(plan["cost"], 3)

    def test_supplied_stereo_observations_and_accessible_volume(self):
        names, positions = default_points()
        views = [0, 15, 30]
        observations = {
            str(view): project_stereo(names, positions, view, SharedImagery(views).camera)
            for view in views
        }
        document = {
            "views": views,
            "observations": observations,
            "forecast": {"0": .70, "15": .20, "30": .10},
        }
        report = run_document(document, steps=2)
        self.assertIsNone(report["telemetry"]["mean_reconstruction_error_m"])
        self.assertEqual(report["forecast"]["measurement"]["threshold_sweep"][0]["accessible_volume"], 3)
        self.assertEqual(report["camera"]["actual_camera_used"], False)
        broken = {**observations, "30": [dict(observations["30"][0])]}
        broken["30"][0]["left"] = broken["30"][0]["right"]
        with self.assertRaisesRegex(ValueError, "left > right"):
            run_document({**document, "observations": broken}, steps=2)

    def test_precision_fusion_improves_the_declared_benchmark(self):
        arithmetic = run_document({"fusion": "arithmetic"}, steps=4)
        precision = run_document({"fusion": "precision"}, steps=4)
        self.assertLess(
            precision["telemetry"]["mean_reconstruction_error_m"],
            arithmetic["telemetry"]["mean_reconstruction_error_m"],
        )
        self.assertAlmostEqual(precision["telemetry"]["mean_reconstruction_error_m"], .0023056443187742374)
        self.assertEqual(precision["shared_state"]["fusion"], "precision")
        self.assertIn("not subjective", precision["vividness"]["scope"])

    def test_accessible_volume_gates_live_view_navigation(self):
        report = run_document({
            "views": [0, 15, 30, 45],
            "forecast": {"0": .70, "15": .20, "30": .09, "45": .01},
        }, steps=4)
        self.assertEqual(report["observed_views"], [0, 30, 15])
        self.assertEqual(report["forecast"]["measurement"]["threshold_sweep"][0]["accessible_volume"], 3)
        self.assertEqual(len(report["events"]), 3)
        self.assertIsNone(report["navigation"][-1]["plan"])
        self.assertNotIn(45, report["observed_views"])
        self.assertIn("not action authorization", report["planner"]["guarantee_scope"])

    def test_live_callback_streams_each_real_cycle(self):
        records = []
        report = run_document(steps=3, on_step=records.append)
        self.assertEqual(len(records), 3)
        self.assertEqual(report["navigation"], records)
        for record in records:
            self.assertEqual(record["provenance"]["observation"], "observed")
            self.assertEqual(record["provenance"]["latent"], "reconstructed")
            self.assertIn("vividness", record)
            self.assertEqual(record["external_actions"], 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(gem_main(["imagery", "--live", "--steps", "2"]), 0)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line["type"] == "navigation" for line in lines))

    def test_scene_and_cli_exports_are_replayable_and_no_overwrite(self):
        scene, report = imagery_scene(run_document())
        self.assertTrue(verify(scene).passed, verify(scene).text())
        self.assertTrue(verify_vdi(scene).passed, verify_vdi(scene).text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix in ("json", "svg", "gem"):
                output = root / f"imagery.{suffix}"
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(gem_main(["imagery", "--output", str(output)]), 0)
                self.assertGreater(output.stat().st_size, 0)
            saved = json.loads((root / "imagery.json").read_text())
            self.assertEqual(saved["instrument"], "Zoe shared perception and imagery")
            self.assertIn("OBSERVED", (root / "imagery.svg").read_text())
            self.assertIn("IMAGINED", (root / "imagery.svg").read_text())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gem_main(["imagery", "--output", str(root / "imagery.json")]), 2)
            second = root / "second.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gem_main([
                    "imagery", "--previous", str(root / "imagery.json"),
                    "--steps", "2", "--output", str(second),
                ]), 0)
            self.assertIn("transitions", json.loads(second.read_text())["telemetry"])


if __name__ == "__main__":
    unittest.main()
