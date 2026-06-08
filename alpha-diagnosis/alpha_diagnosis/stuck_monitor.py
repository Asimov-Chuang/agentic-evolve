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


def is_stuck(
    archive: Archive,
    cfg: StuckConfig,
    maximize: bool,
    *,
    session_baseline_count: int = 0,
) -> bool:
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
) -> RunResult:
    pid_holder: list[int] = []
    result_holder: list[RunResult] = []
    stop_event = threading.Event()
    workspace = Path(workspace_dir).resolve()
    watcher = TrajectoryWatcher(workspace, archive_dir, maximize=maximize)

    def _run():
        result_holder.append(
            runner.run(workspace_dir, prompt, timeout_seconds, pid_holder=pid_holder)
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
                session_baseline_count=session_baseline_count,
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
