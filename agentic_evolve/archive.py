from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agentic_evolve.result_sidecars import finalize_attempt_result, json_safe


def read_improvement_baseline(workspace_dir: Path) -> int:
    """Attempts present before the agent improvement budget starts (default: seed only)."""
    workspace = Path(workspace_dir).resolve()
    meta_path = workspace / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if "improvement_baseline_count" in meta:
            return max(1, int(meta["improvement_baseline_count"]))

    trajectory_path = workspace / "score_trajectory.jsonl"
    if trajectory_path.is_file():
        with open(trajectory_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("event") == "session_start" and row.get("session_baseline_count") is not None:
                    return max(1, int(row["session_baseline_count"]))
    return 1


def write_improvement_baseline(workspace_dir: Path, baseline: int) -> None:
    workspace = Path(workspace_dir).resolve()
    meta_path = workspace / "workspace_meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta["improvement_baseline_count"] = max(1, int(baseline))
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _max_attempt_index(archive_dir: Path) -> int:
    max_idx = -1
    for path in archive_dir.glob("attempt_*"):
        if not path.is_dir():
            continue
        suffix = path.name.split("_", 1)[-1]
        try:
            max_idx = max(max_idx, int(suffix))
        except ValueError:
            continue
    return max_idx


def next_attempt_id_for_dir(archive_dir: Path) -> str:
    """Next unused attempt id (uses max numeric suffix, not directory count)."""
    return f"attempt_{_max_attempt_index(archive_dir) + 1:04d}"


def _dict_or_empty(value) -> dict:
    return value if isinstance(value, dict) else {}


@dataclass
class Attempt:
    attempt_id: str
    directory: Path
    score: float
    is_valid: bool
    feedback: str
    metrics: dict = field(default_factory=dict)
    processed_feedback: str = ""
    analysis_metrics: dict = field(default_factory=dict)
    analysis: dict = field(default_factory=dict)

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
            metrics=_dict_or_empty(result.get("metrics")),
            processed_feedback=str(result.get("processed_feedback", "")),
            analysis_metrics=_dict_or_empty(result.get("analysis_metrics")),
            analysis=_dict_or_empty(result.get("analysis")),
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
        return next_attempt_id_for_dir(self.archive_dir)

    def add_attempt(
        self,
        code_source: Path,
        result: dict,
        *,
        store_raw_artifacts: bool = True,
    ) -> Attempt:
        attempt_id = self.next_attempt_id()
        attempt_dir = self.archive_dir / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=False)

        shutil.copy2(code_source, attempt_dir / "code.py")
        payload = {
            "score": float(result["score"]),
            "is_valid": bool(result["is_valid"]),
            "feedback": str(result.get("feedback", "")),
            "metrics": _dict_or_empty(result.get("metrics")),
        }
        for key, value in result.items():
            if key not in payload:
                payload[key] = json_safe(value)
        payload = finalize_attempt_result(
            attempt_dir,
            payload,
            store_raw_artifacts=store_raw_artifacts,
        )
        with open(attempt_dir / "result.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        return Attempt(
            attempt_id=attempt_id,
            directory=attempt_dir,
            score=payload["score"],
            is_valid=payload["is_valid"],
            feedback=payload["feedback"],
            metrics=payload["metrics"],
            processed_feedback=str(payload.get("processed_feedback", "")),
            analysis_metrics=_dict_or_empty(payload.get("analysis_metrics")),
            analysis=_dict_or_empty(payload.get("analysis")),
        )

    def seed_initial(
        self,
        initial_program: Path,
        result: dict,
        *,
        store_raw_artifacts: bool = True,
    ) -> Attempt:
        if self.list_attempts():
            raise RuntimeError("Archive already has attempts; cannot seed initial program")
        return self.add_attempt(
            initial_program,
            result,
            store_raw_artifacts=store_raw_artifacts,
        )

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

    def remaining_improvements(self, max_improvements: int, *, baseline: int = 1) -> int:
        # Only submissions after the baseline count toward the agent budget.
        baseline = max(1, baseline)
        return max(0, max_improvements - max(0, self.submission_count() - baseline))

    def attempts_for_prompt(
        self,
        *,
        top_n: int = 0,
        recent_n: int = 0,
    ) -> list[Attempt]:
        """Select attempts to summarize in the evolution prompt.

        When ``top_n`` and ``recent_n`` are both 0, returns every attempt in order.
        Otherwise returns the union of top-N by score and the most recent N attempts.
        """
        attempts = self.list_attempts()
        if not attempts or (top_n <= 0 and recent_n <= 0):
            return attempts

        by_id = {a.attempt_id: a for a in attempts}
        selected: list[Attempt] = []
        seen: set[str] = set()

        if top_n > 0:
            pool = [a for a in attempts if a.is_valid] or attempts
            ranked = sorted(
                pool,
                key=lambda a: a.score,
                reverse=self.maximize,
            )[:top_n]
            for attempt in ranked:
                if attempt.attempt_id not in seen:
                    seen.add(attempt.attempt_id)
                    selected.append(attempt)

        if recent_n > 0:
            for attempt in attempts[-recent_n:]:
                if attempt.attempt_id not in seen:
                    seen.add(attempt.attempt_id)
                    selected.append(attempt)

        return [
            by_id[attempt_id]
            for attempt_id in sorted(seen, key=lambda name: int(name.split("_")[1]))
        ]

    def summary_lines(
        self,
        *,
        top_n: int = 0,
        recent_n: int = 0,
        max_feedback_chars: int = 400,
    ) -> list[str]:
        attempts = self.attempts_for_prompt(top_n=top_n, recent_n=recent_n)
        lines: list[str] = []
        for attempt in attempts:
            status = "valid" if attempt.is_valid else "invalid"
            feedback = attempt.processed_feedback or attempt.feedback
            if max_feedback_chars > 0 and len(feedback) > max_feedback_chars:
                feedback = feedback[:max_feedback_chars] + "..."
            lines.append(
                f"- {attempt.attempt_id}: score={attempt.score:.6f} ({status}) "
                f"feedback={feedback}"
            )
        return lines


def save_best_program(archive: Archive, dest: Path, fallback: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    best = archive.best()
    source = best.code_path if best else fallback
    shutil.copy2(source, dest)
    return dest
