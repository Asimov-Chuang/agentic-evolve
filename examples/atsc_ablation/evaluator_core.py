"""Private evaluator and feedback builders for ATSC ablation."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_PROGRAM_TIMEOUT_SECONDS = 120


def _default_frontier_root() -> Path:
    env_root = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    evaluate_rel = (
        Path("benchmarks")
        / "Optics"
        / "adaptive_temporal_smooth_control"
        / "verification"
        / "evaluate.py"
    )
    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering"):
            if (candidate / evaluate_rel).is_file():
                return candidate.resolve()
    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _python_has_aotools(python_bin: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(python_bin), "-c", "import aotools"],
            capture_output=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return completed.returncode == 0


def _resolve_python_bin(frontier_root: Path) -> Path | None:
    env_python = os.environ.get("OPTICS_PYTHON", "").strip() or os.environ.get(
        "GENERAL_MEIO_PYTHON", ""
    ).strip()
    candidates: list[Path] = []
    if env_python:
        candidates.append(Path(env_python).expanduser())
    candidates.append(frontier_root / ".venvs" / "frontier-v1-main" / "bin" / "python")
    candidates.append(frontier_root / ".venvs" / "frontier-v1-main" / "Scripts" / "python.exe")
    candidates.append(Path(sys.executable))
    which_python3 = shutil.which("python3")
    if which_python3:
        candidates.append(Path(which_python3))

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
        if _python_has_aotools(python_bin):
            return python_bin
    return None


def _resolve_paths() -> tuple[Path, Path]:
    frontier_root = _default_frontier_root()
    evaluate_py = (
        frontier_root
        / "benchmarks"
        / "Optics"
        / "adaptive_temporal_smooth_control"
        / "verification"
        / "evaluate.py"
    )
    python_bin = _resolve_python_bin(frontier_root)
    if python_bin is None:
        raise FileNotFoundError(
            "No Python interpreter with aotools found. "
            "Run Frontier-Engineering setup_v1_task_envs.sh and install benchmarks/Optics/requirements.txt, "
            "or set OPTICS_PYTHON / GENERAL_MEIO_PYTHON."
        )
    return evaluate_py, python_bin


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


def evaluate(program_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    program_path_p = Path(program_path).expanduser().resolve()
    output_dir_p = Path(output_dir).resolve()

    if not program_path_p.is_file():
        return _failure_result(f"Candidate program not found: {program_path_p}")

    try:
        evaluate_py, python_bin = _resolve_paths()
    except FileNotFoundError as exc:
        return _failure_result(str(exc))

    if not evaluate_py.is_file():
        return _failure_result(
            f"Frontier evaluator not found: {evaluate_py}. "
            "Set FRONTIER_ENGINEERING_ROOT to your Frontier-Engineering checkout."
        )

    last_eval_path = output_dir_p / "last_eval.json"
    metrics_path = output_dir_p / "metrics.json"
    artifacts_path = output_dir_p / "artifacts.json"
    raw_artifacts_path = output_dir_p / "raw-artifact.json"
    cmd = [
        str(python_bin),
        str(evaluate_py),
        "--solution",
        str(program_path_p),
        "--save-json",
        str(last_eval_path),
        "--metrics-out",
        str(metrics_path),
        "--artifacts-out",
        str(artifacts_path),
        "--raw-artifacts-out",
        str(raw_artifacts_path),
    ]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_program_timeout_seconds(),
            cwd=str(evaluate_py.parent),
        )
    except subprocess.TimeoutExpired:
        return _failure_result(f"Evaluation timed out after {_program_timeout_seconds()} seconds.")
    except Exception as exc:
        return _failure_result(f"Failed to run evaluation: {exc}")

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"return code {completed.returncode}"
        return _failure_result(f"Evaluation failed: {detail[-2000:]}")

    try:
        report = _load_json(last_eval_path)
        metrics_payload = _load_json(metrics_path)
    except Exception as exc:
        return _failure_result(f"Evaluation output missing or invalid: {exc}")

    baseline = report.get("baseline") or {}
    score = float(
        baseline.get(
            "score_0_to_1_higher_is_better",
            metrics_payload.get("combined_score", 0.0),
        )
    )
    return {
        "score": score,
        "is_valid": True,
        "feedback": f"Score: {score:.4f}",
        "metrics": {"score_0_to_1_higher_is_better": score},
    }


def _report_from_output(output_dir: str | Path) -> dict[str, Any]:
    return _load_json(Path(output_dir) / "last_eval.json")


def _load_pro_analyzer():
    analyzer_rel = (
        Path("examples")
        / "adaptive_temporal_smooth_control"
        / "outputs"
        / "optics_temporal_smooth_pro"
        / "analyzer.py"
    )
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / analyzer_rel
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("atsc_pro_feedback_source", candidate)
            if spec is None or spec.loader is None:
                break
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    local_candidate = (
        here.parent.parent
        / "adaptive_temporal_smooth_control"
        / "outputs"
        / "optics_temporal_smooth_pro"
        / "analyzer.py"
    )
    if local_candidate.is_file():
        spec = importlib.util.spec_from_file_location("atsc_pro_feedback_source", local_candidate)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError("Could not locate ATSC pro analyzer source")


def _format_score_only(report: dict[str, Any]) -> str:
    baseline = report.get("baseline") or {}
    score = float(baseline.get("score_0_to_1_higher_is_better", 0.0))
    return f"Score: {score:.4f}"


def analyze(program_path: str, output_dir: str, result: dict, feedback_mode: str) -> dict:
    del program_path
    if not result.get("is_valid"):
        return {
            "processed_feedback": (
                "Invalid controller; fix runtime errors before tuning control logic. "
                f"{result.get('feedback', '')}"
            ),
        }

    report = _report_from_output(output_dir)
    if feedback_mode == "score_only":
        return {"processed_feedback": _format_score_only(report)}
    if feedback_mode != "feedback_with_meaning":
        raise ValueError(f"unknown feedback mode: {feedback_mode}")

    pro_analyzer = _load_pro_analyzer()
    raw = pro_analyzer.load_raw_artifact(output_dir)
    trajectory_metrics = pro_analyzer.extract_trajectory_metrics(raw)
    metrics = pro_analyzer.build_metric_breakdown(report)
    return {
        "processed_feedback": pro_analyzer.format_processed_feedback(report, trajectory_metrics),
        "analysis_metrics": {
            "score_0_to_1_higher_is_better": metrics["score_0_to_1_higher_is_better"],
            "metrics": metrics,
            "trajectory": trajectory_metrics,
        },
        "analysis": {
            "reference_comparison": pro_analyzer.build_reference_comparison(report),
            "diagnosis": pro_analyzer.build_diagnosis(report, trajectory_metrics),
            "trajectory_metrics": trajectory_metrics,
            "raw_artifact_present": raw is not None,
        },
    }


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print(json.dumps(evaluate(candidate, out), indent=2, default=str))
