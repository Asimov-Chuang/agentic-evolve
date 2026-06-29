from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agentic_evolve.archive import Archive, Attempt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Provenance:
    subtask_id: str
    round_num: int
    source_attempt_id: str
    merged_at: str


class GlobalArchive:
    """Central archive merging attempts from all sub-tasks."""

    PROVENANCE_FILENAME = "provenance.json"
    LOG_FILENAME = "merge_log.jsonl"

    def __init__(self, archive_dir: Path, *, maximize: bool, top_n: int = 50):
        self.archive_dir = archive_dir
        self.maximize = maximize
        self.top_n = top_n
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._archive = Archive(archive_dir, maximize)

    @property
    def inner(self) -> Archive:
        return self._archive

    def list_attempts(self) -> list[Attempt]:
        return self._archive.list_attempts()

    def best(self) -> Attempt | None:
        return self._archive.best()

    def top_n_attempts(self, n: int) -> list[Attempt]:
        attempts = self.list_attempts()
        if not attempts:
            return []
        pool = [a for a in attempts if a.is_valid] or attempts
        ranked = sorted(pool, key=lambda a: a.score, reverse=self.maximize)
        return ranked[:n]

    def get_attempt_dir(self, attempt_id: str) -> Path | None:
        path = self.archive_dir / attempt_id
        if path.is_dir() and (path / "code.py").is_file():
            return path
        return None

    def attempt_count(self) -> int:
        return self._archive.submission_count()

    def _next_global_id(self) -> str:
        return self._archive.next_attempt_id()

    def _write_provenance(self, attempt_dir: Path, prov: Provenance) -> None:
        (attempt_dir / self.PROVENANCE_FILENAME).write_text(
            json.dumps(
                {
                    "subtask_id": prov.subtask_id,
                    "round": prov.round_num,
                    "source_attempt_id": prov.source_attempt_id,
                    "merged_at": prov.merged_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _append_merge_log(self, entry: dict) -> None:
        log_path = self.archive_dir.parent / self.LOG_FILENAME
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, encoding="utf-8", mode="a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def _merged_source_keys(self) -> set[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        for attempt in self.list_attempts():
            prov_path = attempt.directory / self.PROVENANCE_FILENAME
            if not prov_path.is_file():
                continue
            with open(prov_path, encoding="utf-8") as f:
                prov = json.load(f)
            subtask_id = prov.get("subtask_id")
            source_id = prov.get("source_attempt_id")
            if subtask_id and source_id:
                keys.add((str(subtask_id), str(source_id)))
        return keys

    def merge_subtask_archive(
        self,
        subtask_archive_dir: Path,
        *,
        subtask_id: str,
        round_num: int,
    ) -> list[str]:
        """Import all attempts from a sub-task archive. Returns new global attempt ids."""
        source = Archive(subtask_archive_dir, self.maximize)
        imported: list[str] = []
        already_merged = self._merged_source_keys()

        for attempt in source.list_attempts():
            if (subtask_id, attempt.attempt_id) in already_merged:
                continue
            new_id = self._next_global_id()
            dest = self.archive_dir / new_id
            dest.mkdir(parents=True, exist_ok=False)
            shutil.copy2(attempt.code_path, dest / "code.py")
            shutil.copy2(attempt.result_path, dest / "result.json")
            for extra in ("raw-artifact.json", "diagnosis_meta.json"):
                src_extra = attempt.directory / extra
                if src_extra.is_file():
                    shutil.copy2(src_extra, dest / extra)
            self._write_provenance(
                dest,
                Provenance(
                    subtask_id=subtask_id,
                    round_num=round_num,
                    source_attempt_id=attempt.attempt_id,
                    merged_at=_now(),
                ),
            )
            imported.append(new_id)

        self._append_merge_log(
            {
                "subtask_id": subtask_id,
                "round": round_num,
                "imported": len(imported),
                "new_ids": imported,
                "merged_at": _now(),
            }
        )
        self.prune()
        return imported

    def prune(self) -> int:
        """Keep only top_n attempts; return count removed."""
        attempts = self.list_attempts()
        if len(attempts) <= self.top_n:
            return 0
        ranked = sorted(attempts, key=lambda a: a.score, reverse=self.maximize)
        keep_ids = {a.attempt_id for a in ranked[: self.top_n]}
        removed = 0
        for attempt in attempts:
            if attempt.attempt_id not in keep_ids:
                shutil.rmtree(attempt.directory, ignore_errors=True)
                removed += 1
        return removed

    def summary_for_hub(self, *, top_n: int = 15, max_feedback_chars: int = 400) -> str:
        lines = ["# Global Archive Summary", ""]
        best = self.best()
        if best:
            lines.append(f"**Global best:** {best.attempt_id} score={best.score:.6f}")
        else:
            lines.append("**Global best:** (none yet)")
        lines.append(f"**Total attempts:** {self.attempt_count()}")
        lines.append("")
        lines.append("## Top attempts")
        lines.append("")
        for attempt in self.top_n_attempts(top_n):
            prov_path = attempt.directory / self.PROVENANCE_FILENAME
            prov_note = ""
            if prov_path.is_file():
                with open(prov_path, encoding="utf-8") as f:
                    prov = json.load(f)
                prov_note = f" [from subtask={prov.get('subtask_id')}, src={prov.get('source_attempt_id')}]"
            feedback = attempt.processed_feedback or attempt.feedback
            if max_feedback_chars > 0 and len(feedback) > max_feedback_chars:
                feedback = feedback[:max_feedback_chars] + "..."
            status = "valid" if attempt.is_valid else "invalid"
            lines.append(f"- {attempt.attempt_id}: score={attempt.score:.6f} ({status}){prov_note}")
            lines.append(f"  feedback: {feedback}")
            lines.append("")
        summary_path = self.archive_dir.parent / "global_archive_summary.md"
        text = "\n".join(lines).strip() + "\n"
        summary_path.write_text(text, encoding="utf-8")
        return text

    def seed_from_initial_program(
        self,
        initial_program: Path,
        evaluator_path: Path,
        *,
        workspace_dir: Path,
        evaluation_timeout_seconds: int,
        analyzer_path: Path | None = None,
        store_raw_artifacts: bool = True,
    ) -> Attempt:
        """Seed global archive with task initial program when empty."""
        if self.list_attempts():
            raise RuntimeError("Global archive already has attempts")

        from agentic_evolve.evaluator import run_evaluation

        result = run_evaluation(
            evaluator_path=evaluator_path,
            program_path=initial_program,
            output_dir=self.archive_dir / "_seed_eval",
            timeout_seconds=evaluation_timeout_seconds,
            maximize=self.maximize,
            analyzer_path=analyzer_path,
            archive_dir=self.archive_dir,
            workspace_dir=workspace_dir,
        )
        return self._archive.seed_initial(
            initial_program,
            result,
            store_raw_artifacts=store_raw_artifacts,
        )
