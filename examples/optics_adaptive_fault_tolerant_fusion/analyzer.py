"""Standard analyzer for adaptive fault-tolerant fusion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _load_raw_artifact(output_dir: str | Path) -> dict[str, Any] | None:
    path = Path(output_dir) / "raw-artifact.json"
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _metrics_from(result: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    metrics = result.get("metrics")
    if isinstance(metrics, dict) and metrics:
        return dict(metrics)
    construction = result.get("construction")
    if isinstance(construction, dict) and isinstance(construction.get("metrics"), dict):
        return dict(construction["metrics"])
    if raw and isinstance(raw.get("metrics"), dict):
        return dict(raw["metrics"])
    return {}


def _command_stats(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    stats = raw.get("command_stats")
    return dict(stats) if isinstance(stats, dict) else {}


def _diagnosis(metrics: dict[str, Any], raw: dict[str, Any] | None) -> list[str]:
    diagnosis: list[str] = []
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    score = _as_float(metrics.get("combined_score"), _as_float(metrics.get("candidate_score"), 0.0))
    gap = _as_float(metrics.get("score_gap_oracle_minus_candidate"), 0.0)
    mean_rms = _as_float(metrics.get("candidate_mean_rms"), 0.0)
    p95_rms = _as_float(metrics.get("candidate_p95_rms"), 0.0)
    mean_strehl = _as_float(metrics.get("candidate_mean_strehl"), 0.0)

    if not valid:
        reason = metrics.get("failure_reason") or (raw or {}).get("error_message") or "unknown evaluator failure"
        return [f"Invalid controller: {reason}"]

    if score >= 0.9:
        diagnosis.append("Controller is near oracle-level on the weighted score.")
    elif gap > 0.25:
        diagnosis.append("Large oracle gap remains; prioritize rejecting faulty WFS channels before fusion.")
    elif gap > 0.08:
        diagnosis.append("Moderate oracle gap remains; tune inlier selection and weighting temperature.")
    else:
        diagnosis.append("Score gap to oracle is small; focus on tail cases rather than mean behavior.")

    if p95_rms > mean_rms * 1.35:
        diagnosis.append("Tail RMS is much worse than mean RMS; inspect worst fault combinations and avoid brittle channel selection.")
    if mean_strehl < 0.25:
        diagnosis.append("Mean Strehl is low; robust fusion may be reducing outliers but under-correcting the clean signal.")

    stats = _command_stats(raw)
    saturation = stats.get("saturation_fraction") if isinstance(stats, dict) else None
    if isinstance(saturation, dict) and _as_float(saturation.get("mean"), 0.0) > 0.15:
        diagnosis.append("Many commands are saturated; reduce fused-slope magnitude or add command regularization.")
    return diagnosis


def _format_feedback(metrics: dict[str, Any], raw: dict[str, Any] | None, diagnosis: list[str]) -> str:
    score = _as_float(metrics.get("combined_score"), _as_float(metrics.get("candidate_score"), 0.0))
    lines = [
        f"Score: {score:.4f}",
        f"Valid: {_as_float(metrics.get('valid'), 0.0) > 0.0}",
        f"Oracle gap: {_as_float(metrics.get('score_gap_oracle_minus_candidate'), 0.0):.4f}",
        f"Mean RMS: {_as_float(metrics.get('candidate_mean_rms'), 0.0):.4f}",
        f"P95 RMS: {_as_float(metrics.get('candidate_p95_rms'), 0.0):.4f}",
        f"Mean Strehl: {_as_float(metrics.get('candidate_mean_strehl'), 0.0):.4f}",
        f"Raw artifact present: {raw is not None}",
    ]
    for item in diagnosis:
        lines.append(f"- {item}")
    return "\n".join(lines)


def analyze(
    program_path: str,
    output_dir: str,
    result: dict,
    archive_dir: str,
    workspace_dir: str,
) -> dict[str, Any]:
    del program_path, archive_dir, workspace_dir

    raw = _load_raw_artifact(output_dir)
    metrics = _metrics_from(result, raw)
    diagnosis = _diagnosis(metrics, raw)
    return {
        "processed_feedback": _format_feedback(metrics, raw, diagnosis),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score"), 0.0),
            "valid": 1.0 if _as_float(metrics.get("valid"), 0.0) > 0.0 else 0.0,
            "candidate_mean_rms": _as_float(metrics.get("candidate_mean_rms"), 0.0),
            "candidate_p95_rms": _as_float(metrics.get("candidate_p95_rms"), 0.0),
            "candidate_mean_strehl": _as_float(metrics.get("candidate_mean_strehl"), 0.0),
            "score_gap_oracle_minus_candidate": _as_float(metrics.get("score_gap_oracle_minus_candidate"), 0.0),
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
        },
        "analysis": {
            "diagnosis": diagnosis,
            "command_stats": _command_stats(raw),
            "raw_artifact_present": raw is not None,
        },
    }
