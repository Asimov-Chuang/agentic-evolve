from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agentic_evolve.archive import Archive, read_improvement_baseline, save_best_program
from agentic_evolve.checkpoint import save_run_checkpoint
from agentic_evolve.config import Config, load_config
from agentic_evolve.opencode_runner import OpenCodeRunner, RunResult
from agentic_evolve.opencode_session import (
    backfill_session_id_from_logs,
    load_session_id,
    update_session_id_from_output,
)
from agentic_evolve.prompt_builder import build_continuation_prompt, build_prompt
from agentic_evolve.score_trajectory import record_event, sync_archive_to_trajectory
from agentic_evolve.workspace import setup_workspace


def _trajectory_session_fields(archive: Archive, config: Config) -> dict[str, Any]:
    best = archive.best()
    baseline = read_improvement_baseline(config.workspace_dir)
    return {
        "best_so_far": best.score if best else None,
        "best_attempt_id": best.attempt_id if best else None,
        "attempt_count": archive.submission_count(),
        "remaining": archive.remaining_improvements(config.max_improvements, baseline=baseline),
        "improvement_baseline_count": baseline,
    }


def run_opencode(
    config: Config,
    workspace: Path,
    prompt: str,
    *,
    verbose: bool,
    continue_session: bool = False,
    session_id: str | None = None,
    append_logs: bool = False,
    r2_threshold: float | None = None,
    poll_interval_seconds: int = 30,
) -> RunResult:
    return _run_opencode(
        config,
        workspace,
        prompt,
        verbose=verbose,
        continue_session=continue_session,
        session_id=session_id,
        append_logs=append_logs,
        r2_threshold=r2_threshold,
        poll_interval_seconds=poll_interval_seconds,
    )


def _run_opencode(
    config: Config,
    workspace: Path,
    prompt: str,
    *,
    verbose: bool,
    continue_session: bool = False,
    session_id: str | None = None,
    append_logs: bool = False,
    r2_threshold: float | None = None,
    poll_interval_seconds: int = 30,
) -> RunResult:
    runner = OpenCodeRunner(
        command=config.opencode.command,
        args=config.opencode.resolved_args(),
        verbose=config.verbose or verbose,
    )
    with _opencode_config_env(config):
        if r2_threshold is not None:
            from agentic_evolve.r2_monitor import run_with_r2_threshold_monitor

            return run_with_r2_threshold_monitor(
                runner,
                str(workspace),
                prompt,
                config.agent_timeout_seconds,
                config.archive_dir,
                config.maximize,
                r2_threshold=r2_threshold,
                poll_interval_seconds=poll_interval_seconds,
            )
        return runner.run(
            str(workspace),
            prompt,
            config.agent_timeout_seconds,
            continue_session=continue_session,
            session_id=session_id,
            append_logs=append_logs,
        )


