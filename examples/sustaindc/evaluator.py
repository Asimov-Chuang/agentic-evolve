"""SustainDC evaluator for agentic-evolve (Frontier-Engineering subprocess bridge)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_PROGRAM_TIMEOUT_SECONDS = 300


def _default_frontier_root() -> Path:
    env_root = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    evaluate_rel = (
        Path("benchmarks")
        / "SustainableDataCenterControl"
        / "hand_written_control"
        / "verification"
        / "evaluate.py"
    )
    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering"):
            evaluate_py = candidate / evaluate_rel
            if evaluate_py.is_file():
                return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _resolve_paths() -> tuple[Path, Path, Path, Path]:
    frontier_root = _default_frontier_root()
    benchmark_dir = (
        frontier_root / "benchmarks" / "SustainableDataCenterControl" / "hand_written_control"
    )
    evaluate_py = benchmark_dir / "verification" / "evaluate.py"
    sustaindc_root = Path(
        os.environ.get(
            "SUSTAINDC_ROOT",
            str(benchmark_dir / "sustaindc"),
        )
    ).expanduser().resolve()
    python_bin = Path(
        os.environ.get(
            "SUSTAINDC_PYTHON",
            str(frontier_root / ".venvs" / "frontier-v1-sustaindc" / "bin" / "python"),
        )
    ).expanduser()
    # Do not resolve python_bin: resolve() follows the venv symlink to base Python.
    return frontier_root, evaluate_py, sustaindc_root, python_bin


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
        _, evaluate_py, sustaindc_root, python_bin = _resolve_paths()
    except FileNotFoundError as exc:
        return _failure_result(str(exc))

    if not evaluate_py.is_file():
        return _failure_result(
            f"Frontier evaluator not found: {evaluate_py}. "
            "Set FRONTIER_ENGINEERING_ROOT to your Frontier-Engineering checkout."
        )
    if not python_bin.exists():
        return _failure_result(
            f"SustainDC python not found: {python_bin}. "
            "Run Frontier-Engineering setup_v1_task_envs.sh or set SUSTAINDC_PYTHON."
        )
    if not (sustaindc_root / "sustaindc_env.py").is_file():
        return _failure_result(
            f"SustainDC root missing sustaindc_env.py: {sustaindc_root}. "
            "Run fetch_task_assets.py --target sustaindc in Frontier-Engineering."
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
        "--sustaindc-root",
        str(sustaindc_root),
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
            cwd=str(evaluate_py.parent.parent),
        )
    except subprocess.TimeoutExpired:
        return _failure_result(
            f"Evaluation timed out after {_program_timeout_seconds()} seconds."
        )
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

    score = float(report.get("average_score", metrics_payload.get("average_score", 0.0)))
    metrics = {key: value for key, value in metrics_payload.items() if isinstance(value, (int, float))}

    return {
        "score": score,
        "is_valid": True,
        "feedback": f"Score: {score:.4f}",
        "metrics": metrics,
        "construction": report,
    }


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print(json.dumps(evaluate(candidate, out), indent=2, default=str))
