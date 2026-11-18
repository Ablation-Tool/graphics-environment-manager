from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from gem.cli import main as gem_main
from gem.saliency_cognition import (
    _gabor_pyramids,
    _gaussian_pyramid,
    attention_scanpath,
    competitive_normalize,
    load_rgb,
    prototype_image,
    rgb_values,
    saliency_report,
)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class CompetitiveMapCase(unittest.TestCase):
    def test_peak_competition_and_empty_maps(self):
        values = np.zeros((5, 5))
        values[1, 1] = 8
        values[4, 4] = 4
        normalized, metadata = competitive_normalize(values)
        self.assertEqual(metadata["local_maximum_count"], 2)
        self.assertEqual(metadata["other_local_maximum_mean"], 4)
        self.assertEqual(metadata["weight"], .25)
        self.assertEqual(normalized[1, 1], .25)
        self.assertEqual(normalized[4, 4], .125)
        self.assertTrue(np.all(competitive_normalize(np.zeros((4, 4)))[0] == 0))
        self.assertTrue(np.all(competitive_normalize(np.ones((4, 4)))[0] == 0))
        with self.assertRaises(ValueError):
            competitive_normalize(np.asarray([[0, -1], [0, 0]]))
        with self.assertRaises(ValueError):
            competitive_normalize(np.asarray([[0, math.nan], [0, 0]]))

    def test_nine_scale_pyramid_and_quadrature_orientation(self):
        constant = _gaussian_pyramid(np.ones((64, 64)))
        self.assertEqual([level.shape for level in constant], [(max(1, 64 // (2**level)), max(1, 64 // (2**level))) for level in range(9)])
        for level in constant:
            self.assertTrue(np.allclose(level, 1))
        yy, xx = np.mgrid[:64, :64]
        vertical_bars = np.sin(math.tau * xx / 7)
        responses = _gabor_pyramids([vertical_bars])
        self.assertGreater(responses[90][0][32, 32], 1)
        self.assertLess(responses[0][0][32, 32], responses[90][0][32, 32] / 40)
        self.assertTrue(all(np.allclose(levels[0], 0) for levels in _gabor_pyramids([np.ones((16, 16))]).values()))


class AttentionCase(unittest.TestCase):
    def test_two_popouts_inhibition_and_exact_navigation(self):
        report = saliency_report(prototype_image())
        self.assertEqual(report["feature_map_counts"], {"intensity": 6, "color": 12, "orientation": 24, "total": 42})
        self.assertEqual(len(report["feature_maps"]), 42)
        self.assertEqual(np.asarray(report["saliency_map"]).shape, (4, 4))
        self.assertTrue(np.all(np.asarray(report["saliency_map"]) >= 0))
        self.assertFalse(report["attention_mechanism"]["continuous_neural_dynamics_simulated"])
        self.assertFalse(report["attention_mechanism"]["object_recognition_performed"])
        first, second = report["scanpath"][:2]
        self.assertTrue(40 <= first["source_xy"][0] <= 55 and 8 <= first["source_xy"][1] <= 23)
        self.assertTrue(8 <= second["source_xy"][0] <= 23 and 40 <= second["source_xy"][1] <= 55)
        self.assertGreater(first["saliency"], second["saliency"])
        visited = set()
        previous = None
        for focus in report["scanpath"]:
            position = tuple(focus["map_xy"])
            self.assertNotIn(position, visited)
            visited.add(position)
            if previous is not None:
                navigation = focus["navigation"]
                self.assertEqual(navigation["map_path"][0], list(previous))
                self.assertEqual(navigation["map_path"][-1], list(position))
                self.assertGreater(navigation["cost"], 0)
            previous = position

    def test_direct_attention_order_and_no_signal(self):
        saliency = np.zeros((16, 16))
        saliency[2, 2] = .9
        saliency[12, 12] = .5
        scanpath = attention_scanpath(saliency, (64, 64), steps=3)
        self.assertEqual([item["map_xy"] for item in scanpath], [[2, 2], [12, 12]])
        self.assertEqual(scanpath[0]["source_xy"], [32, 32])
        self.assertEqual(scanpath[1]["source_xy"], [63, 63])
        self.assertEqual(saliency_report(np.zeros((32, 32, 3)))["scanpath"], [])
        with self.assertRaises(ValueError):
            attention_scanpath(saliency, (64, 64), steps=True)
        with self.assertRaises(ValueError):
            rgb_values(np.zeros((15, 16, 3)))

    @unittest.skipUnless(HAS_PIL, "image-file tests require Pillow")
    def test_rgb_file_provenance_and_complete_cognition_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "popout.png"
            Image.fromarray(np.rint(prototype_image() * 255).astype(np.uint8)).save(image_path)
            image, source = load_rgb(image_path)
            self.assertEqual(image.shape, (64, 64, 3))
            self.assertEqual(source["original_shape"], [64, 64])
            self.assertEqual(len(source["sha256"]), 64)
            self.assertFalse(source["live_camera"])
            output = root / "cognition.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gem_main([
                    "cognition", "--image", str(image_path), "--foci", "2", "--output", str(output),
                ]), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["saliency"]["feature_map_counts"]["total"], 42)
            self.assertEqual(len(report["saliency"]["scanpath"]), 2)
            self.assertEqual(report["saliency"]["source"]["path"], str(image_path))
            self.assertEqual(report["native_cognition"]["saliency_feature_maps"], 42)
            self.assertEqual(report["native_cognition"]["saliency_attended_count"], 2)
            self.assertFalse(report["actual_camera_used"])
            self.assertEqual(report["external_actions"], 0)


if __name__ == "__main__":
    unittest.main()
