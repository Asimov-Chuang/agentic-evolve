"""Append-only best-score trajectory log for evolution workspaces."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from agentic_evolve.archive import Archive, Attempt

TRAJECTORY_FILENAME = "score_trajectory.jsonl"


def trajectory_path(workspace_dir: Path) -> Path:
    return Path(workspace_dir).resolve() / TRAJECTORY_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_entry(workspace_dir: Path, payload: dict[str, Any]) -> Path:
    path = trajectory_path(workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(payload)
    row.setdefault("ts", _now_iso())
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _logged_attempt_ids(workspace_dir: Path) -> set[str]:
    path = trajectory_path(workspace_dir)
    if not path.is_file():
        return set()
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            attempt_id = row.get("attempt_id")
            if isinstance(attempt_id, str):
                seen.add(attempt_id)
    return seen


def _best_fields(archive: Archive) -> tuple[float | None, str | None]:
    best = archive.best()
    if best is None:
        return None, None
    return best.score, best.attempt_id


def record_attempt(
    workspace_dir: Path,
    archive_dir: Path,
    attempt: Attempt,
    *,
    maximize: bool,
    event: str = "submit",
) -> None:
    archive = Archive(archive_dir, maximize)
    best_score, best_id = _best_fields(archive)
    append_entry(
        workspace_dir,
        {
            "event": event,
            "attempt_id": attempt.attempt_id,
            "score": float(attempt.score),
            "is_valid": bool(attempt.is_valid),
            "best_so_far": best_score,
            "best_attempt_id": best_id,
            "attempt_count": archive.submission_count(),
        },
    )


def record_event(workspace_dir: Path, event: str, **fields: Any) -> None:
    append_entry(workspace_dir, {"event": event, **fields})


def sync_archive_to_trajectory(
    workspace_dir: Path,
    archive_dir: Path,
    *,
    maximize: bool,
    event: str = "submit",
) -> int:
    """Append rows for archive attempts not yet present in the trajectory log."""
    logged = _logged_attempt_ids(workspace_dir)
    archive = Archive(archive_dir, maximize)
    added = 0
    for attempt in archive.list_attempts():
        if attempt.attempt_id in logged:
            continue
        record_attempt(
            workspace_dir,
            archive_dir,
            attempt,
            maximize=maximize,
            event=event,
        )
        logged.add(attempt.attempt_id)
        added += 1
    return added


class TrajectoryWatcher:
    """Poll archive during long OpenCode sessions and backfill the trajectory log."""

    def __init__(self, workspace_dir: Path, archive_dir: Path, *, maximize: bool) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.archive_dir = Path(archive_dir).resolve()
        self.maximize = maximize

    def sync(self, *, event: str = "submit") -> int:
        return sync_archive_to_trajectory(
            self.workspace_dir,
            self.archive_dir,
            maximize=self.maximize,
            event=event,
        )

    def record_best_snapshot(self, *, event: str = "poll") -> None:
        archive = Archive(self.archive_dir, self.maximize)
        best_score, best_id = _best_fields(archive)
        append_entry(
            self.workspace_dir,
            {
                "event": event,
                "best_so_far": best_score,
                "best_attempt_id": best_id,
                "attempt_count": archive.submission_count(),
            },
        )


def read_trajectory(workspace_dir: Path) -> list[dict[str, Any]]:
    path = trajectory_path(workspace_dir)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
