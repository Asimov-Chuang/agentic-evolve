from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List

import yaml

from agentic_evolve.archive import Archive, save_best_program
from agentic_evolve.checkpoint import save_run_checkpoint
from agentic_evolve.config import load_config
from agentic_evolve.opencode_runner import OpenCodeRunner
from agentic_evolve.opencode_session import load_session_id, update_session_id_from_output
from agentic_evolve.score_trajectory import record_event, sync_archive_to_trajectory
from agentic_evolve.workspace import setup_workspace

from alpha_diagnosis.config_schema import ForkConfig, WorkflowConfig, load_workflow
from alpha_diagnosis.discovery import run_discovery_cycle, save_discovery_artifact
from alpha_diagnosis.fork import fork_workspace
from alpha_diagnosis.history_review import run_history_review_cycle, save_history_review_artifact
from alpha_diagnosis.prompt_builder import (
    build_primary_continuation_prompt,
    build_rule_guided_prompt,
    injection_quota_target,
    validate_injection_config,
)
from alpha_diagnosis.stuck_monitor import (
    injection_submission_count,
    run_with_injection_quota_monitor,
    run_with_stuck_monitor,
)

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
    needs_derived = (
        workflow.primary.project_name is not None
        or workflow.store_raw_artifacts is not None
        or workflow.primary.store_raw_artifacts is not None
    )
    if not needs_derived:
        return workflow.primary.config_path
    original = workflow.primary.config_path.resolve()
    config_dir = original.parent
    with open(original, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if workflow.primary.project_name:
        raw["project_name"] = workflow.primary.project_name
    if workflow.store_raw_artifacts is not None:
        raw["store_raw_artifacts"] = workflow.store_raw_artifacts
    if workflow.primary.store_raw_artifacts is not None:
        raw["store_raw_artifacts"] = workflow.primary.store_raw_artifacts
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
    *,
    mode: str = "per_rule_variants",
    tag_limit: int | None = None,
) -> tuple[int, int]:
    attempts = sorted(archive_dir.glob("attempt_*"))
    new_attempts = attempts[start_count:]
    if mode == "pro":
        to_tag = new_attempts if tag_limit is None else new_attempts[:tag_limit]
    else:
        limit = tag_limit if tag_limit is not None else rule_count
        to_tag = new_attempts[:limit]
    first_idx = -1
    last_idx = -1
    for i, attempt_dir in enumerate(to_tag):
        if mode == "pro":
            meta = {"source": "alpha_diagnosis", "cycle": cycle, "mode": "pro", "proposal_index": i}
        elif mode == "counterfactual":
            meta = {
                "source": "alpha_diagnosis",
                "cycle": cycle,
                "mode": "counterfactual",
                "rule_index": i,
            }
        else:
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
    injection_start_count: int | None = None,
    injection_rule_count: int | None = None,
    injection_quota_tolerance: int = 2,
    continue_opencode_session: bool = False,
    append_opencode_logs: bool = False,
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
            prompt_history_top_n=config.prompt_history_top_n,
            prompt_history_recent_n=config.prompt_history_recent_n,
            prompt_history_max_feedback_chars=config.prompt_history_max_feedback_chars,
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

    save_run_checkpoint(str(config_path), config, archive, status="running")
    runner = OpenCodeRunner(
        command=config.opencode.command,
        args=config.opencode.resolved_args(),
        verbose=config.verbose or verbose,
    )
    session_id = load_session_id(workspace) if continue_opencode_session else None
    use_continue = continue_opencode_session and session_id is None
    append_logs = append_opencode_logs or (
        continue_opencode_session and session_id is not None
    )
    run_kwargs = {
        "continue_session": use_continue,
        "session_id": session_id,
        "append_logs": append_logs,
    }
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
            **run_kwargs,
        )
    elif injection_start_count is not None and injection_rule_count is not None:
        result = run_with_injection_quota_monitor(
            runner,
            str(workspace),
            prompt,
            config.agent_timeout_seconds,
            config.archive_dir,
            config.maximize,
            poll_interval_seconds=workflow.stuck.poll_interval_seconds,
            injection_start_count=injection_start_count,
            rule_count=injection_rule_count,
            quota_tolerance=injection_quota_tolerance,
            **run_kwargs,
        )
    else:
        result = runner.run(
            str(workspace),
            prompt,
            config.agent_timeout_seconds,
            **run_kwargs,
        )

    update_session_id_from_output(workspace, result.stdout, result.stderr)

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
    save_run_checkpoint(str(config_path), config, archive, status=status)
    save_best_program(archive, config.best_program_path, config.initial_program)
    return {
        "status": status,
        "stopped_reason": result.stopped_reason,
        "result": result,
        "archive": archive,
        "config": config,
        "session_baseline_count": session_baseline_count,
    }


from agentic_evolve.session import should_auto_resume_session as _should_auto_resume_session


