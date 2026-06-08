"""Processed-feedback analyzer for the circle packing example."""

from __future__ import annotations

import json
import math
from pathlib import Path

NUM_CIRCLES = 26


def analyze(program_path: str, output_dir: str, result: dict, archive_dir: str, workspace_dir: str) -> dict:
    del program_path, output_dir, workspace_dir
    construction = result.get("construction") or {}
    centers = construction.get("centers") or []
    radii = construction.get("radii") or []
    geometry = _geometry_metrics(centers, radii)
    history = _archive_score_history(archive_dir)
    score = float(result.get("score", 0.0))
    best_previous = max(history) if history else None

    analysis_metrics = {
        **geometry,
        "score_delta_vs_previous_best": score - best_previous if best_previous is not None else 0.0,
        "previous_best_score": best_previous,
        "num_previous_attempts": len(history),
    }
    return {
        "processed_feedback": _build_feedback(result, analysis_metrics),
        "analysis_metrics": analysis_metrics,
        "analysis": {
            "note": "Packing coordinates come from result['construction'], captured during evaluator execution.",
        },
    }


def _geometry_metrics(centers, radii) -> dict:
    if len(centers) != NUM_CIRCLES or len(radii) != NUM_CIRCLES:
        return {
            "num_circles": min(len(centers), len(radii)),
            "sum_radii_recomputed": float(sum(radii)) if radii else 0.0,
            "min_boundary_margin": None,
            "min_pair_gap": None,
        }

    boundary_margins = []
    for (x, y), radius in zip(centers, radii):
        boundary_margins.extend([x - radius, 1.0 - x - radius, y - radius, 1.0 - y - radius])

    pair_gaps = []
    for i in range(NUM_CIRCLES):
        for j in range(i + 1, NUM_CIRCLES):
            dx = centers[i][0] - centers[j][0]
            dy = centers[i][1] - centers[j][1]
            pair_gaps.append(math.hypot(dx, dy) - radii[i] - radii[j])

    mean_radius = sum(radii) / len(radii)
    variance = sum((radius - mean_radius) ** 2 for radius in radii) / len(radii)
    return {
        "num_circles": len(radii),
        "sum_radii_recomputed": float(sum(radii)),
        "min_radius": float(min(radii)),
        "max_radius": float(max(radii)),
        "radius_stddev": math.sqrt(variance),
        "min_boundary_margin": float(min(boundary_margins)),
        "min_pair_gap": float(min(pair_gaps)) if pair_gaps else None,
        "near_contact_pairs": sum(1 for gap in pair_gaps if abs(gap) <= 1e-4),
    }


def _archive_score_history(archive_dir: str) -> list[float]:
    scores = []
    for result_path in sorted(Path(archive_dir).glob("attempt_*/result.json")):
        try:
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
            if result.get("is_valid"):
                scores.append(float(result["score"]))
        except Exception:
            continue
    return scores


def _build_feedback(result: dict, metrics: dict) -> str:
    if not result.get("is_valid"):
        return (
            "Invalid packing; prioritize fixing hard constraints. "
            f"min_boundary_margin={metrics.get('min_boundary_margin')}, "
            f"min_pair_gap={metrics.get('min_pair_gap')}."
        )

    delta = metrics["score_delta_vs_previous_best"]
    relation = "beats" if delta > 0 else "does not beat"
    slack_notes = []
    if metrics.get("min_boundary_margin") is not None and metrics["min_boundary_margin"] > 1e-3:
        slack_notes.append("boundary slack remains")
    if metrics.get("min_pair_gap") is not None and metrics["min_pair_gap"] > 1e-3:
        slack_notes.append("pairwise gaps remain")
    if not slack_notes:
        slack_notes.append("many constraints are tight")

    return (
        f"Valid packing {relation} previous best by {delta:.6f}; "
        f"{', '.join(slack_notes)}. "
        f"near_contact_pairs={metrics.get('near_contact_pairs', 0)}."
    )
