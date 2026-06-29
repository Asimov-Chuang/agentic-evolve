from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agentic_evolve.archive import Archive, Attempt, read_improvement_baseline


CHECKPOINT_VERSION = 1
CHECKPOINT_FILENAME = "checkpoint.json"


@dataclass
class Checkpoint:
    version: int
    project_name: str
    maximize: bool
    max_improvements: int
    evaluation_timeout_seconds: int
    attempt_count: int
    submissions_after_seed: int
    remaining_improvements: int
    best_attempt_id: Optional[str]
    best_score: Optional[float]
    best_is_valid: bool
    status: str
    updated_at: str
    config_path: str

    @classmethod
    def from_archive(
        cls,
        archive: Archive,
        *,
        project_name: str,
        maximize: bool,
        max_improvements: int,
        evaluation_timeout_seconds: int,
        config_path: str,
        status: str = "paused",
        improvement_baseline: int = 1,
    ) -> Checkpoint:
        best = archive.best()
        count = archive.submission_count()
        baseline = max(1, improvement_baseline)
        return cls(
            version=CHECKPOINT_VERSION,
            project_name=project_name,
            maximize=maximize,
            max_improvements=max_improvements,
            evaluation_timeout_seconds=evaluation_timeout_seconds,
            attempt_count=count,
            submissions_after_seed=max(0, count - baseline),
            remaining_improvements=archive.remaining_improvements(
                max_improvements, baseline=baseline
            ),
            best_attempt_id=best.attempt_id if best else None,
            best_score=best.score if best else None,
            best_is_valid=bool(best.is_valid) if best else False,
            status=status,
            updated_at=_now_iso(),
            config_path=config_path,
        )

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def checkpoint_path(workspace_dir: Path) -> Path:
    return workspace_dir / CHECKPOINT_FILENAME


def checkpoints_root(workspace_dir: Path) -> Path:
    return workspace_dir / "checkpoints"


def save_checkpoint(checkpoint: Checkpoint, workspace_dir: Path) -> Path:
    path = checkpoint_path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(checkpoint), f, indent=2)
    return path


def load_checkpoint(workspace_dir: Path) -> Optional[Checkpoint]:
    path = checkpoint_path(workspace_dir)
    if not path.is_file():
        return None
    return Checkpoint.load(path)


def has_resumable_archive(archive_dir: Path) -> bool:
    if not archive_dir.is_dir():
        return False
    return any(
        p.is_dir() and (p / "code.py").is_file() and (p / "result.json").is_file()
        for p in archive_dir.glob("attempt_*")
    )


def save_named_checkpoint(workspace_dir: Path, name: str) -> Path:
    archive_dir = workspace_dir / "archive"
    if not has_resumable_archive(archive_dir):
        raise RuntimeError("No archive to checkpoint")

    dest = checkpoints_root(workspace_dir) / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    shutil.copytree(archive_dir, dest / "archive")
    cp = load_checkpoint(workspace_dir)
    if cp:
        with open(dest / CHECKPOINT_FILENAME, "w", encoding="utf-8") as f:
            json.dump(asdict(cp), f, indent=2)

    return dest


def restore_named_checkpoint(workspace_dir: Path, name: str) -> Path:
    src = checkpoints_root(workspace_dir) / name
    if not src.is_dir() or not (src / "archive").is_dir():
        raise FileNotFoundError(f"Named checkpoint not found: {name}")

    archive_dir = workspace_dir / "archive"
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    shutil.copytree(src / "archive", archive_dir)

    src_cp = src / CHECKPOINT_FILENAME
    if src_cp.is_file():
        shutil.copy2(src_cp, checkpoint_path(workspace_dir))

    return archive_dir


def list_named_checkpoints(workspace_dir: Path) -> list[str]:
    root = checkpoints_root(workspace_dir)
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "archive").is_dir()
    )


def format_checkpoint_summary(checkpoint: Checkpoint, archive: Archive) -> str:
    best = archive.best()
    lines = [
        f"project: {checkpoint.project_name}",
        f"status: {checkpoint.status}",
        f"attempts: {checkpoint.attempt_count}",
        f"submissions after seed: {checkpoint.submissions_after_seed}",
        f"remaining improvements: {checkpoint.remaining_improvements} / {checkpoint.max_improvements}",
        f"best: {checkpoint.best_attempt_id} score={checkpoint.best_score} valid={checkpoint.best_is_valid}",
        f"updated: {checkpoint.updated_at}",
    ]
    if best:
        lines.append(f"current archive best: {best.attempt_id} score={best.score:.6f}")
    return "\n".join(lines)


def save_run_checkpoint(
    config_path: str,
    config,
    archive: Archive,
    status: str,
) -> None:
    checkpoint = Checkpoint.from_archive(
        archive,
        project_name=config.project_name,
        maximize=config.maximize,
        max_improvements=config.max_improvements,
        evaluation_timeout_seconds=config.evaluation_timeout_seconds,
        config_path=str(Path(config_path).resolve()),
        status=status,
        improvement_baseline=read_improvement_baseline(config.workspace_dir),
    )
    save_checkpoint(checkpoint, config.workspace_dir)