@contextmanager
def _opencode_config_env(config: Config):
    env_updates: dict[str, str] = {}
    if config.opencode_config is not None:
        env_updates["OPENCODE_CONFIG"] = str(config.opencode_config.resolve())
    if config.opencode.model:
        env_updates["CLOUDGPT_MODEL"] = config.opencode.model
    if config.opencode.small_model:
        env_updates["CLOUDGPT_SMALL_MODEL"] = config.opencode.small_model
    elif config.opencode.model:
        env_updates["CLOUDGPT_SMALL_MODEL"] = config.opencode.model

    if not env_updates:
        yield
        return

    previous = {key: os.environ.get(key) for key in env_updates}
    os.environ.update(env_updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_evolution_session(
    config_path: str | Path,
    *,
    resume: bool = False,
    fresh: bool = False,
    from_checkpoint: str | None = None,
    custom_prompt: str | None = None,
    verbose: bool = False,
    session_baseline_count: int | None = None,
    session_mode: str = "evolution",
    r2_threshold: float | None = None,
    poll_interval_seconds: int = 30,
) -> dict[str, Any]:
    """Run one OpenCode evolution session in a workspace."""
    config_path = Path(config_path)
    config = load_config(config_path)
    workspace, archive, resumed_flag = setup_workspace(
        config,
        fresh=fresh,
        from_checkpoint=from_checkpoint,
    )
    baseline = read_improvement_baseline(config.workspace_dir)
    remaining = archive.remaining_improvements(config.max_improvements, baseline=baseline)
    if remaining <= 0 and custom_prompt is None:
        return {
            "status": "completed",
            "stopped_reason": None,
            "archive": archive,
            "config": config,
            "session_baseline_count": archive.submission_count(),
        }

    is_workspace_resume = (resumed_flag or resume) and not fresh
    use_opencode_continue = (
        custom_prompt is None
        and is_workspace_resume
        and config.auto_resume_mode == "continue"
    )

    session_id = load_session_id(workspace)
    if use_opencode_continue:
        session_id = backfill_session_id_from_logs(workspace) or session_id

    if use_opencode_continue:
        prompt = build_continuation_prompt(
            archive,
            workspace,
            config.max_improvements,
            mode=config.mode,
            target_score=config.target_score,
            maximize=config.maximize,
        )
    elif custom_prompt is None:
        prompt = build_prompt(
            archive,
            workspace,
            config.max_improvements,
            resumed=is_workspace_resume,
            hidden_testdata=config.hidden_testdata,
            agent_readable_evaluator=config.agent_readable_evaluator,
            prompt_history_top_n=config.prompt_history_top_n,
            prompt_history_recent_n=config.prompt_history_recent_n,
            prompt_history_max_feedback_chars=config.prompt_history_max_feedback_chars,
            mode=config.mode,
            target_score=config.target_score,
            maximize=config.maximize,
        )
    else:
        prompt = custom_prompt

    (workspace / "prompt.md").write_text(prompt, encoding="utf-8")

    sync_archive_to_trajectory(
        config.workspace_dir,
        config.archive_dir,
        maximize=config.maximize,
        event="backfill",
    )
    if session_baseline_count is None:
        session_baseline_count = archive.submission_count()
    resume_mode: str | None = None
    if use_opencode_continue:
        resume_mode = "session" if session_id else "continue"
    elif is_workspace_resume:
        resume_mode = "new_session"

    record_event(
        config.workspace_dir,
        "session_start",
        mode=session_mode,
        session_baseline_count=session_baseline_count,
        resume_mode=resume_mode,
        **_trajectory_session_fields(archive, config),
    )

    save_run_checkpoint(str(config_path), config, archive, status="running")
    result = _run_opencode(
        config,
        workspace,
        prompt,
        verbose=verbose,
        continue_session=use_opencode_continue and session_id is None,
        session_id=session_id if use_opencode_continue else None,
        append_logs=use_opencode_continue,
        r2_threshold=r2_threshold,
        poll_interval_seconds=poll_interval_seconds,
    )
    update_session_id_from_output(workspace, result.stdout, result.stderr)

    archive = Archive(config.archive_dir, config.maximize)
    baseline = read_improvement_baseline(config.workspace_dir)
    remaining = archive.remaining_improvements(config.max_improvements, baseline=baseline)
    status = (
        "completed"
        if remaining <= 0 or result.stopped_reason == "r2_threshold"
        else "paused"
    )
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
        resume_mode=resume_mode,
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


def run_evolution_continuation(
    config_path: str | Path,
    *,
    verbose: bool = False,
    session_baseline_count: int | None = None,
    session_mode: str = "evolution",
    r2_threshold: float | None = None,
    poll_interval_seconds: int = 30,
) -> dict[str, Any]:
    """Continue the same OpenCode session after an early agent exit."""
    config_path = Path(config_path)
    config = load_config(config_path)
    workspace, archive, _resumed_flag = setup_workspace(config, fresh=False)
    baseline = read_improvement_baseline(config.workspace_dir)
    remaining = archive.remaining_improvements(config.max_improvements, baseline=baseline)
    if remaining <= 0:
        return {
            "status": "completed",
            "stopped_reason": None,
            "archive": archive,
            "config": config,
            "session_baseline_count": session_baseline_count or archive.submission_count(),
        }

    prompt = build_continuation_prompt(
        archive,
        workspace,
        config.max_improvements,
        mode=config.mode,
        target_score=config.target_score,
        maximize=config.maximize,
    )
    (workspace / "prompt.md").write_text(prompt, encoding="utf-8")

    sync_archive_to_trajectory(
        config.workspace_dir,
        config.archive_dir,
        maximize=config.maximize,
    )
    if session_baseline_count is None:
        session_baseline_count = archive.submission_count()

    session_id = backfill_session_id_from_logs(workspace) or load_session_id(workspace)
    result = _run_opencode(
        config,
        workspace,
        prompt,
        verbose=verbose,
        continue_session=session_id is None,
        session_id=session_id,
        append_logs=True,
        r2_threshold=r2_threshold,
        poll_interval_seconds=poll_interval_seconds,
    )
    update_session_id_from_output(workspace, result.stdout, result.stderr)

    archive = Archive(config.archive_dir, config.maximize)
    remaining = archive.remaining_improvements(config.max_improvements, baseline=baseline)
    status = (
        "completed"
        if remaining <= 0 or result.stopped_reason == "r2_threshold"
        else "paused"
    )
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
        resume_mode="continue",
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


def should_auto_resume_session(
    evo: dict[str, Any],
    *,
    auto_resume: bool,
) -> bool:
    if not auto_resume:
        return False
    if evo.get("stopped_reason") in ("stuck", "injection_quota", "r2_threshold"):
        return False
    if evo["status"] == "completed":
        return False

    config: Config = evo["config"]
    archive: Archive = evo["archive"]
    baseline = read_improvement_baseline(config.workspace_dir)
    remaining = archive.remaining_improvements(config.max_improvements, baseline=baseline)
    if remaining <= 0:
        return False

    result = evo.get("result")
    if result is not None and not result.success:
        return False

    return True


def run_evolution_until_done(
    config_path: str | Path,
    *,
    resume: bool = False,
    fresh: bool = False,
    from_checkpoint: str | None = None,
    custom_prompt: str | None = None,
    prompt_factory: Any | None = None,
    verbose: bool = False,
    auto_resume: bool = True,
    session_mode: str = "evolution",
    r2_threshold: float | None = None,
    poll_interval_seconds: int = 30,
) -> dict[str, Any]:
    """Run one or more OpenCode turns until budget exhausted or hard failure."""
    config = load_config(config_path)
    session_resume = resume
    use_fresh = fresh
    checkpoint_restore = from_checkpoint
    evo: dict[str, Any] | None = None
    session_baseline_count: int | None = None
    use_continue = auto_resume and config.auto_resume_mode == "continue"

    while True:
        if evo is None:
            prompt = prompt_factory() if prompt_factory is not None else custom_prompt
            evo = run_evolution_session(
                config_path,
                resume=session_resume,
                fresh=use_fresh,
                from_checkpoint=checkpoint_restore,
                custom_prompt=prompt,
                verbose=verbose,
                session_mode=session_mode,
                r2_threshold=r2_threshold,
                poll_interval_seconds=poll_interval_seconds,
            )
            session_baseline_count = evo.get("session_baseline_count")
            if evo.get("stopped_reason") == "r2_threshold":
                return evo
        elif use_continue:
            if verbose:
                remaining = evo["archive"].remaining_improvements(
                    evo["config"].max_improvements,
                    baseline=read_improvement_baseline(evo["config"].workspace_dir),
                )
                print(
                    f"agent exited early with {remaining} improvement(s) remaining; "
                    "continuing same OpenCode session...",
                    flush=True,
                )
            record_event(
                evo["config"].workspace_dir,
                "auto_resume",
                mode=session_mode,
                resume_mode="continue",
                session_baseline_count=session_baseline_count,
                **_trajectory_session_fields(evo["archive"], evo["config"]),
            )
            evo = run_evolution_continuation(
                config_path,
                verbose=verbose,
                session_baseline_count=session_baseline_count,
                session_mode=session_mode,
                r2_threshold=r2_threshold,
                poll_interval_seconds=poll_interval_seconds,
            )
            if evo.get("stopped_reason") == "r2_threshold":
                return evo
        else:
            if verbose:
                remaining = evo["archive"].remaining_improvements(
                    evo["config"].max_improvements,
                    baseline=read_improvement_baseline(evo["config"].workspace_dir),
                )
                print(
                    f"agent exited early with {remaining} improvement(s) remaining; "
                    "starting a new OpenCode session...",
                    flush=True,
                )
            record_event(
                evo["config"].workspace_dir,
                "auto_resume",
                mode=session_mode,
                resume_mode="new_session",
                session_baseline_count=session_baseline_count,
                **_trajectory_session_fields(evo["archive"], evo["config"]),
            )
            prompt = prompt_factory() if prompt_factory is not None else custom_prompt
            evo = run_evolution_session(
                config_path,
                resume=True,
                fresh=False,
                custom_prompt=prompt,
                verbose=verbose,
                session_baseline_count=session_baseline_count,
                session_mode=session_mode,
                r2_threshold=r2_threshold,
                poll_interval_seconds=poll_interval_seconds,
            )
            if evo.get("stopped_reason") == "r2_threshold":
                return evo

        session_resume = True
        use_fresh = False
        checkpoint_restore = None

        if not should_auto_resume_session(evo, auto_resume=auto_resume):
            return evo
