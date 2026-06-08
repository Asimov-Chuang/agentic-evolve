from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List

import yaml

from agentic_evolve.archive import Archive, save_best_program
from agentic_evolve.cli import _save_run_checkpoint
from agentic_evolve.config import load_config
from agentic_evolve.opencode_runner import OpenCodeRunner
from agentic_evolve.score_trajectory import record_event, sync_archive_to_trajectory
from agentic_evolve.workspace import setup_workspace

from alpha_diagnosis.config_schema import WorkflowConfig, load_workflow
from alpha_diagnosis.discovery import run_discovery_cycle, save_discovery_artifact
from alpha_diagnosis.prompt_builder import build_rule_guided_prompt, validate_injection_config
from alpha_diagnosis.stuck_monitor import run_with_stuck_monitor

STATE_FILENAME = "state.json"


@dataclass
class AlphaState:
    workflow_name: str
    cycle: int = 0
    last_diagnosis_after_attempt: int = -1
    rule_inspired_ranges: List[dict] = field(default_factory=list)
    discovery_history: List[dict] = field(default_factory=list)
    updated_at: str = ""

    @classmethod
    def load(cls, path: Path) -> AlphaState:
        if not path.is_file():
            return cls(workflow_name="", updated_at=_now())
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return cls(
            workflow_name=str(raw.get("workflow_name", "")),
            cycle=int(raw.get("cycle", 0)),
            last_diagnosis_after_attempt=int(raw.get("last_diagnosis_after_attempt", -1)),
            rule_inspired_ranges=list(raw.get("rule_inspired_ranges") or []),
            discovery_history=list(raw.get("discovery_history") or []),
            updated_at=str(raw.get("updated_at", "")),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        with open(path, encoding="utf-8", mode="w") as f:
            json.dump(asdict(self), f, indent=2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(workspace: Path) -> Path:
    return workspace / "alpha-diagnosis" / STATE_FILENAME


def _resolve_primary_config(workflow: WorkflowConfig) -> Path:
    if not workflow.primary.project_name:
        return workflow.primary.config_path
    original = workflow.primary.config_path.resolve()
    config_dir = original.parent
    with open(original, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    raw["project_name"] = workflow.primary.project_name
    # Keep derived config beside the source config so load_config resolves
    # problem/evaluator paths and outputs/{project_name} from the task dir.
    out_path = config_dir / f".alpha_diagnosis_{workflow.name}_primary.yaml"
    out_path.write_text(yaml.dump(raw), encoding="utf-8")
    return out_path


def _tag_injection_attempts(
    archive_dir: Path,
    start_count: int,
    cycle: int,
    rule_count: int,
) -> tuple[int, int]:
    attempts = sorted(archive_dir.glob("attempt_*"))
    new_attempts = attempts[start_count:]
    first_idx = -1
    last_idx = -1
    for i, attempt_dir in enumerate(new_attempts[:rule_count]):
        meta = {"source": "alpha_diagnosis", "cycle": cycle, "rule_index": i}
        (attempt_dir / "diagnosis_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        num = int(attempt_dir.name.split("_")[1])
        if first_idx < 0:
            first_idx = num
        last_idx = num
    return first_idx, last_idx


def _trajectory_session_fields(archive: Archive, config) -> dict[str, Any]:
    best = archive.best()
    return {
        "best_so_far": best.score if best else None,
        "best_attempt_id": best.attempt_id if best else None,
        "attempt_count": archive.submission_count(),
        "remaining": archive.remaining_improvements(config.max_improvements),
    }


def _run_evolution_monitored(
    workflow: WorkflowConfig,
    config_path: Path,
    *,
    resume: bool,
    fresh: bool,
    custom_prompt: str | None = None,
    verbose: bool = False,
    session_baseline_count: int | None = None,
    enable_stuck_monitor: bool = True,
) -> dict[str, Any]:
    config = load_config(config_path)
    workspace, archive, resumed_flag = setup_workspace(config, fresh=fresh)
    remaining = archive.remaining_improvements(config.max_improvements)
    if remaining <= 0 and custom_prompt is None:
        return {
            "status": "completed",
            "stopped_reason": None,
            "archive": archive,
            "config": config,
        }

    if custom_prompt is None:
        from agentic_evolve.prompt_builder import build_prompt

        prompt = build_prompt(
            archive,
            workspace,
            config.max_improvements,
            resumed=resumed_flag or resume,
            hidden_testdata=config.hidden_testdata,
            agent_readable_evaluator=config.agent_readable_evaluator,
        )
    else:
        prompt = custom_prompt

    sync_archive_to_trajectory(
        config.workspace_dir,
        config.archive_dir,
        maximize=config.maximize,
        event="backfill",
    )
    if session_baseline_count is None:
        session_baseline_count = archive.submission_count()
    record_event(
        config.workspace_dir,
        "session_start",
        mode="rule_injection" if custom_prompt else "evolution",
        session_baseline_count=session_baseline_count,
        **_trajectory_session_fields(archive, config),
    )

    _save_run_checkpoint(str(config_path), config, archive, status="running")
    runner = OpenCodeRunner(
        command=config.opencode.command,
        args=config.opencode.resolved_args(),
        verbose=config.verbose or verbose,
    )
    if enable_stuck_monitor:
        result = run_with_stuck_monitor(
            runner,
            str(workspace),
            prompt,
            config.agent_timeout_seconds,
            config.archive_dir,
            config.maximize,
            workflow.stuck,
            session_baseline_count=session_baseline_count,
        )
    else:
        result = runner.run(str(workspace), prompt, config.agent_timeout_seconds)

    archive = Archive(config.archive_dir, config.maximize)
    remaining = archive.remaining_improvements(config.max_improvements)
    status = "completed" if remaining <= 0 else "paused"
    sync_archive_to_trajectory(
        config.workspace_dir,
        config.archive_dir,
        maximize=config.maximize,
    )
    record_event(
        config.workspace_dir,
        "session_end",
        status=status,
        stopped_reason=result.stopped_reason,
        **_trajectory_session_fields(archive, config),
    )
    _save_run_checkpoint(str(config_path), config, archive, status=status)
    save_best_program(archive, config.best_program_path, config.initial_program)
    return {
        "status": status,
        "stopped_reason": result.stopped_reason,
        "result": result,
        "archive": archive,
        "config": config,
        "session_baseline_count": session_baseline_count,
    }


def _should_auto_resume(
    evo: dict[str, Any],
    *,
    auto_resume: bool,
    injection_start_count: int | None = None,
    injection_target: int | None = None,
) -> bool:
    if not auto_resume:
        return False
    if evo["stopped_reason"] == "stuck":
        return False
    if evo["status"] == "completed":
        return False

    config = evo["config"]
    archive: Archive = evo["archive"]
    remaining = archive.remaining_improvements(config.max_improvements)
    if remaining <= 0:
        return False

    if injection_start_count is not None and injection_target is not None:
        submitted = archive.submission_count() - injection_start_count
        if submitted >= injection_target:
            return False

    result = evo.get("result")
    if result is not None and not result.success:
        return False

    return True


def _run_evolution_until_stuck_or_done(
    workflow: WorkflowConfig,
    config_path: Path,
    *,
    resume: bool,
    fresh: bool,
    custom_prompt: str | None = None,
    prompt_factory: Callable[[], str] | None = None,
    verbose: bool = False,
    injection_start_count: int | None = None,
    injection_target: int | None = None,
) -> dict[str, Any]:
    """Run one or more OpenCode sessions until stuck, budget exhausted, or hard failure."""
    session_resume = resume
    use_fresh = fresh
    evo: dict[str, Any] | None = None
    stuck_baseline: int | None = None
    is_injection = injection_start_count is not None

    while True:
        prompt = prompt_factory() if prompt_factory is not None else custom_prompt
        evo = _run_evolution_monitored(
            workflow,
            config_path,
            resume=session_resume,
            fresh=use_fresh,
            custom_prompt=prompt,
            verbose=verbose,
            session_baseline_count=stuck_baseline,
            enable_stuck_monitor=not is_injection,
        )
        if stuck_baseline is None:
            stuck_baseline = int(evo["session_baseline_count"])
        session_resume = True
        use_fresh = False

        if not _should_auto_resume(
            evo,
            auto_resume=workflow.loop.auto_resume_on_early_exit,
            injection_start_count=injection_start_count,
            injection_target=injection_target,
        ):
            return evo

        remaining = evo["archive"].remaining_improvements(evo["config"].max_improvements)
        if verbose:
            print(
                f"agent exited early with {remaining} improvement(s) remaining; "
                f"auto-resuming (stuck baseline={stuck_baseline})...",
                flush=True,
            )
        record_event(
            evo["config"].workspace_dir,
            "auto_resume",
            mode="rule_injection" if prompt_factory or custom_prompt else "evolution",
            session_baseline_count=stuck_baseline,
            **_trajectory_session_fields(evo["archive"], evo["config"]),
        )


def run_workflow(workflow_path: Path, *, resume: bool = False, verbose: bool = False) -> int:
    workflow = load_workflow(workflow_path)
    if workflow.adapter.trajectory_format == "none":
        raise ValueError(f"Adapter {workflow.adapter.task_id} does not support trajectory-based diagnosis")

    primary_cfg_path = _resolve_primary_config(workflow)
    primary_cfg = load_config(primary_cfg_path)
    state = AlphaState.load(_state_path(primary_cfg.workspace_dir))
    state.workflow_name = workflow.name

    cycle = state.cycle
    should_resume = resume or cycle > 0 or state.cycle > 0

    while cycle < workflow.loop.max_diagnosis_cycles:
        evo = _run_evolution_until_stuck_or_done(
            workflow,
            primary_cfg_path,
            resume=should_resume,
            fresh=False,
            verbose=verbose,
        )
        archive: Archive = evo["archive"]
        if evo["stopped_reason"] != "stuck":
            state.save(_state_path(primary_cfg.workspace_dir))
            return 0

        record_event(
            primary_cfg.workspace_dir,
            "discovery_start",
            cycle=cycle + 1,
            **_trajectory_session_fields(archive, primary_cfg),
        )

        if workflow.discovery is None:
            break

        cycle += 1
        discovery = run_discovery_cycle(
            workflow,
            primary_cfg_path,
            primary_cfg.archive_dir,
            primary_cfg.workspace_dir,
            cycle,
            verbose=verbose,
        )
        save_discovery_artifact(primary_cfg.workspace_dir, discovery)
        record_event(
            primary_cfg.workspace_dir,
            "discovery_end",
            cycle=cycle,
            discovery_project=discovery.project_name,
            discovery_best_score=discovery.best_score,
            discovery_best_attempt_id=discovery.best_attempt_id,
            rule_count=len(discovery.rules),
        )
        state.discovery_history.append(
            {
                "cycle": cycle,
                "project_name": discovery.project_name,
                "best_score": discovery.best_score,
                "best_attempt_id": discovery.best_attempt_id,
            }
        )
        best = archive.best()
        state.last_diagnosis_after_attempt = (
            int(best.attempt_id.split("_")[1]) if best else state.last_diagnosis_after_attempt
        )

        validate_injection_config(workflow.injection, len(discovery.rules))
        start_count = archive.submission_count()
        rule_count = len(discovery.rules)

        def _injection_prompt() -> str:
            current = Archive(primary_cfg.archive_dir, primary_cfg.maximize)
            return build_rule_guided_prompt(
                workflow,
                current,
                primary_cfg.workspace_dir,
                primary_cfg.max_improvements,
                discovery.rules,
                resumed=True,
                agent_readable_evaluator=primary_cfg.agent_readable_evaluator,
                hidden_testdata=primary_cfg.hidden_testdata,
            )

        _run_evolution_until_stuck_or_done(
            workflow,
            primary_cfg_path,
            resume=True,
            fresh=False,
            prompt_factory=_injection_prompt,
            verbose=verbose,
            injection_start_count=start_count,
            injection_target=rule_count,
        )
        archive = Archive(primary_cfg.archive_dir, primary_cfg.maximize)
        first_idx, last_idx = _tag_injection_attempts(
            primary_cfg.archive_dir,
            start_count,
            cycle,
            len(discovery.rules),
        )
        if first_idx >= 0:
            state.rule_inspired_ranges.append(
                {"cycle": cycle, "first": first_idx, "last": last_idx}
            )
        state.cycle = cycle
        state.save(_state_path(primary_cfg.workspace_dir))
        should_resume = True

        if not workflow.loop.resume_after_injection:
            break

    state.save(_state_path(primary_cfg.workspace_dir))
    return 0