def _should_auto_resume(
    evo: dict[str, Any],
    *,
    auto_resume: bool,
    injection_start_count: int | None = None,
    injection_target: int | None = None,
) -> bool:
    if injection_start_count is not None and injection_target is not None:
        config = evo["config"]
        archive: Archive = evo["archive"]
        submitted = injection_submission_count(archive, injection_start_count)
        if submitted >= injection_target:
            return False
    return _should_auto_resume_session(evo, auto_resume=auto_resume)


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
    initial_continue_opencode: bool = False,
    use_continuation_on_auto_resume: bool = False,
) -> dict[str, Any]:
    """Run one or more OpenCode sessions until stuck, budget exhausted, or hard failure."""
    shared = workflow.loop.shared_opencode_session
    session_resume = resume
    use_fresh = fresh
    evo: dict[str, Any] | None = None
    stuck_baseline: int | None = None
    is_injection = injection_start_count is not None
    injection_tol = workflow.injection.quota_tolerance if is_injection else 2
    first_opencode = True

    while True:
        if evo is not None and use_continuation_on_auto_resume and shared:
            config = load_config(config_path)
            archive = Archive(config.archive_dir, config.maximize)
            if is_injection and prompt_factory is not None:
                prompt = prompt_factory()
            elif not is_injection:
                from agentic_evolve.prompt_builder import build_continuation_prompt

                prompt = build_continuation_prompt(
                    archive,
                    config.workspace_dir,
                    config.max_improvements,
                    mode=config.mode,
                )
            else:
                prompt = custom_prompt
        else:
            prompt = prompt_factory() if prompt_factory is not None else custom_prompt

        continue_oc = False
        append_logs = False
        if shared:
            config = load_config(config_path)
            sid = load_session_id(config.workspace_dir)
            if first_opencode:
                continue_oc = initial_continue_opencode or (session_resume and sid is not None)
                append_logs = continue_oc and sid is not None
            else:
                continue_oc = True
                append_logs = True

        evo = _run_evolution_monitored(
            workflow,
            config_path,
            resume=session_resume,
            fresh=use_fresh,
            custom_prompt=prompt,
            verbose=verbose,
            session_baseline_count=stuck_baseline,
            enable_stuck_monitor=not is_injection,
            injection_start_count=injection_start_count,
            injection_rule_count=injection_target,
            injection_quota_tolerance=injection_tol,
            continue_opencode_session=continue_oc,
            append_opencode_logs=append_logs,
        )
        first_opencode = False
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
            mode_label = "continuing same OpenCode session" if shared else "auto-resuming"
            print(
                f"agent exited early with {remaining} improvement(s) remaining; "
                f"{mode_label} (stuck baseline={stuck_baseline})...",
                flush=True,
            )
        record_event(
            evo["config"].workspace_dir,
            "auto_resume",
            mode="rule_injection" if prompt_factory or custom_prompt else "evolution",
            resume_mode="continue" if shared else "new_session",
            session_baseline_count=stuck_baseline,
            **_trajectory_session_fields(evo["archive"], evo["config"]),
        )


def _resolve_fork(
    workflow: WorkflowConfig,
    *,
    fork_from: Path | None,
    fork_at_stuck: int | None,
    fork_at_attempt: int | None,
) -> ForkConfig | None:
    if fork_from is not None:
        if fork_at_stuck is not None and fork_at_attempt is not None:
            raise ValueError("Specify only one of fork_at_stuck or fork_at_attempt")
        if fork_at_stuck is None and fork_at_attempt is None:
            raise ValueError("--fork-from requires --fork-at-stuck or --fork-at-attempt")
        start_at_diagnosis = fork_at_stuck is not None
        return ForkConfig(
            source_workspace=fork_from.resolve(),
            at_stuck_cycle=fork_at_stuck,
            at_attempt=fork_at_attempt,
            start_at_diagnosis=start_at_diagnosis,
        )
    return workflow.fork


