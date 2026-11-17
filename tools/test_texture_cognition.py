from __future__ import annotations

import unittest

import numpy as np

from gem.texture_cognition import skeletonize_volume, texture_descriptor


class TextureCase(unittest.TestCase):
    def test_constant_texture_and_seed_handling(self):
        report = texture_descriptor(np.ones((2, 2), dtype=float))
        self.assertEqual(report["costs"], [[0.0, 0.0], [0.0, 0.0]])
        self.assertEqual(report["histogram_counts"], 3)
        self.assertAlmostEqual(report["histogram_entropy_bits"], .9182958340544896)
        self.assertEqual(report["ndc_mean"], 0)
        self.assertGreater(report["nln_mean"], 0)
        self.assertEqual(report["feature_count"], 400)
        self.assertEqual(len(report["feature_vector"]), 400)
        self.assertEqual(report["seed_handling"], "excluded because L1 is zero")

    def test_gradient_texture_has_nonzero_cost(self):
        report = texture_descriptor(np.asarray([[0, 0], [0, 255]], dtype=float))
        self.assertEqual(report["histogram_counts"], 3)
        self.assertGreater(report["ndc_max"], 0)
        self.assertGreater(report["histogram_entropy_bits"], 0)

    def test_volumetric_centerline_and_cycle_policy(self):
        mask = np.ones((1, 1, 4), dtype=bool)
        distance = np.ones((1, 1, 4), dtype=float)
        report = skeletonize_volume(mask, distance, (0, 0, 0))
        self.assertEqual(report["centerline"], [(0, 0, 0), (0, 0, 1), (0, 0, 2), (0, 0, 3)])
        self.assertEqual(report["max_distance_from_source"], 3)
        self.assertEqual(len(report["symbolic_edges"]), 3)
        self.assertIn("remains cyclic", report["cycle_policy"])


if __name__ == "__main__":
    unittest.main()
