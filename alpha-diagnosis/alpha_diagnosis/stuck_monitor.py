from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from agentic_evolve.archive import Archive
from agentic_evolve.opencode_runner import OpenCodeRunner, RunResult
from agentic_evolve.score_trajectory import TrajectoryWatcher, record_event

from alpha_diagnosis.config_schema import StuckConfig


def consecutive_no_improvement(
    archive: Archive,
    maximize: bool,
    *,
    session_baseline_count: int = 0,
) -> int:
    """Trailing attempts since the last strict best-score improvement.

    When ``session_baseline_count`` is set, only submissions after that
    archive size count toward the streak (session-scoped stuck detection).
    """
    attempts = archive.list_attempts()
    baseline = max(0, session_baseline_count)
    if len(attempts) <= baseline:
        return 0

    running_best: float | None = None
    for attempt in attempts[:baseline]:
        if not attempt.is_valid:
            continue
        score = attempt.score
        if running_best is None:
            running_best = score
            continue
        improved = score > running_best if maximize else score < running_best
        if improved:
            running_best = score

    streak = 0
    for attempt in attempts[baseline:]:
        if not attempt.is_valid:
            streak += 1
            continue

        score = attempt.score
        if running_best is None:
            running_best = score
            streak = 0
            continue

        improved = score > running_best if maximize else score < running_best
        if improved:
            running_best = score
            streak = 0
        else:
            streak += 1

    return streak


def session_submission_count(archive: Archive, session_baseline_count: int) -> int:
    """Agent submissions in the current evolution session (after baseline)."""
    return max(0, archive.submission_count() - max(0, session_baseline_count))


def is_stuck(
    archive: Archive,
    cfg: StuckConfig,
    maximize: bool,
    *,
    session_baseline_count: int = 0,
) -> bool:
    if session_submission_count(archive, session_baseline_count) < cfg.min_attempts_before_stuck:
        return False
    return (
        consecutive_no_improvement(
            archive,
            maximize,
            session_baseline_count=session_baseline_count,
        )
        >= cfg.consecutive_no_improvement
    )


def _terminate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_with_stuck_monitor(
    runner: OpenCodeRunner,
    workspace_dir: str,
    prompt: str,
    timeout_seconds: int,
    archive_dir: Path,
    maximize: bool,
    cfg: StuckConfig,
    *,
    session_baseline_count: int = 0,
    continue_session: bool = False,
    session_id: str | None = None,
    append_logs: bool = False,
) -> RunResult:
    pid_holder: list[int] = []
    result_holder: list[RunResult] = []
    stop_event = threading.Event()
    workspace = Path(workspace_dir).resolve()
    watcher = TrajectoryWatcher(workspace, archive_dir, maximize=maximize)

    def _run():
        result_holder.append(
            runner.run(
                workspace_dir,
                prompt,
                timeout_seconds,
                pid_holder=pid_holder,
                continue_session=continue_session,
                session_id=session_id,
                append_logs=append_logs,
            )
        )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    while thread.is_alive():
        time.sleep(cfg.poll_interval_seconds)
        watcher.sync()
        if not pid_holder:
            continue
        archive = Archive(archive_dir, maximize)
        if is_stuck(
            archive,
            cfg,
            maximize,
            session_baseline_count=session_baseline_count,
        ):
            best = archive.best()
            streak = consecutive_no_improvement(
                archive,
                maximize,
                session_baseline_count=session_baseline_count,
            )
            record_event(
                workspace,
                "stuck",
                consecutive_no_improvement=streak,
                threshold=cfg.consecutive_no_improvement,
                min_attempts_before_stuck=cfg.min_attempts_before_stuck,
                session_baseline_count=session_baseline_count,
                session_submissions=session_submission_count(archive, session_baseline_count),
                best_so_far=best.score if best else None,
                best_attempt_id=best.attempt_id if best else None,
                attempt_count=archive.submission_count(),
            )
            stop_event.set()
            _terminate_pid(pid_holder[0])
            break

    thread.join(timeout=timeout_seconds + 120)
    if not result_holder:
        return RunResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr="",
            error="OpenCode run did not return",
            stopped_reason="stuck" if stop_event.is_set() else None,
        )

    result = result_holder[0]
    if stop_event.is_set():
        result.stopped_reason = "stuck"
        result.success = False
        if not result.error:
            result.error = "Stopped: score stuck"
    return result


def injection_submission_count(archive: Archive, injection_start_count: int) -> int:
    return max(0, archive.submission_count() - injection_start_count)


def is_injection_quota_reached(
    archive: Archive,
    injection_start_count: int,
    rule_count: int,
    *,
    quota_tolerance: int = 0,
) -> bool:
    submitted = injection_submission_count(archive, injection_start_count)
    return submitted >= rule_count + quota_tolerance


def run_with_injection_quota_monitor(
    runner: OpenCodeRunner,
    workspace_dir: str,
    prompt: str,
    timeout_seconds: int,
    archive_dir: Path,
    maximize: bool,
    *,
    poll_interval_seconds: int,
    injection_start_count: int,
    rule_count: int,
    quota_tolerance: int = 2,
    continue_session: bool = False,
    session_id: str | None = None,
    append_logs: bool = False,
) -> RunResult:
    """Poll archive during rule injection and terminate when quota + tolerance is met."""
    pid_holder: list[int] = []
    result_holder: list[RunResult] = []
    stop_event = threading.Event()
    workspace = Path(workspace_dir).resolve()
    watcher = TrajectoryWatcher(workspace, archive_dir, maximize=maximize)
    hard_limit = rule_count + quota_tolerance

    def _run():
        result_holder.append(
            runner.run(
                workspace_dir,
                prompt,
                timeout_seconds,
                pid_holder=pid_holder,
                continue_session=continue_session,
                session_id=session_id,
                append_logs=append_logs,
            )
        )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    while thread.is_alive():
        time.sleep(poll_interval_seconds)
        watcher.sync()
        if not pid_holder:
            continue
        archive = Archive(archive_dir, maximize)
        submitted = injection_submission_count(archive, injection_start_count)
        if is_injection_quota_reached(
            archive,
            injection_start_count,
            rule_count,
            quota_tolerance=quota_tolerance,
        ):
            best = archive.best()
            record_event(
                workspace,
                "injection_quota",
                submitted=submitted,
                rule_count=rule_count,
                quota_tolerance=quota_tolerance,
                hard_limit=hard_limit,
                injection_start_count=injection_start_count,
                best_so_far=best.score if best else None,
                best_attempt_id=best.attempt_id if best else None,
                attempt_count=archive.submission_count(),
            )
            stop_event.set()
            _terminate_pid(pid_holder[0])
            break

    thread.join(timeout=timeout_seconds + 120)
    if not result_holder:
        return RunResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr="",
            error="OpenCode run did not return",
            stopped_reason="injection_quota" if stop_event.is_set() else None,
        )

    result = result_holder[0]
    if stop_event.is_set():
        result.stopped_reason = "injection_quota"
        result.success = False
        if not result.error:
            result.error = (
                f"Stopped: injection quota reached ({hard_limit} submissions "
                f"= {rule_count} rules + {quota_tolerance} tolerance)"
            )
    return result
