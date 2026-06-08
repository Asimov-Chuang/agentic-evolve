"""Processed-feedback analyzer aligned with OpenEvolve metric exposure."""

from __future__ import annotations

import json
from pathlib import Path


def analyze(program_path: str, output_dir: str, result: dict, archive_dir: str, workspace_dir: str) -> dict:
    del program_path, output_dir, workspace_dir
    metrics = result.get("metrics") or {}
    history = _archive_score_history(archive_dir)
    score = float(result.get("score", 0.0))
    best_previous = max(history) if history else None

    analysis_metrics = {
        **metrics,
        "overall_score": score,
        "score_delta_vs_previous_best": score - best_previous if best_previous is not None else 0.0,
        "previous_best_score": best_previous,
        "num_previous_attempts": len(history),
    }

    return {
        "processed_feedback": _build_feedback(result, analysis_metrics),
        "analysis_metrics": analysis_metrics,
        "analysis": {},
    }


def _archive_score_history(archive_dir: str) -> list[float]:
    scores = []
    for result_path in sorted(Path(archive_dir).glob("attempt_*/result.json")):
        try:
            with open(result_path, encoding="utf-8") as f:
                payload = json.load(f)
            if payload.get("is_valid"):
                scores.append(float(payload["score"]))
        except Exception:
            continue
    return scores


def _build_feedback(result: dict, metrics: dict) -> str:
    feedback = str(result.get("feedback", "")).strip()
    if not result.get("is_valid"):
        return feedback or "Invalid program."

    lines = []
    previous_best = metrics.get("previous_best_score")
    if previous_best is not None:
        delta = metrics.get("score_delta_vs_previous_best", 0.0)
        if delta > 0:
            relation = "improved"
        elif delta < 0:
            relation = "declined"
        else:
            relation = "unchanged"
        lines.append(
            f"Fitness (overall_score) {relation} vs previous best: "
            f"{metrics.get('overall_score', 0.0):.4f} (delta {delta:+.4f})."
        )

    if feedback:
        lines.append(feedback)
    return "\n".join(lines)
