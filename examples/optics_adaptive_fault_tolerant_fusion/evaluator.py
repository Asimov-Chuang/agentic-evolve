"""Adaptive fault-tolerant fusion evaluator for agentic-evolve.

This bridge reuses Frontier-Engineering's Optics benchmark setup, then runs an
instrumented copy of the evaluation loop so raw per-case artifacts are available
for agentic-evolve analyzers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

DEFAULT_CASES = 320
DEFAULT_MAX_VOLTAGE = 0.50
DEFAULT_PROGRAM_TIMEOUT_SECONDS = 300
BENCHMARK_REL = Path("benchmarks") / "Optics" / "adaptive_fault_tolerant_fusion"
EVALUATOR_REL = BENCHMARK_REL / "verification" / "evaluate.py"
WORKER_ENV = "AFTF_EVALUATOR_WORKER"


def _default_frontier_root() -> Path:
    env_root = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering"):
            if (candidate / EVALUATOR_REL).is_file():
                return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _python_has_optics(python_bin: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(python_bin), "-c", "import aotools, sklearn, matplotlib, numpy"],
            capture_output=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return completed.returncode == 0


def _current_python_has_optics() -> bool:
    try:
        import aotools  # noqa: F401
        import matplotlib  # noqa: F401
        import numpy  # noqa: F401
        import sklearn  # noqa: F401
    except Exception:
        return False
    return True


def _resolve_python_bin(frontier_root: Path) -> Path | None:
    env_python = os.environ.get("OPTICS_PYTHON", "").strip() or os.environ.get(
        "GENERAL_MEIO_PYTHON", ""
    ).strip()
    candidates: list[Path] = []
    if env_python:
        candidates.append(Path(env_python).expanduser())
    candidates.extend(
        [
            frontier_root / ".venvs" / "frontier-v1-main" / "bin" / "python",
            frontier_root / ".venvs" / "frontier-v1-main" / "Scripts" / "python.exe",
            Path(sys.executable),
        ]
    )
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)

        python_bin = candidate
        if not python_bin.exists():
            resolved = shutil.which(str(python_bin))
            if not resolved:
                continue
            python_bin = Path(resolved)

        if _python_has_optics(python_bin):
            return python_bin
    return None


def _program_timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))
    return DEFAULT_PROGRAM_TIMEOUT_SECONDS


def _delegate_to_optics_python(
    frontier_root: Path,
    program_path: Path,
    output_dir: Path,
) -> dict[str, Any] | None:
    if os.environ.get(WORKER_ENV) == "1" or _current_python_has_optics():
        return None

    python_bin = _resolve_python_bin(frontier_root)
    if python_bin is None or Path(sys.executable).resolve() == python_bin.resolve():
        return None

    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        result_path = Path(tmp.name)

    env = os.environ.copy()
    env[WORKER_ENV] = "1"
    env.setdefault("FRONTIER_ENGINEERING_ROOT", str(frontier_root))
    cmd = [
        str(python_bin),
        str(Path(__file__).resolve()),
        "--worker",
        str(program_path),
        str(output_dir),
        str(result_path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_program_timeout_seconds(),
            env=env,
        )
        if result_path.is_file():
            with open(result_path, "rb") as f:
                return pickle.load(f)
        if completed.returncode != 0:
            return _failure_result(
                "Optics worker failed: " + ((completed.stderr or completed.stdout or "").strip()[-2000:])
            )
        return _failure_result("Optics worker did not produce an evaluation result.")
    except subprocess.TimeoutExpired:
        return _failure_result(f"Evaluation timed out after {_program_timeout_seconds()} seconds.")
    except Exception as exc:
        return _failure_result(f"Failed to delegate evaluation to Optics Python: {exc}")
    finally:
        result_path.unlink(missing_ok=True)


def _load_module(module_name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_frontier_evaluator(frontier_root: Path) -> Any:
    evaluate_py = frontier_root / EVALUATOR_REL
    if not evaluate_py.is_file():
        raise FileNotFoundError(f"Frontier evaluator not found: {evaluate_py}")
    verification_dir = evaluate_py.parent
    benchmark_dir = verification_dir.parent
    for path in (verification_dir, benchmark_dir, frontier_root):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    return _load_module("_aftf_frontier_evaluator", evaluate_py)


def _to_jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except Exception:
        np = None  # type: ignore[assignment]

    if np is not None:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_jsonable(payload), f, indent=2)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _summary_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    import numpy as np

    arr = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(np.mean(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(np.max(arr)),
    }


def _failure_result(message: str, *, metrics: dict[str, Any] | None = None, raw_artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
    failure_metrics = {"valid": 0.0, "combined_score": 0.0, "failure_reason": message}
    if metrics:
        failure_metrics.update(metrics)
    payload = {
        "score": 0.0,
        "is_valid": False,
        "feedback": message,
        "metrics": failure_metrics,
        "construction": {"metrics": failure_metrics, "error_message": message},
    }
    if raw_artifacts is not None:
        payload["raw_artifacts"] = raw_artifacts
    return payload


def _write_failure_sidecars(output_dir: Path, message: str, raw_artifacts: dict[str, Any] | None = None) -> None:
    failure_metrics = {"valid": 0.0, "combined_score": 0.0, "failure_reason": message}
    raw = raw_artifacts or {
        "benchmark": "Optics/adaptive_fault_tolerant_fusion",
        "is_valid": False,
        "error_message": message,
        "partial_case_trace": [],
    }
    _write_json(output_dir / "metrics.json", failure_metrics)
    _write_json(output_dir / "artifacts.json", {"error_message": message})
    _write_json(output_dir / "raw-artifact.json", raw)
    _write_json(output_dir / "last_eval.json", {"metrics": failure_metrics, "error_message": message})


def _make_multi_wfs_observation_with_trace(rng: Any, true_slopes: Any) -> tuple[Any, dict[str, Any]]:
    import numpy as np

    n_wfs = 5
    slopes_multi = np.stack(
        [true_slopes + rng.normal(0.0, 0.01, size=true_slopes.shape) for _ in range(n_wfs)], axis=0
    )

    n_bad = 3
    bad_ids = rng.choice(n_wfs, size=n_bad, replace=False)
    fault_entries: list[dict[str, Any]] = []
    for bad_id_raw in bad_ids:
        bad_id = int(bad_id_raw)
        gain = float(rng.uniform(3.0, 5.2))
        sign_flipped = False
        if rng.random() < 0.2:
            gain *= -1.0
            sign_flipped = True

        additive_noise = rng.normal(0.0, 1.0, size=true_slopes.shape)
        slopes_multi[bad_id] = gain * slopes_multi[bad_id] + additive_noise

        spike_idx = rng.choice(true_slopes.size, size=true_slopes.size // 2, replace=False)
        spike_noise = rng.normal(0.0, 3.0, size=spike_idx.size)
        slopes_multi[bad_id, spike_idx] += spike_noise

        dropout_idx = rng.choice(true_slopes.size, size=true_slopes.size // 6, replace=False)
        slopes_multi[bad_id, dropout_idx] = 0.0

        fault_entries.append(
            {
                "sensor_id": bad_id,
                "gain": gain,
                "sign_flipped": sign_flipped,
                "additive_noise_std": float(np.std(additive_noise)),
                "spike_count": int(spike_idx.size),
                "spike_noise_std": float(np.std(spike_noise)),
                "dropout_count": int(dropout_idx.size),
            }
        )

    return slopes_multi, {"bad_ids": [int(item) for item in bad_ids.tolist()], "faults": fault_entries}


def _channel_diagnostics(slopes_multi: Any, control_model: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    model = control_model.get("anomaly_model")
    if model is None:
        return {}
    try:
        scores = np.asarray(model.decision_function(slopes_multi), dtype=np.float64)
    except Exception:
        return {}
    inlier_fraction = float(control_model.get("inlier_fraction", 0.4))
    n_keep = max(1, int(np.ceil(inlier_fraction * slopes_multi.shape[0])))
    keep_idx = np.argsort(scores)[-n_keep:]
    return {
        "anomaly_scores": [float(item) for item in scores.tolist()],
        "selected_sensor_ids": [int(item) for item in keep_idx.tolist()],
        "score_gap_best_minus_worst": float(np.max(scores) - np.min(scores)),
    }


def _example_summary(phase: Any, residual: Any, psf: Any, cmd: Any, slopes_multi: Any) -> dict[str, Any]:
    import numpy as np

    return {
        "phase_shape": list(phase.shape),
        "residual_shape": list(residual.shape),
        "psf_shape": list(psf.shape),
        "phase_rms": float(np.sqrt(np.mean(np.asarray(phase, dtype=np.float64) ** 2))),
        "residual_rms": float(np.sqrt(np.mean(np.asarray(residual, dtype=np.float64) ** 2))),
        "psf_peak": float(np.max(psf)),
        "command_preview": [float(item) for item in np.asarray(cmd, dtype=np.float64)[:12].tolist()],
        "sensor_l2_norms": [float(np.linalg.norm(row)) for row in np.asarray(slopes_multi, dtype=np.float64)],
    }


def _aggregate_case_metrics(case_trace: list[dict[str, Any]], frontier: Any) -> dict[str, Any]:
    import numpy as np

    rms_list = [float(item["rms"]) for item in case_trace]
    strehl_list = [float(item["strehl"]) for item in case_trace]
    mean_rms = float(np.mean(rms_list))
    p95_rms = float(np.quantile(rms_list, 0.95))
    worst_rms = float(np.max(rms_list))
    mean_strehl = float(np.mean(strehl_list))
    raw_cost = float(mean_rms + frontier.P95_WEIGHT * p95_rms - frontier.STREHL_WEIGHT * mean_strehl)
    u_mean_rms = frontier._utility_lower_better(
        mean_rms,
        frontier.SCORE_ANCHORS["mean_rms_good"],
        frontier.SCORE_ANCHORS["mean_rms_bad"],
    )
    u_p95_rms = frontier._utility_lower_better(
        p95_rms,
        frontier.SCORE_ANCHORS["p95_rms_good"],
        frontier.SCORE_ANCHORS["p95_rms_bad"],
    )
    u_strehl = frontier._utility_higher_better(
        mean_strehl,
        frontier.SCORE_ANCHORS["strehl_good"],
        frontier.SCORE_ANCHORS["strehl_bad"],
    )
    score_01 = float(
        frontier.SCORE_WEIGHTS["mean_rms"] * u_mean_rms
        + frontier.SCORE_WEIGHTS["p95_rms"] * u_p95_rms
        + frontier.SCORE_WEIGHTS["strehl"] * u_strehl
    )
    return {
        "mean_rms": mean_rms,
        "p95_rms": p95_rms,
        "worst_rms": worst_rms,
        "mean_strehl": mean_strehl,
        "raw_cost_lower_is_better": raw_cost,
        "score_0_to_1_higher_is_better": score_01,
        "score_percent": 100.0 * score_01,
        "utility_mean_rms": float(u_mean_rms),
        "utility_p95_rms": float(u_p95_rms),
        "utility_strehl": float(u_strehl),
    }


def _run_instrumented_eval(
    frontier: Any,
    controller_fn: Any,
    *,
    max_voltage: float = DEFAULT_MAX_VOLTAGE,
    n_cases: int = DEFAULT_CASES,
    capture_trace: bool = True,
) -> dict[str, Any]:
    import numpy as np

    sys_cfg = frontier.make_system(seed=53)
    rng = sys_cfg["rng"]
    pupil = sys_cfg["pupil"]
    valid_mask = sys_cfg["valid_mask"]
    zern = sys_cfg["zern"]
    slopes_from_phase = sys_cfg["slopes_from_phase"]
    dm_surface = sys_cfg["dm_surface"]
    reconstructor = sys_cfg["reconstructor"]
    control_model = sys_cfg["control_model"]
    strehl_ref = sys_cfg["strehl_ref"]
    n_act = sys_cfg["n_act"]

    case_trace: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    previous_cmd_for_stats = None

    for case_index in range(n_cases):
        coeff = rng.normal(0.0, 0.35, size=zern.shape[0])
        phase = np.tensordot(coeff, zern, axes=(0, 0))

        true_slopes = slopes_from_phase(phase)
        slopes_multi, fault_trace = _make_multi_wfs_observation_with_trace(rng, true_slopes)
        channel_diag = _channel_diagnostics(slopes_multi, control_model)

        try:
            cmd = controller_fn(slopes_multi, reconstructor, control_model, None, max_voltage=max_voltage)
            cmd = np.asarray(cmd, dtype=np.float64)
        except Exception as exc:
            return {
                "is_valid": False,
                "error_message": f"Controller exception on case {case_index}: {exc}",
                "traceback": traceback.format_exc(),
                "case_trace": case_trace,
            }

        if cmd.shape != (n_act,):
            return {
                "is_valid": False,
                "error_message": f"Invalid output shape on case {case_index}: {cmd.shape}, expected {(n_act,)}",
                "case_trace": case_trace,
            }
        if not np.all(np.isfinite(cmd)):
            return {
                "is_valid": False,
                "error_message": f"Controller output contains NaN/Inf on case {case_index}",
                "case_trace": case_trace,
            }
        if np.any(np.abs(cmd) > max_voltage + 1e-8):
            return {
                "is_valid": False,
                "error_message": f"Controller output violates voltage bounds on case {case_index}",
                "case_trace": case_trace,
            }

        residual = (phase - dm_surface(cmd)) * pupil
        rms = float(np.sqrt(np.mean(residual[valid_mask] ** 2)))
        i_psf = np.abs(frontier.fouriertransform.ft2((pupil * np.exp(1j * residual)).astype(np.complex128), 1.0)) ** 2
        strehl = float(i_psf.max() / strehl_ref)
        saturation_fraction = float(np.mean(np.abs(cmd) >= max_voltage - 1e-8))
        command_slew_l2 = 0.0
        if previous_cmd_for_stats is not None and previous_cmd_for_stats.shape == cmd.shape:
            command_slew_l2 = float(np.linalg.norm(cmd - previous_cmd_for_stats))
        previous_cmd_for_stats = cmd

        case_entry = {
            "case_index": case_index,
            "rms": rms,
            "strehl": strehl,
            "command_l2": float(np.linalg.norm(cmd)),
            "command_linf": float(np.max(np.abs(cmd))),
            "command_mean_abs": float(np.mean(np.abs(cmd))),
            "command_slew_l2": command_slew_l2,
            "saturation_fraction": saturation_fraction,
        }
        if capture_trace:
            case_entry.update(fault_trace)
            case_entry.update(channel_diag)
        case_trace.append(case_entry)

        if case_index == 0:
            psf = i_psf / (i_psf.sum() + 1e-12)
            examples.append(_example_summary(phase, residual, psf, cmd, slopes_multi))

    metrics = _aggregate_case_metrics(case_trace, frontier)
    command_l2 = [float(item["command_l2"]) for item in case_trace]
    command_linf = [float(item["command_linf"]) for item in case_trace]
    command_mean_abs = [float(item["command_mean_abs"]) for item in case_trace]
    command_slew = [float(item["command_slew_l2"]) for item in case_trace[1:]]
    saturation = [float(item["saturation_fraction"]) for item in case_trace]

    return {
        "is_valid": True,
        "metrics": metrics,
        "case_trace": case_trace,
        "examples": examples,
        "command_stats": {
            "l2": _summary_stats(command_l2),
            "linf": _summary_stats(command_linf),
            "mean_abs": _summary_stats(command_mean_abs),
            "slew_l2": _summary_stats(command_slew),
            "saturation_fraction": _summary_stats(saturation),
        },
    }


def _normalized_metrics(candidate: dict[str, Any], reference: dict[str, Any], runtime_s: float) -> dict[str, float]:
    cand = candidate.get("metrics") or {}
    ref = reference.get("metrics") or {}
    score = _as_float(cand.get("score_0_to_1_higher_is_better"), 0.0)
    ref_score = _as_float(ref.get("score_0_to_1_higher_is_better"), 0.0)
    metrics = {
        "valid": 1.0,
        "combined_score": score,
        "candidate_score": score,
        "candidate_score_pct": _as_float(cand.get("score_percent"), score * 100.0),
        "oracle_score": ref_score,
        "oracle_score_pct": _as_float(ref.get("score_percent"), ref_score * 100.0),
        "score_gap_oracle_minus_candidate": ref_score - score,
        "candidate_mean_rms": _as_float(cand.get("mean_rms")),
        "candidate_p95_rms": _as_float(cand.get("p95_rms")),
        "candidate_worst_rms": _as_float(cand.get("worst_rms")),
        "candidate_mean_strehl": _as_float(cand.get("mean_strehl")),
        "candidate_raw_cost_lower_is_better": _as_float(cand.get("raw_cost_lower_is_better")),
        "oracle_mean_rms": _as_float(ref.get("mean_rms")),
        "oracle_p95_rms": _as_float(ref.get("p95_rms")),
        "oracle_mean_strehl": _as_float(ref.get("mean_strehl")),
        "runtime_s": float(runtime_s),
    }
    command_stats = candidate.get("command_stats") or {}
    for group_name, group in command_stats.items():
        if isinstance(group, dict):
            for key, value in group.items():
                metrics[f"command_{group_name}_{key}"] = _as_float(value)
    return metrics


def evaluate(program_path: str, output_dir: str) -> dict[str, Any]:
    import time

    output_dir_p = Path(output_dir).expanduser().resolve()
    output_dir_p.mkdir(parents=True, exist_ok=True)
    program_path_p = Path(program_path).expanduser().resolve()

    if not program_path_p.is_file():
        message = f"Candidate program not found: {program_path_p}"
        _write_failure_sidecars(output_dir_p, message)
        return _failure_result(message)

    try:
        frontier_root = _default_frontier_root()
    except FileNotFoundError as exc:
        message = str(exc)
        _write_failure_sidecars(output_dir_p, message)
        return _failure_result(message)

    delegated = _delegate_to_optics_python(frontier_root, program_path_p, output_dir_p)
    if delegated is not None:
        return delegated

    if not _current_python_has_optics():
        message = (
            "Current Python environment is missing Optics dependencies (aotools, sklearn, matplotlib, numpy). "
            "Install benchmarks/Optics/requirements.txt into the agentic-evolve environment, or set OPTICS_PYTHON "
            "to an interpreter that can run this evaluator."
        )
        raw = {
            "benchmark": "Optics/adaptive_fault_tolerant_fusion",
            "frontier_root": str(frontier_root),
            "candidate_program": str(program_path_p),
            "is_valid": False,
            "error_message": message,
            "partial_case_trace": [],
        }
        _write_failure_sidecars(output_dir_p, message, raw)
        return _failure_result(message, raw_artifacts=raw)

    start = time.time()
    try:
        frontier = _load_frontier_evaluator(frontier_root)
        candidate_fn = frontier.load_callable(program_path_p, "fuse_and_compute_dm_commands")
        candidate = _run_instrumented_eval(frontier, candidate_fn, capture_trace=True)
    except Exception as exc:
        message = f"Failed to run Frontier evaluation setup: {exc}"
        _write_failure_sidecars(output_dir_p, message)
        return _failure_result(message)

    if not candidate.get("is_valid"):
        message = str(candidate.get("error_message") or "Controller failed evaluation contract.")
        raw = {
            "benchmark": "Optics/adaptive_fault_tolerant_fusion",
            "frontier_root": str(frontier_root),
            "candidate_program": str(program_path_p),
            "is_valid": False,
            "error_message": message,
            "partial_case_trace": candidate.get("case_trace") or [],
            "traceback": candidate.get("traceback"),
        }
        _write_json(output_dir_p / "raw-artifact.json", raw)
        _write_json(output_dir_p / "artifacts.json", {"error_message": message})
        _write_json(output_dir_p / "metrics.json", {"valid": 0.0, "combined_score": 0.0, "failure_reason": message})
        _write_json(output_dir_p / "last_eval.json", {"metrics": {"valid": 0.0, "combined_score": 0.0}, "error_message": message})
        return _failure_result(message, raw_artifacts=raw)

    try:
        reference = _run_instrumented_eval(frontier, frontier.reference_controller, capture_trace=False)
    except Exception as exc:
        message = f"Candidate evaluation succeeded but reference evaluation failed: {exc}"
        _write_failure_sidecars(output_dir_p, message)
        return _failure_result(message)

    runtime_s = time.time() - start
    metrics = _normalized_metrics(candidate, reference, runtime_s)
    candidate_metrics = candidate.get("metrics") or {}
    reference_metrics = reference.get("metrics") or {}
    report = {
        "task": "task4_fault_tolerant_fusion",
        "benchmark_profile": "v3_fault_stress",
        "candidate_module": str(program_path_p),
        "oracle_backend": "IsolationForest weighted inlier fusion",
        "fault_scenario": "5 WFS channels with 3 severe random corruptions per case",
        "score_mode": "0_to_1_higher_is_better",
        "score_anchors": dict(frontier.SCORE_ANCHORS),
        "score_weights": dict(frontier.SCORE_WEIGHTS),
        "baseline": candidate_metrics,
        "reference": reference_metrics,
        "metrics": metrics,
    }
    raw_artifacts = {
        "benchmark": "Optics/adaptive_fault_tolerant_fusion",
        "frontier_root": str(frontier_root),
        "candidate_program": str(program_path_p),
        "case_count": len(candidate.get("case_trace") or []),
        "max_voltage": DEFAULT_MAX_VOLTAGE,
        "metrics": metrics,
        "aggregate": report,
        "command_stats": candidate.get("command_stats") or {},
        "case_trace": candidate.get("case_trace") or [],
        "examples": candidate.get("examples") or [],
    }
    artifacts = {
        "task_name": "adaptive_fault_tolerant_fusion",
        "task_kind": "adaptive",
        "error_message": "",
        "raw_artifact_case_count": raw_artifacts["case_count"],
        "reference_score": metrics["oracle_score"],
    }

    _write_json(output_dir_p / "last_eval.json", report)
    _write_json(output_dir_p / "metrics.json", metrics)
    _write_json(output_dir_p / "artifacts.json", artifacts)
    _write_json(output_dir_p / "raw-artifact.json", raw_artifacts)

    score = metrics["combined_score"]
    feedback = (
        f"Score: {score:.4f}\n"
        f"Mean RMS: {metrics['candidate_mean_rms']:.4f}\n"
        f"P95 RMS: {metrics['candidate_p95_rms']:.4f}\n"
        f"Mean Strehl: {metrics['candidate_mean_strehl']:.4f}\n"
        f"Oracle gap: {metrics['score_gap_oracle_minus_candidate']:.4f}"
    )
    return {
        "score": score,
        "is_valid": True,
        "feedback": feedback,
        "metrics": metrics,
        "construction": report,
        "raw_artifacts": raw_artifacts,
    }


def _main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        if len(sys.argv) != 5:
            raise SystemExit("Usage: evaluator.py --worker PROGRAM_PATH OUTPUT_DIR RESULT_PICKLE")
        result = evaluate(sys.argv[2], sys.argv[3])
        with open(sys.argv[4], "wb") as f:
            pickle.dump(result, f)
        return

    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    result = evaluate(candidate, out)
    printable = {key: value for key, value in result.items() if key != "raw_artifacts"}
    print(json.dumps(_to_jsonable(printable), indent=2))


if __name__ == "__main__":
    _main()
