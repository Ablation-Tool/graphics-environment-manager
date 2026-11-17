from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from gem.cli import main as gem_main
from gem.cyclic_flow import DEFAULT_TEMPLATE, cyclic_flow_scene
from gem.geometry import verify
from gem.imagery import run_document
from gem.runner import verify_vdi


class CyclicFlowCase(unittest.TestCase):
    def setUp(self):
        self.report = run_document(steps=4)

    def test_symmetric_live_network_and_replay(self):
        scene, report = cyclic_flow_scene(self.report)
        self.assertTrue(verify(scene).passed, verify(scene).text())
        self.assertTrue(verify_vdi(scene).passed, verify_vdi(scene).text())
        objects = {item["id"]: item for item in scene.objects}
        north = objects["card-perception"]["bounds"]
        south = objects["card-learning"]["bounds"]
        east = objects["card-thinking"]["bounds"]
        west = objects["card-action"]["bounds"]
        self.assertEqual(north[0], south[0])
        self.assertEqual(north[2], south[2])
        self.assertEqual((north[1] + north[3] + south[1] + south[3]) / 4, 555)
        self.assertEqual(east[1], west[1])
        self.assertEqual(east[3], west[3])
        self.assertEqual((east[0] + east[2] + west[0] + west[2]) / 4, 960)
        self.assertIn("accessible volume = 4", objects["metric-thinking"]["text"])
        self.assertIn("precision", objects["metric-learning"]["text"])
        expected_path = " -> ".join(
            f"{view:g}" for view in self.report["plans"][-1]["path"]
        ) if self.report["plans"] else "accessible set complete"
        self.assertEqual(objects["metric-action"]["text"], expected_path)
        self.assertEqual(report["visual_layout"], "cyclic")
        self.assertEqual(report["external_actions"], 0)

    def test_editable_cycle_labels_and_palette(self):
        template = json.loads(json.dumps(DEFAULT_TEMPLATE))
        template["title"] = "ZOE / IRIS REMIX"
        template["cycle"] = ["action", "learning", "thinking", "perception"]
        template["labels"]["center"] = "LIVING GEOMETRY"
        template["palette"]["perception"] = "orange"
        scene, report = cyclic_flow_scene(self.report, template)
        objects = {item["id"]: item for item in scene.objects}
        self.assertEqual(objects["card-perception"]["bounds"], [295, 473, 675, 637])
        self.assertEqual(objects["card-perception"]["stroke"], "orange")
        self.assertEqual(objects["core-label"]["text"], "LIVING GEOMETRY")
        self.assertEqual(report["creative_template"]["title"], "ZOE / IRIS REMIX")
        self.assertTrue(verify(scene).passed, verify(scene).text())
        with self.assertRaisesRegex(ValueError, "cycle"):
            cyclic_flow_scene(self.report, {**template, "cycle": ["perception"]})

    def test_network_cli_and_custom_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "network.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gem_main(["imagery", "--layout", "network", "--output", str(output)]), 0)
            report = json.loads(output.read_text())
            self.assertEqual(report["visual_layout"], "cyclic")
            self.assertEqual(report["creative_template"]["cycle"][0], "perception")
            template = root / "template.json"
            custom = json.loads(json.dumps(DEFAULT_TEMPLATE))
            custom["title"] = "ZOE / CUSTOM CANVAS"
            template.write_text(json.dumps(custom), encoding="utf-8")
            svg = root / "network.svg"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gem_main([
                    "imagery", "--template", str(template), "--steps", "2", "--output", str(svg),
                ]), 0)
            self.assertIn("ZOE / CUSTOM CANVAS", svg.read_text())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gem_main(["imagery", "--layout", "network", "--output", str(output)]), 2)


if __name__ == "__main__":
    unittest.main()
