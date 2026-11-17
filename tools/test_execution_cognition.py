from __future__ import annotations

import unittest

import numpy as np

from gem.execution_cognition import (
    DeviceProfile,
    Workload,
    benchmark_dct,
    dct_workload,
    fft_workload,
    matmul_workload,
    roofline,
    select_execution,
)


class RooflineCase(unittest.TestCase):
    def test_roofline_bound_and_limiting_factor(self):
        workload = Workload("unit", flops=1e9, bytes_transferred=1e9, kind="other")
        device = DeviceProfile("test", "cuda", compute_gflops=100, memory_bandwidth_gbps=50)
        report = roofline(workload, device)
        self.assertAlmostEqual(report["compute_seconds"], .01)
        self.assertAlmostEqual(report["memory_seconds"], .02)
        self.assertAlmostEqual(report["lower_bound_seconds"], .02)
        self.assertEqual(report["limiting_factor"], "memory")
        self.assertTrue(report["complete"])

    def test_incomplete_gpu_data_does_not_claim_execution(self):
        workload = Workload("unit", flops=1e9, bytes_transferred=1e9, kind="other")
        device = DeviceProfile("reference-only", "cuda", memory_bandwidth_gbps=50)
        selection = select_execution(workload, [device])
        self.assertEqual(selection["selected_backend"], "cpu")
        self.assertIn("no complete", selection["reason"])
        self.assertFalse(selection["candidates"][0]["complete"])

    def test_dijkstra_stays_on_cpu_even_with_a_faster_gpu_profile(self):
        workload = Workload("graph", flops=1e9, bytes_transferred=1e9, kind="dijkstra")
        gpu = DeviceProfile("fast-gpu", "cuda", compute_gflops=1e9, memory_bandwidth_gbps=1e9)
        cpu = DeviceProfile("slow-cpu", "cpu", compute_gflops=1, memory_bandwidth_gbps=1)
        selection = select_execution(workload, [gpu, cpu])
        self.assertEqual(selection["selected_backend"], "cpu")
        self.assertIn("exact priority-queue", selection["reason"])

    def test_declared_workload_models(self):
        dct = dct_workload(256)
        self.assertEqual(dct.flops, 67_108_864)
        self.assertEqual(dct.bytes_transferred, 537_919_488)
        fft = fft_workload(1024)
        self.assertEqual(fft.flops, 51_200)
        self.assertEqual(fft.bytes_transferred, 32_768)
        matmul = matmul_workload(2, 3, 4)
        self.assertEqual(matmul.flops, 48)
        self.assertEqual(matmul.bytes_transferred, 208)

    def test_measured_dct_evidence_and_selection(self):
        histogram = np.zeros((4, 4), dtype=np.int64)
        histogram[0, 0] = 1
        report = benchmark_dct(histogram, repeat=2)
        self.assertEqual(report["workload"]["kind"], "dct")
        self.assertEqual(report["cpu_evidence"]["repeat"], 2)
        self.assertEqual(report["cpu_evidence"]["feature_count"], 16)
        self.assertGreater(report["cpu_evidence"]["achieved_compute_gflops"], 0)
        self.assertGreater(report["cpu_evidence"]["achieved_memory_bandwidth_gbps"], 0)
        self.assertEqual(report["cpu_evidence"]["validation"], "measured on the current CPU")
        self.assertEqual(report["gpu_execution"], "not_performed")
        self.assertIn("selection", report)


if __name__ == "__main__":
    unittest.main()