def run_workflow(
    workflow_path: Path,
    *,
    resume: bool = False,
    verbose: bool = False,
    fork_from: Path | None = None,
    fork_at_stuck: int | None = None,
    fork_at_attempt: int | None = None,
) -> int:
    workflow = load_workflow(workflow_path)
    if workflow.adapter.trajectory_format == "none":
        raise ValueError(f"Adapter {workflow.adapter.task_id} does not support trajectory-based diagnosis")

    primary_cfg_path = _resolve_primary_config(workflow)
    primary_cfg = load_config(primary_cfg_path)

    fork_cfg = _resolve_fork(
        workflow,
        fork_from=fork_from,
        fork_at_stuck=fork_at_stuck,
        fork_at_attempt=fork_at_attempt,
    )
    skip_evolution_once = False
    if fork_cfg is not None:
        if verbose:
            print(f"Forking workspace from {fork_cfg.source_workspace}...", flush=True)
        fork_workspace(fork_cfg, primary_cfg, config_path=str(primary_cfg_path.resolve()))
        resume = True
        skip_evolution_once = fork_cfg.start_at_diagnosis
        if skip_evolution_once and verbose:
            print(
                "Fork point is a stuck checkpoint; skipping evolution and starting diagnosis.",
                flush=True,
            )

    state = AlphaState.load(_state_path(primary_cfg.workspace_dir))
    state.workflow_name = workflow.name

    cycle = state.cycle
    should_resume = resume or cycle > 0 or state.cycle > 0
    primary_after_injection = False

    while cycle < workflow.loop.max_diagnosis_cycles:
        if skip_evolution_once:
            skip_evolution_once = False
            primary_cfg = load_config(primary_cfg_path)
            archive = Archive(primary_cfg.archive_dir, primary_cfg.maximize)
            sync_archive_to_trajectory(
                primary_cfg.workspace_dir,
                primary_cfg.archive_dir,
                maximize=primary_cfg.maximize,
                event="backfill",
            )
            record_event(
                primary_cfg.workspace_dir,
                "stuck",
                consecutive_no_improvement=workflow.stuck.consecutive_no_improvement,
                threshold=workflow.stuck.consecutive_no_improvement,
                fork_immediate_diagnosis=True,
                **_trajectory_session_fields(archive, primary_cfg),
            )
            evo = {"stopped_reason": "stuck", "archive": archive}
        elif primary_after_injection and workflow.loop.shared_opencode_session:
            def _primary_after_injection_prompt() -> str:
                cfg = load_config(primary_cfg_path)
                current = Archive(cfg.archive_dir, cfg.maximize)
                return build_primary_continuation_prompt(
                    current,
                    cfg.workspace_dir,
                    cfg.max_improvements,
                    mode=cfg.mode,
                )

            evo = _run_evolution_until_stuck_or_done(
                workflow,
                primary_cfg_path,
                resume=True,
                fresh=False,
                prompt_factory=_primary_after_injection_prompt,
                verbose=verbose,
                initial_continue_opencode=True,
                use_continuation_on_auto_resume=True,
            )
            primary_after_injection = False
            archive = evo["archive"]
            if evo["stopped_reason"] != "stuck":
                state.save(_state_path(primary_cfg.workspace_dir))
                return 0
        else:
            evo = _run_evolution_until_stuck_or_done(
                workflow,
                primary_cfg_path,
                resume=should_resume,
                fresh=False,
                verbose=verbose,
                use_continuation_on_auto_resume=workflow.loop.shared_opencode_session,
            )
            archive = evo["archive"]
            if evo["stopped_reason"] != "stuck":
                state.save(_state_path(primary_cfg.workspace_dir))
                return 0

        discovery_mode = (
            workflow.discovery.mode if workflow.discovery is not None else None
        )
        record_event(
            primary_cfg.workspace_dir,
            "discovery_start",
            cycle=cycle + 1,
            discovery_mode=discovery_mode,
            **_trajectory_session_fields(archive, primary_cfg),
        )

        if workflow.discovery is None:
            break

        cycle += 1
        if workflow.discovery.mode == "agent_review":
            discovery = run_history_review_cycle(
                workflow,
                primary_cfg_path,
                primary_cfg.archive_dir,
                primary_cfg.workspace_dir,
                cycle,
                verbose=verbose,
            )
            save_history_review_artifact(primary_cfg.workspace_dir, discovery)
        else:
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
            discovery_mode=workflow.discovery.mode,
            discovery_project=discovery.project_name,
            discovery_best_score=discovery.best_score,
            discovery_best_attempt_id=discovery.best_attempt_id,
            rule_count=len(discovery.rules),
        )
        state.discovery_history.append(
            {
                "cycle": cycle,
                "mode": workflow.discovery.mode,
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
        quota_target = injection_quota_target(workflow.injection, rule_count)

        shared_session = workflow.loop.shared_opencode_session

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
                prompt_history_top_n=primary_cfg.prompt_history_top_n,
                prompt_history_recent_n=primary_cfg.prompt_history_recent_n,
                prompt_history_max_feedback_chars=primary_cfg.prompt_history_max_feedback_chars,
                cycle=cycle,
                continuation=shared_session,
            )

        _run_evolution_until_stuck_or_done(
            workflow,
            primary_cfg_path,
            resume=True,
            fresh=False,
            prompt_factory=_injection_prompt,
            verbose=verbose,
            injection_start_count=start_count,
            injection_target=quota_target,
            initial_continue_opencode=shared_session,
            use_continuation_on_auto_resume=shared_session,
        )
        archive = Archive(primary_cfg.archive_dir, primary_cfg.maximize)
        first_idx, last_idx = _tag_injection_attempts(
            primary_cfg.archive_dir,
            start_count,
            cycle,
            rule_count,
            mode=workflow.injection.mode,
            tag_limit=quota_target if workflow.injection.mode == "pro" else None,
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

        primary_after_injection = workflow.loop.shared_opencode_session

    state.save(_state_path(primary_cfg.workspace_dir))
    return 0
