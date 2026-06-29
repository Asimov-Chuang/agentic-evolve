from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Template

from agentic_evolve.archive import Attempt
from agentic_evolve.config import load_config
from agentic_evolve.opencode_runner import OpenCodeRunner

from alpha_diagnosis.config_schema import WorkflowConfig
from alpha_diagnosis.direction_extract import extract_directions
from alpha_diagnosis.discovery import DiscoveryResult


def _eligible_review_attempts(source: Path) -> list[tuple[str, float, Path]]:
    """Attempts with code.py and scored result.json (no raw-artifact required)."""
    eligible: list[tuple[str, float, Path]] = []
    for attempt_dir in sorted(source.glob("attempt_*")):
        if not attempt_dir.is_dir():
            continue
        code_path = attempt_dir / "code.py"
        result_path = attempt_dir / "result.json"
        if not code_path.is_file() or not result_path.is_file():
            continue
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        score = result.get("score")
        if score is None:
            continue
        eligible.append((attempt_dir.name, float(score), attempt_dir))
    return eligible


def _top_review_attempt_dirs(source: Path, top_n: int, maximize: bool) -> list[Path]:
    eligible = _eligible_review_attempts(source)
    if not eligible:
        raise ValueError(
            f"No eligible attempts in {source} (need attempt_*/code.py and result.json with score)"
        )
    eligible.sort(key=lambda item: (item[1], item[0]), reverse=maximize)
    return [path for _name, _score, path in eligible[:top_n]]


def _write_archive_summary(attempt_dirs: list[Path], dest: Path, maximize: bool) -> None:
    lines: list[str] = []
    scored: list[tuple[str, float, str]] = []
    for attempt_dir in attempt_dirs:
        attempt = Attempt.from_directory(attempt_dir)
        feedback = attempt.processed_feedback or attempt.feedback
        status = "valid" if attempt.is_valid else "invalid"
        scored.append((attempt.attempt_id, attempt.score, feedback))
    scored.sort(key=lambda x: x[1], reverse=maximize)
    for attempt_id, score, feedback in scored:
        lines.append(f"- {attempt_id}: score={score:.6f} ({status})")
        lines.append(f"  feedback: {feedback[:500]}{'...' if len(feedback) > 500 else ''}")
        lines.append("")
    dest.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _prepare_review_workspace(
    review_dir: Path,
    primary_archive: Path,
    primary_workspace: Path,
    *,
    source_top_n: int,
    maximize: bool,
) -> list[Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = review_dir / "archive"
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    archive_dir.mkdir()

    attempt_dirs = _top_review_attempt_dirs(primary_archive, source_top_n, maximize)
    for attempt_dir in attempt_dirs:
        link = archive_dir / attempt_dir.name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(attempt_dir.resolve(), target_is_directory=True)

    problem_src = primary_workspace / "problem.md"
    if problem_src.is_file():
        shutil.copy2(problem_src, review_dir / "problem.md")

    _write_archive_summary(attempt_dirs, review_dir / "archive_summary.txt", maximize)
    return attempt_dirs


def _build_history_review_prompt(
    workflow: WorkflowConfig,
    direction_count: int,
) -> str:
    template_path = workflow.alpha_diagnosis_root / "templates" / "history_review_prompt.md.j2"
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.render(direction_count=direction_count)


def run_history_review_cycle(
    workflow: WorkflowConfig,
    primary_config_path: Path,
    primary_archive: Path,
    primary_workspace: Path,
    cycle: int,
    *,
    verbose: bool = False,
) -> DiscoveryResult:
    assert workflow.discovery is not None
    dcfg = workflow.discovery
    primary_cfg = load_config(primary_config_path)
    primary_name = workflow.primary.project_name or primary_cfg.project_name

    review_dir = primary_workspace / "alpha-diagnosis" / "history_review" / f"cycle_{cycle:02d}"
    _prepare_review_workspace(
        review_dir,
        primary_archive,
        primary_workspace,
        source_top_n=dcfg.source_top_n,
        maximize=primary_cfg.maximize,
    )

    prompt = _build_history_review_prompt(workflow, dcfg.rule_set_size)
    runner = OpenCodeRunner(
        command=primary_cfg.opencode.command,
        args=primary_cfg.opencode.resolved_args(),
        verbose=primary_cfg.verbose or verbose,
    )
    result = runner.run(
        str(review_dir),
        prompt,
        dcfg.agent_timeout_seconds,
    )
    if not result.success:
        raise RuntimeError(
            f"History review agent failed (rc={result.returncode}): {result.error or result.stderr}"
        )

    directions_path = review_dir / "directions.json"
    rules = extract_directions(directions_path, expected_count=dcfg.rule_set_size)

    project_name = f"{primary_name}_hr_c{cycle:02d}"
    return DiscoveryResult(
        project_name=project_name,
        workspace_dir=review_dir,
        best_attempt_id="directions.json",
        best_score=0.0,
        rules=rules,
        cycle=cycle,
        run_index=0,
    )


def save_history_review_artifact(primary_workspace: Path, result: DiscoveryResult) -> Path:
    out = primary_workspace / "alpha-diagnosis" / f"history_review_cycle_{result.cycle:02d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "agent_review",
        "project_name": result.project_name,
        "best_attempt_id": result.best_attempt_id,
        "best_score": result.best_score,
        "rules": [
            {
                "index": r.index,
                "name": r.name,
                "description": r.description,
                "score_effect": r.score_effect,
            }
            for r in result.rules
        ],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out
