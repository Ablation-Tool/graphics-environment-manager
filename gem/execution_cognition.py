from __future__ import annotations

from dataclasses import dataclass, field
import math
import numpy as np
import shutil
import statistics
import time

from .texture_cognition import _dct_features

NVIDIA_REFERENCE = "https://moss.csc.ncsu.edu/~mueller/cluster/nvidia/"


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    backend: str
    compute_gflops: float | None = None
    memory_bandwidth_gbps: float | None = None
    stream_processors: int | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.backend not in {"cpu", "cuda", "other"}:
            raise ValueError("backend must be cpu, cuda, or other")
        for name in ("compute_gflops", "memory_bandwidth_gbps"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive when supplied")
        if self.stream_processors is not None and (isinstance(self.stream_processors, bool) or not isinstance(self.stream_processors, int) or self.stream_processors <= 0):
            raise ValueError("stream_processors must be a positive integer")


@dataclass(frozen=True)
class Workload:
    name: str
    flops: float
    bytes_transferred: float
    kind: str = "other"
    assumptions: dict = field(default_factory=dict)

    def __post_init__(self):
        for name in ("flops", "bytes_transferred"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.kind not in {"dct", "fft", "matmul", "dijkstra", "other"}:
            raise ValueError("unsupported workload kind")


def dct_workload(size, word_bytes=8):
    if isinstance(size, bool) or not isinstance(size, int) or not 2 <= size <= 512:
        raise ValueError("DCT size must be an integer from 2 to 512")
    if isinstance(word_bytes, bool) or not isinstance(word_bytes, int) or word_bytes not in {4, 8, 16}:
        raise ValueError("word_bytes must be 4, 8, or 16")
    return Workload(
        name=f"dct-{size}x{size}",
        flops=4 * size**3,
        bytes_transferred=(4 * size**3 + 2 * size**2) * word_bytes,
        kind="dct",
        assumptions={
            "flops": "4*N^3 multiply/add operations for two matrix multiplications",
            "bytes": "(4*N^3 + 2*N^2) * word_bytes; uncached elementwise reads and writes",
            "word_bytes": word_bytes,
        },
    )


def fft_workload(size, word_bytes=16):
    if isinstance(size, bool) or not isinstance(size, int) or size < 2 or size > 2**24:
        raise ValueError("FFT size must be an integer from 2 to 16777216")
    if size & (size - 1):
        raise ValueError("FFT size must be a power of two")
    if isinstance(word_bytes, bool) or not isinstance(word_bytes, int) or word_bytes not in {4, 8, 16}:
        raise ValueError("word_bytes must be 4, 8, or 16")
    return Workload(
        name=f"fft-{size}",
        flops=5 * size * math.log2(size),
        bytes_transferred=2 * size * word_bytes,
        kind="fft",
        assumptions={
            "flops": "5*N*log2(N) operations for the declared Cooley-Tukey estimate",
            "bytes": "one complex-vector read and write, word_bytes per component",
            "word_bytes": word_bytes,
        },
    )


def matmul_workload(m, n, k, word_bytes=8):
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 4096 for value in (m, n, k)):
        raise ValueError("matrix dimensions must be integers from 1 to 4096")
    if isinstance(word_bytes, bool) or not isinstance(word_bytes, int) or word_bytes not in {4, 8, 16}:
        raise ValueError("word_bytes must be 4, 8, or 16")
    return Workload(
        name=f"matmul-{m}x{n}x{k}",
        flops=2 * m * n * k,
        bytes_transferred=(m * k + k * n + m * n) * word_bytes,
        kind="matmul",
        assumptions={
            "flops": "2*M*N*K multiply/add operations",
            "bytes": "one read of each input matrix and one output write",
            "word_bytes": word_bytes,
        },
    )


def roofline(workload, device):
    compute_seconds = None if device.compute_gflops is None else workload.flops / (device.compute_gflops * 1e9)
    memory_seconds = None if device.memory_bandwidth_gbps is None else workload.bytes_transferred / (device.memory_bandwidth_gbps * 1e9)
    candidates = [value for value in (compute_seconds, memory_seconds) if value is not None]
    lower_bound = max(candidates) if candidates else None
    if compute_seconds is None and memory_seconds is None:
        limiting = "unknown"
    elif compute_seconds is not None and memory_seconds is not None:
        limiting = "compute" if compute_seconds > memory_seconds else "memory"
    elif lower_bound == compute_seconds:
        limiting = "compute"
    else:
        limiting = "memory"
    return {
        "device": device.name,
        "backend": device.backend,
        "compute_seconds": compute_seconds,
        "memory_seconds": memory_seconds,
        "lower_bound_seconds": lower_bound,
        "limiting_factor": limiting,
        "arithmetic_intensity_flops_per_byte": workload.flops / workload.bytes_transferred if workload.bytes_transferred else math.inf,
        "complete": compute_seconds is not None and memory_seconds is not None,
        "stream_processors": device.stream_processors,
        "metadata": dict(device.metadata),
    }


def select_execution(workload, devices):
    if workload.kind == "dijkstra":
        return {
            "selected_backend": "cpu",
            "reason": "exact priority-queue Dijkstra is retained on the CPU path; no frontier-based replacement is claimed",
            "candidates": [roofline(workload, device) for device in devices],
        }
    candidates = [roofline(workload, device) for device in devices]
    complete = [candidate for candidate in candidates if candidate["complete"]]
    if not complete:
        return {
            "selected_backend": "cpu",
            "reason": "no complete CPU/GPU roofline estimate is available; retaining the measured CPU path without claiming GPU execution",
            "candidates": candidates,
        }
    selected = min(complete, key=lambda candidate: candidate["lower_bound_seconds"])
    return {
        "selected_backend": selected["backend"],
        "selected_device": selected["device"],
        "reason": "minimum complete lower bound among declared device profiles; this is an estimate, not a hardware result",
        "candidates": candidates,
    }


def tool_availability():
    return {
        "nvidia_smi_present": shutil.which("nvidia-smi") is not None,
        "nvcc_present": shutil.which("nvcc") is not None,
        "scope": "tool presence only; not proof of a usable NVIDIA device or driver",
    }


def nvidia_profile(name, stream_processors, memory_bandwidth_gbps, compute_gflops=None):
    return DeviceProfile(
        name=name,
        backend="cuda",
        compute_gflops=compute_gflops,
        memory_bandwidth_gbps=memory_bandwidth_gbps,
        stream_processors=stream_processors,
        metadata={"source": NVIDIA_REFERENCE, "availability": "reference profile only; not detected hardware"},
    )


def default_devices():
    return [
        nvidia_profile("Tesla K40c Kepler", 2880, 288),
        nvidia_profile("Tesla K20c Kepler", 2496, 200),
        nvidia_profile("GTX 480 Fermi", 480, 177),
    ]


def benchmark_dct(histogram, repeat=3, devices=None):
    if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 16:
        raise ValueError("benchmark repeat must be an integer from 1 to 16")
    histogram = np.asarray(histogram, dtype=np.int64)
    size = histogram.shape[0]
    workload = dct_workload(size)
    timings = []
    for _ in range(repeat):
        started = time.perf_counter_ns()
        features = _dct_features(histogram)
        timings.append(time.perf_counter_ns() - started)
    median_ns = statistics.median(timings)
    median_seconds = median_ns / 1e9
    achieved_gflops = workload.flops / median_seconds / 1e9
    achieved_bandwidth = workload.bytes_transferred / median_seconds / 1e9
    cpu = DeviceProfile(
        name="measured CPU",
        backend="cpu",
        compute_gflops=achieved_gflops,
        memory_bandwidth_gbps=achieved_bandwidth,
        metadata={"measurement": "median _dct_features runtime"},
    )
    profiles = [cpu, *(default_devices() if devices is None else devices)]
    selection = select_execution(workload, profiles)
    return {
        "model": "roofline lower bound with declared workload assumptions",
        "workload": {
            "name": workload.name,
            "kind": workload.kind,
            "flops": workload.flops,
            "bytes_transferred": workload.bytes_transferred,
            "assumptions": workload.assumptions,
        },
        "cpu_evidence": {
            "repeat": repeat,
            "timings_ns": timings,
            "median_ns": median_ns,
            "feature_count": len(features),
            "achieved_compute_gflops": achieved_gflops,
            "achieved_memory_bandwidth_gbps": achieved_bandwidth,
            "validation": "measured on the current CPU",
        },
        "availability": tool_availability(),
        "selection": selection,
        "gpu_execution": "not_performed",
        "scope": "CPU measurement and declared estimates only; NVIDIA reference profiles do not establish hardware availability or kernel latency",
    }
