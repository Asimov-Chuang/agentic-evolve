from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml

from agentic_evolve.archive import Archive
from agentic_evolve.checkpoint import load_checkpoint
from agentic_evolve.cli import run_evolution
from agentic_evolve.config import load_config
from agentic_evolve.r2_monitor import best_r2_in_archive, is_r2_threshold_met
from agentic_evolve.score_trajectory import record_event

from alpha_diagnosis.config_schema import WorkflowConfig
from alpha_diagnosis.rule_extract import RuleSpec, extract_rules


def _discovery_trajectory_fields(config) -> dict:
    archive = Archive(config.archive_dir, config.maximize)
    best = archive.best()
    return {
        "best_so_far": best.score if best else None,
        "best_attempt_id": best.attempt_id if best else None,
        "attempt_count": archive.submission_count(),
        "remaining": archive.remaining_improvements(config.max_improvements),
    }


def _should_auto_resume_discovery(
    config,
    *,
    auto_resume: bool,
    r2_threshold: float | None = None,
) -> bool:
    if not auto_resume:
        return False
    archive = Archive(config.archive_dir, config.maximize)
    if r2_threshold is not None and is_r2_threshold_met(archive, r2_threshold):
        return False
    if archive.remaining_improvements(config.max_improvements) <= 0:
        return False
    checkpoint = load_checkpoint(config.workspace_dir)
    return not (checkpoint and checkpoint.status == "completed")


def _run_discovery_until_done(
    cfg_path: Path,
    *,
    verbose: bool,
    fresh: bool,
    auto_resume: bool,
    r2_threshold: float | None = None,
    poll_interval_seconds: int = 30,
) -> int:
    """Run discovery with optional auto-resume when the agent exits early."""
    session_resume = False
    use_fresh = fresh
    while True:
        rc = run_evolution(
            str(cfg_path),
            verbose=verbose,
            fresh=use_fresh,
            resume=session_resume,
            r2_early_stop_threshold=r2_threshold,
            poll_interval_seconds=poll_interval_seconds,
        )
        if rc != 0:
            return rc

        config = load_config(cfg_path)
        if not _should_auto_resume_discovery(
            config,
            auto_resume=auto_resume,
            r2_threshold=r2_threshold,
        ):
            if (
                verbose
                and r2_threshold is not None
                and is_r2_threshold_met(Archive(config.archive_dir, config.maximize), r2_threshold)
            ):
                best_r2 = best_r2_in_archive(Archive(config.archive_dir, config.maximize))
                print(
                    f"discovery: R² threshold reached (best R²={best_r2:.4f} >= {r2_threshold:.4f}); "
                    "proceeding to injection.",
                    flush=True,
                )
            return rc

        if verbose:
            remaining = Archive(config.archive_dir, config.maximize).remaining_improvements(
                config.max_improvements
            )
            print(
                f"discovery: agent exited early with {remaining} improvement(s) remaining; "
                "auto-resuming...",
                flush=True,
            )
        record_event(
            config.workspace_dir,
            "auto_resume",
            mode="discovery",
            **_discovery_trajectory_fields(config),
        )
        session_resume = True
        use_fresh = False


@dataclass
class DiscoveryResult:
    project_name: str
    workspace_dir: Path
    best_attempt_id: str
    best_score: float
    rules: List[RuleSpec]
    cycle: int
    run_index: int


def _write_discovery_config(
    workflow: WorkflowConfig,
    primary_archive: Path,
    project_name: str,
    output_config_path: Path,
) -> None:
    assert workflow.discovery is not None
    dcfg = workflow.discovery
    if dcfg.task_dir is None:
        raise ValueError(
            f"discovery.task_dir is required for discovery mode {dcfg.mode!r}"
        )
    template_path = dcfg.task_dir / "config.template.yaml"
    if template_path.is_file():
        with open(template_path, encoding="utf-8") as f:
            raw: dict = yaml.safe_load(f) or {}
    else:
        raw = {
            "maximize": True,
            "problem": "problem.md",
            "initial_program": "initial_program.py",
            "evaluator": "evaluator.py",
            "agent_readable_evaluator": True,
            "verbose": False,
            "opencode": {
                "command": "opencode",
                "args": ["run", "--dangerously-skip-permissions"],
            },
        }

    raw["project_name"] = project_name
    raw["source_archive"] = str(primary_archive.resolve())
    raw["source_archive_top_n"] = dcfg.source_top_n
    raw["rule_set_size"] = dcfg.rule_set_size
    raw["max_improvements"] = dcfg.max_improvements
    raw["agent_timeout_seconds"] = dcfg.agent_timeout_seconds
    raw["evaluation_timeout_seconds"] = dcfg.evaluation_timeout_seconds
    raw["problem"] = str((dcfg.task_dir / "problem.md").resolve())
    raw["initial_program"] = str((dcfg.task_dir / "initial_program.py").resolve())
    raw["evaluator"] = str((dcfg.task_dir / "evaluator.py").resolve())

    if dcfg.mode == "algorithm_based_rule":
        raw["discovery_sample_type"] = "code"

    output_config_path.parent.mkdir(parents=True, exist_ok=True)
    output_config_path.write_text(yaml.dump(raw, sort_keys=False), encoding="utf-8")


def run_discovery_cycle(
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

    cfg_dir = primary_workspace / "alpha-diagnosis" / "discovery_configs" / f"cycle_{cycle:02d}"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    best_result: DiscoveryResult | None = None
    for run_index in range(dcfg.runs):
        project_name = f"{primary_name}_drd_c{cycle:02d}_r{run_index:02d}"
        cfg_path = cfg_dir / f"run_{run_index:02d}.yaml"
        _write_discovery_config(workflow, primary_archive, project_name, cfg_path)
        fresh = dcfg.fresh_each_run
        _run_discovery_until_done(
            cfg_path,
            verbose=verbose,
            fresh=fresh,
            auto_resume=workflow.loop.auto_resume_on_early_exit,
            r2_threshold=dcfg.early_injection_r2_threshold,
            poll_interval_seconds=workflow.stuck.poll_interval_seconds,
        )

        disc_cfg = load_config(cfg_path)
        archive = Archive(disc_cfg.archive_dir, disc_cfg.maximize)
        best = archive.best()
        if best is None:
            continue
        rules = extract_rules(best.directory)
        candidate = DiscoveryResult(
            project_name=project_name,
            workspace_dir=disc_cfg.workspace_dir,
            best_attempt_id=best.attempt_id,
            best_score=best.score,
            rules=rules,
            cycle=cycle,
            run_index=run_index,
        )
        if best_result is None or candidate.best_score > best_result.best_score:
            best_result = candidate

    if best_result is None:
        raise RuntimeError("All discovery runs failed to produce a valid rule set")
    return best_result


def save_discovery_artifact(primary_workspace: Path, result: DiscoveryResult) -> Path:
    out = primary_workspace / "alpha-diagnosis" / f"discovery_cycle_{result.cycle:02d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
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

    rule_src = (
        result.workspace_dir
        / "archive"
        / result.best_attempt_id
        / "code.py"
    )
    if rule_src.is_file():
        rule_dst_dir = primary_workspace / "alpha-diagnosis" / "rule_programs"
        rule_dst_dir.mkdir(parents=True, exist_ok=True)
        rule_dst = rule_dst_dir / f"cycle_{result.cycle:02d}.py"
        rule_dst.write_text(rule_src.read_text(encoding="utf-8"), encoding="utf-8")

    return out
