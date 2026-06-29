#!/usr/bin/env python3
"""Re-run analyzer.py on an existing archive attempt without re-evaluating."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_meta(workspace: Path) -> dict:
    meta_path = workspace / "workspace_meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Missing workspace_meta.json in {workspace}")
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


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


def _resolve_attempt_dir(archive_dir: Path, attempt_id: str | None) -> Path:
    if attempt_id:
        attempt_dir = archive_dir / attempt_id
        if not attempt_dir.is_dir():
            raise FileNotFoundError(f"Attempt directory not found: {attempt_dir}")
        return attempt_dir

    attempts = sorted(archive_dir.glob("attempt_*"))
    if not attempts:
        raise FileNotFoundError(f"No attempts found in {archive_dir}")
    return attempts[-1]


def _strip_analysis_fields(payload: dict) -> None:
    for key in ("processed_feedback", "analysis_metrics", "analysis"):
        payload.pop(key, None)


def _merge_analysis(payload: dict, analysis: dict) -> dict:
    merged = dict(payload)
    _strip_analysis_fields(merged)
    merged.update(analysis)
    return merged


from agentic_evolve.result_sidecars import result_for_agent_display


def rerun_analyzer_on_attempt(
    workspace: Path,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    meta = _load_meta(workspace)
    if not meta.get("analyzer_enabled"):
        raise RuntimeError("analyzer is not enabled in this workspace")

    archive_dir = workspace / "archive"
    attempt_dir = _resolve_attempt_dir(archive_dir, attempt_id)
    result_path = attempt_dir / "result.json"
    if not result_path.is_file():
        raise FileNotFoundError(f"Missing result.json in {attempt_dir}")

    with open(result_path, encoding="utf-8") as f:
        payload = json.load(f)

    code_path = attempt_dir / "code.py"
    if not code_path.is_file():
        raise FileNotFoundError(f"Missing code.py in {attempt_dir}")

    run_analyzer = _load_run_analyzer(workspace)
    analysis = run_analyzer(
        analyzer_path=workspace / "analyzer.py",
        program_path=code_path,
        output_dir=attempt_dir,
        result=payload,
        archive_dir=archive_dir,
        workspace_dir=workspace,
        timeout_seconds=int(meta.get("evaluation_timeout_seconds", 60)),
        max_feedback_lines=meta.get("analyzer_max_feedback_lines"),
    )
    updated = _merge_analysis(payload, analysis)

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)

    return updated


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    attempt_id = args[0] if args else None

    workspace = Path(__file__).resolve().parent
    try:
        payload = rerun_analyzer_on_attempt(workspace, attempt_id)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result_for_agent_display(payload), indent=2))
    resolved = attempt_id or sorted((workspace / "archive").glob("attempt_*"))[-1].name
    print(f"Updated analyzer output for {resolved}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
