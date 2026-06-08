from __future__ import annotations

import json
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

from agentic_evolve.analyzer import run_analyzer
from agentic_evolve.registry import evaluation_env


def normalize_evaluation_result(payload: dict) -> dict:
    result = {
        "score": float(payload["score"]),
        "is_valid": bool(payload["is_valid"]),
        "feedback": str(payload.get("feedback", "")),
        "metrics": dict(payload.get("metrics") or {}),
    }
    for key, value in payload.items():
        if key not in result:
            result[key] = _json_safe(value)
    return result


def run_evaluation(
    evaluator_path: Path,
    program_path: Path,
    output_dir: Path,
    timeout_seconds: int,
    maximize: bool = True,
    analyzer_path: Path | None = None,
    archive_dir: Path | None = None,
    workspace_dir: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "evaluation_result.json"

    worst_score = float("-inf") if maximize else float("inf")

    try:
        ws = workspace_dir or output_dir.parent
        hidden = False
        meta_path = ws / "workspace_meta.json"
        if meta_path.is_file():
            with open(meta_path, encoding="utf-8") as f:
                hidden = bool(json.load(f).get("hidden_testdata", False))
        result = _evaluate_in_subprocess(
            evaluator_path=evaluator_path,
            program_path=program_path,
            output_dir=output_dir,
            timeout_seconds=timeout_seconds,
            env=evaluation_env(ws.name, hidden_testdata=hidden),
        )
    except Exception as exc:
        result = {
            "score": worst_score,
            "is_valid": False,
            "feedback": f"Evaluation failed: {exc}",
            "metrics": {},
        }

    if analyzer_path is not None:
        analysis = run_analyzer(
            analyzer_path=analyzer_path,
            program_path=program_path,
            output_dir=output_dir,
            result=result,
            archive_dir=archive_dir or output_dir.parent,
            workspace_dir=workspace_dir or output_dir.parent,
            timeout_seconds=timeout_seconds,
        )
        result.update(analysis)

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def _evaluate_in_subprocess(
    evaluator_path: Path,
    program_path: Path,
    output_dir: Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        result_file = tmp.name

    script = f"""
import importlib.util
import pickle
import sys
import traceback

evaluator_path = {str(evaluator_path)!r}
program_path = {str(program_path)!r}
output_dir = {str(output_dir)!r}
result_file = {result_file!r}

try:
    spec = importlib.util.spec_from_file_location("user_evaluator", evaluator_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "evaluate"):
        raise AttributeError("evaluator must define evaluate(program_path, output_dir)")
    result = module.evaluate(program_path, output_dir)
    if not isinstance(result, dict):
        raise TypeError("evaluate() must return a dict")
    with open(result_file, "wb") as f:
        pickle.dump(result, f)
except Exception:
    with open(result_file, "wb") as f:
        pickle.dump({{"error": traceback.format_exc()}}, f)
    sys.exit(1)
"""

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp_script:
        tmp_script.write(script.encode("utf-8"))
        script_path = tmp_script.name

    try:
        completed = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
        with open(result_file, "rb") as f:
            payload = pickle.load(f)

        if "error" in payload:
            raise RuntimeError(payload["error"])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Evaluator subprocess failed")

        return normalize_evaluation_result(payload)
    finally:
        Path(result_file).unlink(missing_ok=True)
        Path(script_path).unlink(missing_ok=True)


def _json_safe(value):
    return json.loads(json.dumps(value, default=str))
