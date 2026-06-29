from __future__ import annotations

import json
import shutil
from pathlib import Path

from agentic_evolve.archive import Archive
from agentic_evolve.checkpoint import Checkpoint, save_checkpoint
from agentic_evolve.config import Config, load_config

from alpha_diagnosis.config_schema import ForkConfig


def _read_stuck_attempt_count(source_workspace: Path, stuck_cycle: int) -> int:
    trajectory_path = source_workspace / "score_trajectory.jsonl"
    if not trajectory_path.is_file():
        raise FileNotFoundError(f"score_trajectory.jsonl not found in {source_workspace}")

    stuck_events: list[int] = []
    with open(trajectory_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            if event.get("event") == "stuck":
                count = event.get("attempt_count")
                if count is not None:
                    stuck_events.append(int(count))

    if stuck_cycle < 1 or stuck_cycle > len(stuck_events):
        raise ValueError(
            f"at_stuck_cycle={stuck_cycle} out of range; "
            f"source has {len(stuck_events)} stuck event(s)"
        )
    return stuck_events[stuck_cycle - 1]


def _resolve_fork_attempt_count(fork: ForkConfig) -> int:
    if fork.at_attempt is not None:
        return fork.at_attempt + 1
    assert fork.at_stuck_cycle is not None
    return _read_stuck_attempt_count(fork.source_workspace, fork.at_stuck_cycle)


_WORKSPACE_FILES = (
    "problem.md",
    "submit.py",
    "evaluator.py",
    "_evaluator.py",
    "analyzer.py",
    "workspace_meta.json",
)


def fork_workspace(
    fork: ForkConfig,
    target_config: Config,
    *,
    config_path: str,
) -> Path:
    """Create target workspace from source, truncating archive to fork point."""
    source = fork.source_workspace.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"fork source_workspace not found: {source}")

    attempt_count = _resolve_fork_attempt_count(fork)
    source_archive = source / "archive"
    if not source_archive.is_dir():
        raise FileNotFoundError(f"source archive not found: {source_archive}")

    target = target_config.workspace_dir
    target_archive = target_config.archive_dir

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for name in _WORKSPACE_FILES:
        src = source / name
        if src.is_file():
            shutil.copy2(src, target / name)

    target_archive.mkdir(parents=True)
    for attempt_dir in sorted(source_archive.glob("attempt_*")):
        if not attempt_dir.is_dir():
            continue
        num = int(attempt_dir.name.split("_")[1])
        if num >= attempt_count:
            continue
        shutil.copytree(attempt_dir, target_archive / attempt_dir.name)

    archive = Archive(target_archive, target_config.maximize)
    if archive.submission_count() == 0:
        raise RuntimeError(f"Fork produced empty archive (attempt_count={attempt_count})")

    checkpoint = Checkpoint.from_archive(
        archive,
        project_name=target_config.project_name,
        maximize=target_config.maximize,
        max_improvements=target_config.max_improvements,
        evaluation_timeout_seconds=target_config.evaluation_timeout_seconds,
        config_path=config_path,
        status="paused",
    )
    save_checkpoint(checkpoint, target)

    best = archive.best()
    if best and best.code_path.is_file():
        shutil.copy2(best.code_path, target / "best_program.py")

    return target


def apply_fork_if_configured(
    fork: ForkConfig | None,
    primary_config_path: Path,
) -> bool:
    """Run fork before workflow if configured. Returns True if fork was applied."""
    if fork is None:
        return False
    config = load_config(primary_config_path)
    fork_workspace(fork, config, config_path=str(primary_config_path.resolve()))
    return True
