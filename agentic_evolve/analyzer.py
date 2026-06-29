from __future__ import annotations

import json
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def run_analyzer(
    analyzer_path: Path,
    program_path: Path,
    output_dir: Path,
    result: dict,
    archive_dir: Path,
    workspace_dir: Path,
    timeout_seconds: int,
    max_feedback_lines: int | None = None,
) -> dict:
    if not analyzer_path.is_file():
        return {}

    try:
        payload = _run_analyzer_in_subprocess(
            analyzer_path=analyzer_path,
            program_path=program_path,
            output_dir=output_dir,
            result=result,
            archive_dir=archive_dir,
            workspace_dir=workspace_dir,
            timeout_seconds=timeout_seconds,
        )
        return _normalize_analysis(payload, max_feedback_lines=max_feedback_lines)
    except Exception as exc:
        return {
            "processed_feedback": _limit_feedback_lines(
                f"Analyzer failed: {exc}",
                max_feedback_lines,
            ),
            "analysis_metrics": {},
            "analysis": {"error": str(exc)},
        }


def _run_analyzer_in_subprocess(
    analyzer_path: Path,
    program_path: Path,
    output_dir: Path,
    result: dict,
    archive_dir: Path,
    workspace_dir: Path,
    timeout_seconds: int,
) -> Any:
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        result_file = tmp.name

    base_result_json = json.dumps(result, default=str)
    script = f"""
import importlib.util
import json
import pickle
import sys
import traceback

analyzer_path = {str(analyzer_path)!r}
program_path = {str(program_path)!r}
output_dir = {str(output_dir)!r}
base_result = json.loads({base_result_json!r})
archive_dir = {str(archive_dir)!r}
workspace_dir = {str(workspace_dir)!r}
result_file = {result_file!r}

try:
    spec = importlib.util.spec_from_file_location("user_analyzer", analyzer_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "analyze"):
        raise AttributeError("analyzer must define analyze(program_path, output_dir, result, archive_dir, workspace_dir)")
    analysis = module.analyze(
        program_path=program_path,
        output_dir=output_dir,
        result=base_result,
        archive_dir=archive_dir,
        workspace_dir=workspace_dir,
    )
    with open(result_file, "wb") as f:
        pickle.dump(analysis, f)
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

        if isinstance(payload, dict) and "error" in payload:
            raise RuntimeError(payload["error"])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Analyzer subprocess failed")
        return payload
    finally:
        Path(result_file).unlink(missing_ok=True)
        Path(script_path).unlink(missing_ok=True)


def _normalize_analysis(payload: Any, *, max_feedback_lines: int | None = None) -> dict:
    if payload is None:
        return {}
    if isinstance(payload, str):
        return {
            "processed_feedback": _limit_feedback_lines(payload, max_feedback_lines),
            "analysis_metrics": {},
        }
    if not isinstance(payload, dict):
        return {
            "processed_feedback": _limit_feedback_lines(str(payload), max_feedback_lines),
            "analysis_metrics": {},
        }

    normalized: dict[str, Any] = {}
    processed_feedback = payload.get("processed_feedback", payload.get("feedback", ""))
    if processed_feedback:
        normalized["processed_feedback"] = _limit_feedback_lines(
            str(processed_feedback),
            max_feedback_lines,
        )

    metrics = payload.get("analysis_metrics", payload.get("metrics", {}))
    normalized["analysis_metrics"] = _as_dict(metrics)

    if "analysis" in payload:
        normalized["analysis"] = _json_safe(payload["analysis"])
    else:
        extras = {
            key: value
            for key, value in payload.items()
            if key not in {"processed_feedback", "feedback", "analysis_metrics", "metrics"}
        }
        if extras:
            normalized["analysis"] = _json_safe(extras)

    return normalized


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        safe = _json_safe(value)
        return safe if isinstance(safe, dict) else {}
    return {}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _limit_feedback_lines(text: str, max_lines: int | None) -> str:
    if max_lines is None:
        return text
    if max_lines < 1:
        return ""

    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text

    marker = f"... [truncated; showing {max_lines} of {len(lines)} lines]"
    if max_lines == 1:
        return marker
    return "\n".join([*lines[: max_lines - 1], marker])
