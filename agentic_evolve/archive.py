from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Attempt:
    attempt_id: str
    directory: Path
    score: float
    is_valid: bool
    feedback: str
    metrics: dict = field(default_factory=dict)

    @property
    def code_path(self) -> Path:
        return self.directory / "code.py"

    @property
    def result_path(self) -> Path:
        return self.directory / "result.json"

    @classmethod
    def from_directory(cls, directory: Path) -> Attempt:
        with open(directory / "result.json", encoding="utf-8") as f:
            result = json.load(f)
        return cls(
            attempt_id=directory.name,
            directory=directory,
            score=float(result["score"]),
            is_valid=bool(result["is_valid"]),
            feedback=str(result.get("feedback", "")),
            metrics=dict(result.get("metrics") or {}),
        )


class Archive:
    def __init__(self, archive_dir: Path, maximize: bool):
        self.archive_dir = archive_dir
        self.maximize = maximize
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def list_attempts(self) -> list[Attempt]:
        attempts: list[Attempt] = []
        for path in sorted(self.archive_dir.glob("attempt_*")):
            if path.is_dir() and (path / "result.json").is_file() and (path / "code.py").is_file():
                attempts.append(Attempt.from_directory(path))
        return attempts

    def next_attempt_id(self) -> str:
        existing = sorted(self.archive_dir.glob("attempt_*"))
        return f"attempt_{len(existing):04d}"

    def add_attempt(self, code_source: Path, result: dict) -> Attempt:
        attempt_id = self.next_attempt_id()
        attempt_dir = self.archive_dir / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=False)

        shutil.copy2(code_source, attempt_dir / "code.py")
        payload = {
            "score": float(result["score"]),
            "is_valid": bool(result["is_valid"]),
            "feedback": str(result.get("feedback", "")),
            "metrics": dict(result.get("metrics") or {}),
        }
        with open(attempt_dir / "result.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        return Attempt(
            attempt_id=attempt_id,
            directory=attempt_dir,
            score=payload["score"],
            is_valid=payload["is_valid"],
            feedback=payload["feedback"],
            metrics=payload["metrics"],
        )

    def seed_initial(self, initial_program: Path, result: dict) -> Attempt:
        if self.list_attempts():
            raise RuntimeError("Archive already has attempts; cannot seed initial program")
        return self.add_attempt(initial_program, result)

    def best(self) -> Optional[Attempt]:
        valid = [a for a in self.list_attempts() if a.is_valid]
        if not valid:
            return None
        if self.maximize:
            return max(valid, key=lambda a: a.score)
        return min(valid, key=lambda a: a.score)

    def best_score(self) -> Optional[float]:
        best = self.best()
        return best.score if best else None

    def submission_count(self) -> int:
        return len(self.list_attempts())

    def remaining_improvements(self, max_improvements: int) -> int:
        # attempt_0000 is the seed; agent budget is max_improvements new submissions
        return max(0, max_improvements - max(0, self.submission_count() - 1))

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        for attempt in self.list_attempts():
            status = "valid" if attempt.is_valid else "invalid"
            lines.append(
                f"- {attempt.attempt_id}: score={attempt.score:.6f} ({status}) "
                f"feedback={attempt.feedback}"
            )
        return lines


def save_best_program(archive: Archive, dest: Path, fallback: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    best = archive.best()
    source = best.code_path if best else fallback
    shutil.copy2(source, dest)
    return dest
