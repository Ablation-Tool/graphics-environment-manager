from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

import numpy as np

from .cyclic_flow import cyclic_flow_scene
from .execution_cognition import benchmark_dct
from .imagery import run_document
from .spu_cognition import SPUExecutionField
from .texture_cognition import texture_descriptor

MAX_SPU_BYTES = 256 * 1024 * 1024
MAX_TEXTURE_BYTES = 16 * 1024 * 1024


def _load_spu(path):
    if path is None:
        return SPUExecutionField.from_words([
            (0x3050, 0x4206D803),
            (0x3054, 0x34000000),
            (0x3058, 0x24000000),
            (0x305C, 0x00000000),
        ])
    source = Path(path).expanduser().resolve(strict=True)
    if source.stat().st_size > MAX_SPU_BYTES:
        raise ValueError("SPU ELF input exceeds the 256 MiB limit")
    return SPUExecutionField.from_elf(source.read_bytes(), source=str(source))


def _texture(path, spu):
    if path is not None:
        source = Path(path).expanduser().resolve(strict=True)
        if source.stat().st_size > MAX_TEXTURE_BYTES:
            raise ValueError("texture NPZ input exceeds the 16 MiB limit")
        with np.load(source, allow_pickle=False) as artifact:
            if "image" not in artifact:
                raise ValueError("texture NPZ must contain an image array")
            return np.asarray(artifact["image"], dtype=float), str(source)
    text = spu.text
    side = math.ceil(math.sqrt(len(text)))
    values = np.zeros(side * side, dtype=np.uint8)
    values[:len(text)] = np.frombuffer(text, dtype=np.uint8)
    return values.reshape(side, side), "SPU instruction bytes reshaped as a structural texture"


def run_cognition(spu_path=None, texture_path=None, previous=None, stereo_steps=3, template=None, benchmark_repeat=3):
    spu = _load_spu(spu_path)
    spu_report = spu.report()
    image, texture_source = _texture(texture_path, spu)
    texture = texture_descriptor(image)
    texture["source"] = texture_source
    execution = benchmark_dct(texture["histogram"], repeat=benchmark_repeat)
    stereo = run_document(previous=previous, steps=stereo_steps)
    native = {
        "spu_instruction_count": spu_report["instruction_count"],
        "spu_path_cost": spu_report["execution_imagery"]["path"]["cost"],
        "spu_timing_known_ratio": spu_report["timing"]["known_ratio"],
        "texture_entropy_bits": texture["histogram_entropy_bits"],
        "texture_source": texture_source,
        "execution_backend": execution["selection"]["selected_backend"],
        "execution_gflops": execution["cpu_evidence"]["achieved_compute_gflops"],
    }
    report = {
        "schema_version": 1,
        "instrument": "Zoe native cognitive field",
        "creative_template": template,
        "native_cognition": native,
        "spu": spu_report,
        "texture": texture,
        "execution": execution,
        "stereo": stereo,
        "beowulf": {
            "scope": "declared PPE/SPE/MFC/EIB structural model, not a cluster runtime trace",
            "nodes": ["PPE", "SPE", "local_store", "MFC", "EIB", "main_memory"],
            "flow": [
                "PPE loads the SPE program into local storage",
                "PPE instructs the SPE to execute",
                "MFC transfers data between main memory and local storage",
                "SPU computes and returns results through the same structural graph",
            ],
        },
        "cognitive_cycle": {
            "perception": "real SPU bytes, structural texture, and labeled stereo observations",
            "imagery": "SPU execution path/timing projection and stereo view prediction",
            "learning": "historical prediction error and precision-weighted reconstruction",
            "action": "Dijkstra paths annotated inside the retained cyclic graph plus roofline-selected computation backends",
        },
        "vividness": {
            "spu_timing_known_ratio": native["spu_timing_known_ratio"],
            "texture_entropy_bits": native["texture_entropy_bits"],
            "execution_backend": native["execution_backend"],
            "execution_gflops": native["execution_gflops"],
            "stereo": stereo["vividness"],
            "scope": "geometric, structural, and temporal detail/stability, not emotion",
        },
        "provenance": "observed bytes and stereo measurements remain distinct from imagined schedules, textures, and Dijkstra projections",
        "summary": (
            f"{native['spu_instruction_count']} SPU instructions · "
            f"texture entropy={native['texture_entropy_bits']:.3f} bits · "
            f"{stereo['vividness']['reconstructed_detail_count']} reconstructed points · "
            f"backend={native['execution_backend']}"
        ),
        "computation_performed": True,
        "external_actions": 0,
        "executed": False,
    }
    return report


def cognition_scene(report):
    stereo = deepcopy(report["stereo"])
    stereo["native_cognition"] = report["native_cognition"]
    scene, augmented_stereo = cyclic_flow_scene(stereo, report.get("creative_template"))
    augmented = deepcopy(report)
    augmented["creative_template"] = augmented_stereo["creative_template"]
    augmented["visual_layout"] = augmented_stereo["visual_layout"]
    return scene, augmented
