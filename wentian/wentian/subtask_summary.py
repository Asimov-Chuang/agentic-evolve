from __future__ import annotations

import json
from pathlib import Path

from agentic_evolve.archive import Archive

from wentian.hub_plan import SubtaskSpec


def _score_delta(attempts: list, maximize: bool) -> float:
    if len(attempts) < 2:
        return 0.0
    scores = [a.score for a in attempts if a.is_valid] or [a.score for a in attempts]
    if not scores:
        return 0.0
    first = scores[0]
    best = max(scores) if maximize else min(scores)
    return best - first if maximize else first - best


def _trajectory_notes(attempts: list, maximize: bool) -> str:
    if len(attempts) < 2:
        return "Only seed attempt; no evolution yet."

    valid = [a for a in attempts if a.is_valid]
    pool = valid or attempts
    best_score = max(a.score for a in pool) if maximize else min(a.score for a in pool)

    plateau = 0
    for a in attempts[1:]:
        if (maximize and a.score >= best_score) or (not maximize and a.score <= best_score):
            break
        plateau += 1

    if plateau >= len(attempts) - 1:
        return f"No improvement over {len(attempts) - 1} submissions after seed."

    breakthrough_idx = None
    running_best = attempts[0].score
    for i, a in enumerate(attempts[1:], start=1):
        improved = (maximize and a.score > running_best) or (not maximize and a.score < running_best)
        if improved:
            breakthrough_idx = i
            running_best = a.score

    if breakthrough_idx is not None:
        return f"First {breakthrough_idx} submission(s) after seed showed no improvement; breakthrough at index {breakthrough_idx}."
    return "Mixed trajectory; see top attempts for details."


def _suggested_directions(attempts: list, *, top_k: int = 3) -> list[str]:
    directions: list[str] = []
    seen: set[str] = set()
    ranked = sorted(attempts, key=lambda a: a.score, reverse=True)
    for attempt in ranked[:top_k]:
        fb = (attempt.processed_feedback or attempt.feedback).strip()
        if not fb:
            continue
        snippet = fb.split("\n")[0][:200]
        if snippet and snippet not in seen:
            seen.add(snippet)
            directions.append(snippet)
    return directions


def summarize_subtask(
    subtask_id: str,
    archive_dir: Path,
    *,
    round_num: int,
    maximize: bool,
    spec: SubtaskSpec | None = None,
) -> dict:
    archive = Archive(archive_dir, maximize)
    attempts = archive.list_attempts()
    best = archive.best()

    top_attempts = []
    pool = [a for a in attempts if a.is_valid] or attempts
    ranked = sorted(pool, key=lambda a: a.score, reverse=maximize)[:5]
    for a in ranked:
        fb = a.processed_feedback or a.feedback
        top_attempts.append(
            {
                "id": a.attempt_id,
                "score": a.score,
                "is_valid": a.is_valid,
                "feedback_snippet": fb[:400] + ("..." if len(fb) > 400 else ""),
            }
        )

    summary = {
        "subtask_id": subtask_id,
        "round": round_num,
        "best_score": best.score if best else None,
        "best_attempt_id": best.attempt_id if best else None,
        "attempt_count": len(attempts),
        "improvement_delta": _score_delta(attempts, maximize),
        "top_attempts": top_attempts,
        "trajectory_notes": _trajectory_notes(attempts, maximize),
        "suggested_directions": _suggested_directions(attempts),
        "evolve_focus": spec.evolve_focus if spec else None,
        "prompt_append": spec.prompt_append if spec else "",
    }
    return summary


def write_subtask_summary(summary: dict, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return dest
