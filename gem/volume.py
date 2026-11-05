from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from .events import atomic_write
from .measurement import document_sha256, measure_distribution, normalized_thresholds
from .prediction import _atomic_savez, _next_run_directory, _numpy, _sha256


def _load_npz(path, key):
    np = _numpy()
    source = Path(path).expanduser().resolve(strict=True)
    with np.load(source, allow_pickle=False) as artifact:
        if key not in artifact:
            raise ValueError(f"NPZ artifact does not contain {key!r}")
        probabilities = artifact[key]
        ids = artifact["input_ids"] if "input_ids" in artifact else np.arange(len(probabilities), dtype=np.int64)
    if ids.ndim != 1 or not len(ids):
        raise ValueError("input_ids must be a non-empty one-dimensional array")
    if not np.issubdtype(ids.dtype, np.integer) or np.any(ids < 0):
        raise ValueError("input_ids must contain nonnegative integers")
    return ids, probabilities, {
        "path": str(source),
        "key": key,
        "artifact_sha256": _sha256(source),
        "input_ids_sha256": hashlib.sha256(ids.tobytes()).hexdigest(),
    }


def write_report(report, output):
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return output


@dataclass(frozen=True)
class VolumeRun:
    path: Path
    report: dict
    evidence: dict | None


class VolumeBridge:
    def __init__(self, session=None):
        self.session = session
        self.output = session.root / "accessible-volume" if session else Path.cwd() / "accessible-volume"
        self.output.mkdir(parents=True, exist_ok=True)

    def _latest_previous(self):
        paths = sorted(self.output.glob("accessible-volume-*/probabilities.npz"), key=lambda path: path.stat().st_mtime_ns)
        return paths[-1] if paths else None

    def observe(self, source, previous=None, thresholds=None, key="probabilities", previous_key=None,
                minimum=1, maximum=4, actual_token_id=None, model_id="npz-artifact"):
        started = time.monotonic_ns()
        state = self.session.current_state() if self.session else None
        ids, probabilities, source_metadata = _load_npz(source, key)
        previous_path = Path(previous).expanduser().resolve(strict=True) if previous is not None else self._latest_previous()
        previous_values = None
        previous_metadata = None
        if previous_path is not None:
            load_key = previous_key or key if previous is not None else "probabilities"
            _previous_ids, previous_values, previous_metadata = _load_npz(previous_path, load_key)
        thresholds = normalized_thresholds(thresholds) if thresholds is not None else normalized_thresholds(
            (0.02, 0.05, 0.10, 0.15, 0.30, 0.50)
        )
        thresholds = normalized_thresholds((*thresholds, 0.02, 0.05))
        measurement = measure_distribution(
            probabilities, thresholds, previous=previous_values,
            minimum=minimum, maximum=maximum, actual_token_id=actual_token_id,
        )
        context = {
            "selected_id": state["selected_id"] if state else str(source_metadata["path"]),
            "revision": state["revision"] if state else 1,
            "context_tokens": len(ids),
            "context_truncated": False,
        }
        digest = document_sha256({
            "source": source_metadata,
            "previous": previous_metadata,
            "thresholds": thresholds,
            "minimum": minimum,
            "maximum": maximum,
            "actual_token_id": int(actual_token_id) if actual_token_id is not None else None,
            "model_id": model_id,
        })
        report = {
            **measurement,
            "model": {"id": model_id},
            "gem_context": context,
            "source": source_metadata,
            "previous_source": previous_metadata,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "elapsed_ns": time.monotonic_ns() - started,
            "input_ids_sha256": source_metadata["input_ids_sha256"],
            "run_digest": digest,
            "scope": [
                "The NPZ artifact supplies the complete distribution being measured; no embedded agent is inferred.",
                "Accessible volume describes forecast breadth, not correctness, safety, or action authorization.",
                "Advisory steering is experimental and never executes an action.",
            ],
            "executed": False,
        }
        from .steering import evaluate_advisory

        report["advisory"] = evaluate_advisory(report)
        run_path = _next_run_directory(self.output, digest)
        run_path.mkdir(parents=True, exist_ok=False)
        probability_path = run_path / "probabilities.npz"
        _atomic_savez(probability_path, ids, probabilities)
        report["probability_artifact"] = probability_path.name
        report["probability_sha256"] = _sha256(probability_path)
        report_path = run_path / "accessible-volume.json"
        atomic_write(report_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        evidence = None
        if self.session is not None:
            latest = self.session.current_state()
            if latest["selected_id"] != state["selected_id"] or latest["revision"] != state["revision"]:
                raise ValueError("selection changed during NPZ measurement; run retained without stale evidence")
            decision = next((item for item in measurement["threshold_sweep"] if item["tau"] == 0.05), measurement["threshold_sweep"][0])
            evidence = self.session.emit(
                f"evidence:accessible-volume:{digest[:24]}",
                state["selected_id"],
                "evidence",
                f"NPZ accessible volume · τ={decision['tau']}: {decision['accessible_volume']}",
                "complete_scoped",
                "tool",
                report_path.relative_to(self.session.root).as_posix(),
                f"Offline distribution measurement and advisory feedback. No action executed.\nRun: {run_path.relative_to(self.session.root)}",
                "NPZ forecast breadth and optional known-outcome scoring only; not an embedded-agent, correctness, safety, or authorization measurement",
            )
            report["measurement_event_id"] = evidence["id"]
            atomic_write(report_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return VolumeRun(run_path, report, evidence)
