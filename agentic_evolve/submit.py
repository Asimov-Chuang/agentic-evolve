#!/usr/bin/env python3
"""Evaluate a candidate and archive it under archive/attempt_NNNN/."""

from __future__ import annotations

import json
import importlib.util
import pickle
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _evaluation_env(project_name: str, *, hidden_testdata: bool, workspace: Path) -> dict[str, str]:
    try:
        from agentic_evolve.registry import evaluation_env

        return evaluation_env(project_name, hidden_testdata=hidden_testdata)
    except ModuleNotFoundError:
        runner_path = workspace / "_registry.py"
        spec = importlib.util.spec_from_file_location("registry_runner", runner_path)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(
                f"agentic-evolve is not installed and missing workspace helper: {runner_path}"
            ) from None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.evaluation_env(
            project_name,
            hidden_testdata=hidden_testdata,
            start=workspace,
        )


def _load_meta(workspace: Path) -> dict:
    meta_path = workspace / "workspace_meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Missing workspace_meta.json in {workspace}")
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def _evaluator_path(workspace: Path, meta: dict) -> Path:
    filename = meta.get("evaluator_filename", "evaluator.py")
    return workspace / filename


def _load_run_analyzer(workspace: Path):
    try:
        from agentic_evolve.analyzer import run_analyzer

        return run_analyzer
    except ModuleNotFoundError:
        runner_path = workspace / "_analyzer_runner.py"
        spec = importlib.util.spec_from_file_location("analyzer_runner", runner_path)
        if spec is None or spec.loader is None:
            raise
        runner_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner_module)
        return runner_module.run_analyzer


def _normalize_evaluation_result(payload: dict) -> dict:
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


def _record_score_trajectory(
    workspace: Path,
    archive_dir: Path,
    attempt_dir: Path,
    meta: dict,
) -> None:
    try:
        from agentic_evolve.archive import Attempt
        from agentic_evolve.score_trajectory import record_attempt

        attempt = Attempt.from_directory(attempt_dir)
        record_attempt(
            workspace,
            archive_dir,
            attempt,
            maximize=bool(meta.get("maximize", True)),
        )
    except Exception as exc:
        print(f"Warning: score trajectory not recorded: {exc}", file=sys.stderr)


def _json_safe(value):
    return json.loads(json.dumps(value, default=str))


# Large evaluator extras (e.g. packing coordinates) are kept in result.json
# but omitted from stdout so the agent sees a compact summary.
_AGENT_DISPLAY_OMIT_KEYS = frozenset({"construction", "per_case"})

# Keys stripped from result.json and written as sidecar files in the attempt dir.
_RESULT_SIDECAR_KEYS: dict[str, str] = {
    "raw_artifacts": "raw-artifact.json",
    "stepwise_raw_artifacts": "raw-artifact.json",
}


def _result_for_agent_display(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in _AGENT_DISPLAY_OMIT_KEYS}


def _strip_construction_stepwise(construction: Any) -> Any:
    if not isinstance(construction, dict):
        return construction
    cleaned = dict(construction)
    cleaned.pop("stepwise_raw_artifacts", None)
    return cleaned


def _persist_result_sidecars(attempt_dir: Path, payload: dict) -> None:
    for key, filename in _RESULT_SIDECAR_KEYS.items():
        if key not in payload:
            continue
        sidecar_path = attempt_dir / filename
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(_json_safe(payload.pop(key)), f, indent=2)
        break

    if "construction" in payload:
        payload["construction"] = _strip_construction_stepwise(payload["construction"])


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
    workspace: Path,
    project_name: str,
    meta: dict,
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
            env=_evaluation_env(
                project_name,
                hidden_testdata=bool(meta.get("hidden_testdata", False)),
                workspace=workspace,
            ),
        )
        with open(result_file, "rb") as f:
            payload = pickle.load(f)

        if "error" in payload:
            raise RuntimeError(payload["error"])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Evaluator subprocess failed")

        return _normalize_evaluation_result(payload)
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
        evaluator_path=_evaluator_path(workspace, meta),
        program_path=attempt_dir / "code.py",
        output_dir=attempt_dir,
        timeout_seconds=int(meta.get("evaluation_timeout_seconds", 60)),
        maximize=bool(meta.get("maximize", True)),
        workspace=workspace,
        project_name=str(meta.get("project_name", workspace.name)),
        meta=meta,
    )
    if meta.get("analyzer_enabled"):
        run_analyzer = _load_run_analyzer(workspace)
        analysis = run_analyzer(
            analyzer_path=workspace / "analyzer.py",
            program_path=attempt_dir / "code.py",
            output_dir=attempt_dir,
            result=result,
            archive_dir=archive_dir,
            workspace_dir=workspace,
            timeout_seconds=int(meta.get("evaluation_timeout_seconds", 60)),
        )
        result.update(analysis)

    payload = _normalize_evaluation_result(result)
    if meta.get("hidden_testdata"):
        payload.pop("per_case", None)
    _persist_result_sidecars(attempt_dir, payload)
    with open(attempt_dir / "result.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    _record_score_trajectory(workspace, archive_dir, attempt_dir, meta)

    print(json.dumps(_result_for_agent_display(payload), indent=2))
    print(f"Archived to {attempt_dir.name}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
