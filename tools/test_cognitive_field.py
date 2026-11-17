from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from gem.cli import main as gem_main
from gem.cognitive_field import cognition_scene, run_cognition
from gem.geometry import verify
from gem.runner import verify_vdi


class NativeCognitiveFieldCase(unittest.TestCase):
    def test_complete_field_and_visual_replay(self):
        report = run_cognition(stereo_steps=4)
        self.assertEqual(report["instrument"], "Zoe native cognitive field")
        self.assertIn("spu", report)
        self.assertIn("texture", report)
        self.assertIn("stereo", report)
        self.assertIn("execution", report)
        self.assertEqual(report["execution"]["gpu_execution"], "not_performed")
        self.assertEqual(report["spu"]["instruction_count"], 4)
        self.assertEqual(report["external_actions"], 0)
        scene, augmented = cognition_scene(report)
        self.assertTrue(verify(scene).passed, verify(scene).text())
        self.assertTrue(verify_vdi(scene).passed, verify_vdi(scene).text())
        self.assertEqual(augmented["visual_layout"], "cyclic")
        self.assertEqual(augmented["native_cognition"]["spu_instruction_count"], 4)
        objects = {item["id"]: item for item in scene.objects}
        self.assertIn("4 SPU ops", objects["core-points"]["text"])
        self.assertIn("SPU + candidate futures", objects["detail-thinking"]["text"])

    def test_cognition_cli_preserves_complete_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "cognition.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gem_main(["cognition", "--output", str(output)]), 0)
            report = json.loads(output.read_text())
            self.assertIn("spu", report)
            self.assertIn("texture", report)
            self.assertIn("stereo", report)
            self.assertEqual(report["visual_layout"], "cyclic")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gem_main(["cognition", "--output", str(output)]), 2)


if __name__ == "__main__":
    unittest.main()
