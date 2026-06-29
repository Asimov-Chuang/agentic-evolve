"""PRO-mode analyzer: rich feedback from construction plus raw-artifact trajectory signals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def load_raw_artifact(output_dir: str | Path) -> dict[str, Any] | None:
    path = Path(output_dir) / "raw-artifact.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _iter_episodes(raw: dict[str, Any]):
    for block in raw.get("scenarios") or []:
        steps = list(block.get("steps") or [])
        if steps:
            yield int(block.get("episode", 0)), steps


def _cmd_norm(step: dict[str, Any]) -> float:
    cmd = np.asarray((step.get("actions") or {}).get("cmd") or [], dtype=np.float64)
    return float(np.linalg.norm(cmd)) if cmd.size else 0.0


def extract_trajectory_metrics(raw: dict[str, Any] | None) -> dict[str, float]:
    if not raw:
        return {}

    cmd_norms: list[float] = []
    step_slews: list[float] = []
    prev_cmd: np.ndarray | None = None

    for _episode, steps in _iter_episodes(raw):
        for step in steps:
            cmd_norms.append(_cmd_norm(step))
            cmd = np.asarray((step.get("actions") or {}).get("cmd") or [], dtype=np.float64)
            if prev_cmd is not None and cmd.size and prev_cmd.size == cmd.size:
                step_slews.append(float(np.linalg.norm(cmd - prev_cmd)))
            if cmd.size:
                prev_cmd = cmd

    metrics: dict[str, float] = {}
    if cmd_norms:
        metrics["trajectory_mean_cmd_norm"] = float(np.mean(cmd_norms))
        metrics["trajectory_p95_cmd_norm"] = float(np.percentile(cmd_norms, 95))
    if step_slews:
        metrics["trajectory_mean_step_slew"] = float(np.mean(step_slews))
        metrics["trajectory_p95_step_slew"] = float(np.percentile(step_slews, 95))
    metrics["trajectory_step_count"] = float(len(cmd_norms))
    return metrics


def _baseline(report: dict[str, Any]) -> dict[str, Any]:
    return dict(report.get("baseline") or {})


def _reference(report: dict[str, Any]) -> dict[str, Any]:
    return dict(report.get("reference") or {})


def build_metric_breakdown(report: dict[str, Any]) -> dict[str, float]:
    baseline = _baseline(report)
    return {
        "score_0_to_1_higher_is_better": float(
            baseline.get("score_0_to_1_higher_is_better", 0.0)
        ),
        "mean_rms": float(baseline.get("mean_rms", 0.0)),
        "mean_slew": float(baseline.get("mean_slew", 0.0)),
        "mean_strehl": float(baseline.get("mean_strehl", 0.0)),
        "raw_cost_lower_is_better": float(baseline.get("raw_cost_lower_is_better", 0.0)),
    }


def build_reference_comparison(report: dict[str, Any]) -> dict[str, dict[str, float]]:
    baseline = _baseline(report)
    reference = _reference(report)
    keys = ("mean_rms", "mean_slew", "mean_strehl", "score_0_to_1_higher_is_better")
    return {
        "candidate": {key: float(baseline.get(key, 0.0)) for key in keys},
        "reference": {key: float(reference.get(key, 0.0)) for key in keys},
    }


def format_processed_feedback(
    report: dict[str, Any],
    trajectory_metrics: dict[str, float],
) -> str:
    baseline = _baseline(report)
    score = float(baseline.get("score_0_to_1_higher_is_better", 0.0))
    metrics = build_metric_breakdown(report)
    lines = [f"Score: {score:.4f}"]
    metric_parts = [
        f"{name}={value:.4f}"
        for name, value in (
            ("mean_rms", metrics.get("mean_rms", 0.0)),
            ("mean_slew", metrics.get("mean_slew", 0.0)),
            ("mean_strehl", metrics.get("mean_strehl", 0.0)),
        )
    ]
    lines.append(f"Metrics: {', '.join(metric_parts)}")
    if trajectory_metrics:
        traj_parts = [
            f"{name}={value:.4f}"
            for name, value in sorted(trajectory_metrics.items())
            if name != "trajectory_step_count"
        ]
        if traj_parts:
            lines.append(f"Trajectory: {', '.join(traj_parts)}")
    return "\n".join(lines)


def analyze(
    program_path: str,
    output_dir: str,
    result: dict,
    archive_dir: str,
    workspace_dir: str,
) -> dict:
    del program_path, archive_dir, workspace_dir

    if not result.get("is_valid"):
        return {
            "processed_feedback": (
                "Invalid controller; fix runtime errors before tuning control logic. "
                f"{result.get('feedback', '')}"
            ),
        }

    report = result.get("construction") or {}
    if not report:
        return {
            "processed_feedback": (
                "Evaluation succeeded but no construction report was captured; "
                "check evaluator.py integration."
            ),
        }

    raw = load_raw_artifact(output_dir)
    trajectory_metrics = extract_trajectory_metrics(raw)
    metrics = build_metric_breakdown(report)
    return {
        "processed_feedback": format_processed_feedback(report, trajectory_metrics),
        "analysis_metrics": {
            "score_0_to_1_higher_is_better": metrics["score_0_to_1_higher_is_better"],
            "metrics": metrics,
            "trajectory": trajectory_metrics,
        },
        "analysis": {
            "reference_comparison": build_reference_comparison(report),
            "trajectory_metrics": trajectory_metrics,
            "raw_artifact_present": raw is not None,
        },
    }
