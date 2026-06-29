"""PIDTuning evaluator for agentic-evolve (Frontier-Engineering subprocess bridge)."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_PROGRAM_TIMEOUT_SECONDS = 300

_GAIN_KEYS = [
    "Kp_z", "Ki_z", "Kd_z", "N_z",
    "Kp_x", "Ki_x", "Kd_x", "N_x",
    "Kp_theta", "Ki_theta", "Kd_theta", "N_theta",
]


def _default_frontier_root() -> Path:
    env_root = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    benchmark_rel = Path("benchmarks") / "Robotics" / "PIDTuning"
    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering"):
            benchmark_dir = candidate / benchmark_rel
            if (benchmark_dir / "verification" / "evaluator.py").is_file():
                return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _resolve_paths() -> tuple[Path, Path, Path]:
    frontier_root = _default_frontier_root()
    benchmark_dir = frontier_root / "benchmarks" / "Robotics" / "PIDTuning"
    evaluate_py = benchmark_dir / "verification" / "evaluator.py"
    python_bin = Path(
        os.environ.get(
            "PID_TUNING_PYTHON",
            os.environ.get(
                "FRONTIER_EVAL_DRIVER_PYTHON",
                sys.executable,
            ),
        )
    ).expanduser()
    return frontier_root, evaluate_py, python_bin


def _program_timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))
    return DEFAULT_PROGRAM_TIMEOUT_SECONDS


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Expected JSON file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _failure_result(message: str, *, metrics: dict[str, Any] | None = None) -> dict:
    return {
        "score": 0.0,
        "is_valid": False,
        "feedback": message,
        "metrics": metrics or {},
    }


def _load_benchmark_module(evaluate_py: Path) -> Any:
    spec = importlib.util.spec_from_file_location("pid_tuning_benchmark_eval", evaluate_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load benchmark evaluator: {evaluate_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evaluate_gains_detailed(gains: dict[str, float], benchmark_mod: Any) -> dict[str, Any]:
    cfg = benchmark_mod.load_config()
    scenarios_out: list[dict[str, Any]] = []
    inv_itaes: list[float] = []
    all_feasible = True

    for scenario in cfg["scenarios"]:
        result = benchmark_mod.simulate_quadrotor_2d(gains, scenario, cfg)
        feasible = bool(result["feasible"])
        itae = float(result["itae"])
        inv_itae = (1.0 / itae) if feasible and itae > 0.0 else 0.0
        scenarios_out.append(
            {
                "name": scenario["name"],
                "itae": itae,
                "feasible": feasible,
                "inv_itae": inv_itae,
                "duration": float(scenario["duration"]),
                "wind": list(scenario.get("wind", [0.0, 0.0])),
            }
        )
        if not feasible or itae <= 0.0:
            all_feasible = False
        else:
            inv_itaes.append(inv_itae)

    if not all_feasible or not inv_itaes:
        combined_score = 0.0
    else:
        log_sum = sum(math.log(value) for value in inv_itaes)
        combined_score = float(math.exp(log_sum / len(inv_itaes)))

    return {
        "combined_score": combined_score,
        "feasible": bool(combined_score > 0.0),
        "gains": dict(gains),
        "scenarios": scenarios_out,
        "gain_bounds": dict(cfg["gains"]),
        "constraints": dict(cfg["constraints"]),
    }


def _run_candidate(program_path: Path, benchmark_dir: Path, python_bin: Path) -> tuple[Path | None, str | None]:
    work_dir = Path(tempfile.mkdtemp(prefix="pid_tuning_eval_")).resolve()
    try:
        shutil.copy2(program_path, work_dir / "init.py")
        ref_src = benchmark_dir / "references"
        if ref_src.is_dir():
            shutil.copytree(ref_src, work_dir / "references")

        completed = subprocess.run(
            [str(python_bin), str(work_dir / "init.py")],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=_program_timeout_seconds(),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            return None, f"Candidate exited with code {completed.returncode}: {detail[-2000:]}"

        submission_path = work_dir / "submission.json"
        if not submission_path.is_file():
            return None, "Candidate did not write submission.json"
        return submission_path, None
    except subprocess.TimeoutExpired:
        shutil.rmtree(work_dir, ignore_errors=True)
        return None, f"Candidate timed out after {_program_timeout_seconds()} seconds"
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        return None, f"Failed to run candidate: {exc}"


def evaluate(program_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    program_path_p = Path(program_path).expanduser().resolve()
    output_dir_p = Path(output_dir).resolve()

    if not program_path_p.is_file():
        return _failure_result(f"Candidate program not found: {program_path_p}")

    try:
        frontier_root, evaluate_py, python_bin = _resolve_paths()
    except FileNotFoundError as exc:
        return _failure_result(str(exc))

    benchmark_dir = frontier_root / "benchmarks" / "Robotics" / "PIDTuning"
    if not evaluate_py.is_file():
        return _failure_result(
            f"Frontier evaluator not found: {evaluate_py}. "
            "Set FRONTIER_ENGINEERING_ROOT to your Frontier-Engineering checkout."
        )
    if not python_bin.exists():
        return _failure_result(
            f"PID tuning python not found: {python_bin}. "
            "Set PID_TUNING_PYTHON or FRONTIER_EVAL_DRIVER_PYTHON."
        )

    submission_path, run_error = _run_candidate(program_path_p, benchmark_dir, python_bin)
    if run_error:
        return _failure_result(run_error)

    try:
        benchmark_mod = _load_benchmark_module(evaluate_py)
        cfg = benchmark_mod.load_config()
        gains = benchmark_mod._load_submission(submission_path)  # noqa: SLF001
        if gains is None:
            return _failure_result("submission.json is missing required numeric gain keys")
        if not benchmark_mod._validate_bounds(gains, cfg):  # noqa: SLF001
            return _failure_result("One or more PID gains are out of configured bounds")

        report = _evaluate_gains_detailed(gains, benchmark_mod)
    except Exception as exc:
        return _failure_result(f"Evaluation failed: {exc}")

    score = float(report["combined_score"])
    feasible = bool(report["feasible"])
    metrics = {
        "combined_score": score,
        "feasible": 1.0 if feasible else 0.0,
        "valid": 1.0 if feasible else 0.0,
    }
    for scenario in report["scenarios"]:
        name = str(scenario["name"])
        metrics[f"itae_{name}"] = float(scenario["itae"])
        metrics[f"inv_itae_{name}"] = float(scenario["inv_itae"])

    last_eval_path = output_dir_p / "last_eval.json"
    metrics_path = output_dir_p / "metrics.json"
    artifacts_path = output_dir_p / "artifacts.json"
    raw_artifacts_path = output_dir_p / "raw-artifact.json"

    last_eval_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    artifacts_path.write_text(
        json.dumps(
            {
                "benchmark_dir": str(benchmark_dir),
                "candidate_path": str(program_path_p),
                "submission_keys": _GAIN_KEYS,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    raw_artifacts_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    return {
        "score": score,
        "is_valid": feasible,
        "feedback": f"Score: {score:.6f}" if feasible else "Infeasible PID gains (score=0.0)",
        "metrics": metrics,
        "construction": report,
    }


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print(json.dumps(evaluate(candidate, out), indent=2, default=str))
