#!/usr/bin/env python3
"""Evaluate a candidate and archive it under archive/attempt_NNNN/."""

from __future__ import annotations

import json
import pickle
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _load_meta(workspace: Path) -> dict:
    meta_path = workspace / "workspace_meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Missing workspace_meta.json in {workspace}")
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def _next_attempt_dir(archive_dir: Path) -> Path:
    existing = sorted(archive_dir.glob("attempt_*"))
    attempt_id = f"attempt_{len(existing):04d}"
    attempt_dir = archive_dir / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)
    return attempt_dir


def _evaluate_program(
    evaluator_path: Path,
    program_path: Path,
    output_dir: Path,
    timeout_seconds: int,
    maximize: bool,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    worst_score = float("-inf") if maximize else float("inf")

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
        )
        with open(result_file, "rb") as f:
            payload = pickle.load(f)

        if "error" in payload:
            raise RuntimeError(payload["error"])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Evaluator subprocess failed")

        return {
            "score": float(payload["score"]),
            "is_valid": bool(payload["is_valid"]),
            "feedback": str(payload.get("feedback", "")),
            "metrics": dict(payload.get("metrics") or {}),
        }
    except Exception as exc:
        return {
            "score": worst_score,
            "is_valid": False,
            "feedback": f"Evaluation failed: {exc}",
            "metrics": {},
        }
    finally:
        Path(result_file).unlink(missing_ok=True)
        Path(script_path).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: python submit.py <path-to-code.py>", file=sys.stderr)
        return 1

    code_path = Path(args[0]).resolve()
    if not code_path.is_file():
        print(f"Code file not found: {code_path}", file=sys.stderr)
        return 1

    workspace = Path(__file__).resolve().parent
    meta = _load_meta(workspace)
    archive_dir = workspace / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    submissions_after_seed = max(0, len(list(archive_dir.glob("attempt_*"))) - 1)
    max_improvements = int(meta.get("max_improvements", 10))
    if submissions_after_seed >= max_improvements:
        print(
            f"Improvement budget exhausted ({max_improvements} submissions). "
            "No new archive entry created.",
            file=sys.stderr,
        )
        return 2

    attempt_dir = _next_attempt_dir(archive_dir)
    shutil.copy2(code_path, attempt_dir / "code.py")

    result = _evaluate_program(
        evaluator_path=workspace / "evaluator.py",
        program_path=attempt_dir / "code.py",
        output_dir=attempt_dir,
        timeout_seconds=int(meta.get("evaluation_timeout_seconds", 60)),
        maximize=bool(meta.get("maximize", True)),
    )

    payload = {
        "score": float(result["score"]),
        "is_valid": bool(result["is_valid"]),
        "feedback": str(result.get("feedback", "")),
        "metrics": dict(result.get("metrics") or {}),
    }
    with open(attempt_dir / "result.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(json.dumps(payload, indent=2))
    print(f"Archived to {attempt_dir.name}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
