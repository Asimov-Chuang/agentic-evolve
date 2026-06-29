from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from agentic_evolve.archive import Archive
from agentic_evolve.opencode_runner import OpenCodeRunner, RunResult
from agentic_evolve.score_trajectory import TrajectoryWatcher, record_event


def best_r2_in_archive(archive: Archive) -> float | None:
    """Highest R² among valid attempts (from metrics.r2 in rule-discovery evaluators)."""
    best: float | None = None
    for attempt in archive.list_attempts():
        if not attempt.is_valid:
            continue
        r2 = attempt.metrics.get("r2")
        if r2 is None:
            continue
        try:
            r2f = float(r2)
        except (TypeError, ValueError):
            continue
        if best is None or r2f > best:
            best = r2f
    return best


def is_r2_threshold_met(archive: Archive, threshold: float) -> bool:
    best_r2 = best_r2_in_archive(archive)
    return best_r2 is not None and best_r2 >= threshold


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


def run_with_r2_threshold_monitor(
    runner: OpenCodeRunner,
    workspace_dir: str,
    prompt: str,
    timeout_seconds: int,
    archive_dir: Path,
    maximize: bool,
    *,
    r2_threshold: float,
    poll_interval_seconds: int,
) -> RunResult:
    """Poll archive during rule discovery and stop when best R² meets threshold."""
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
        time.sleep(poll_interval_seconds)
        watcher.sync()
        if not pid_holder:
            continue
        archive = Archive(archive_dir, maximize)
        if is_r2_threshold_met(archive, r2_threshold):
            best_r2 = best_r2_in_archive(archive)
            best = archive.best()
            record_event(
                workspace,
                "discovery_r2_threshold",
                r2=best_r2,
                threshold=r2_threshold,
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
            stopped_reason="r2_threshold" if stop_event.is_set() else None,
        )

    result = result_holder[0]
    if stop_event.is_set():
        result.stopped_reason = "r2_threshold"
        result.success = False
        best_r2 = best_r2_in_archive(Archive(archive_dir, maximize))
        if not result.error:
            result.error = (
                f"Stopped: discovery R² threshold reached "
                f"(best R²={best_r2:.4f} >= {r2_threshold:.4f})"
            )
    return result
