"""PRO analyzer for adaptive fault-tolerant fusion raw artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def load_raw_artifact(output_dir: str | Path) -> dict[str, Any] | None:
    path = Path(output_dir) / "raw-artifact.json"
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _metrics_from(result: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    metrics = result.get("metrics")
    if isinstance(metrics, dict) and metrics:
        return dict(metrics)
    if raw and isinstance(raw.get("metrics"), dict):
        return dict(raw["metrics"])
    construction = result.get("construction")
    if isinstance(construction, dict) and isinstance(construction.get("metrics"), dict):
        return dict(construction["metrics"])
    return {}


def _case_trace(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    trace = raw.get("case_trace")
    return list(trace) if isinstance(trace, list) else []


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def _trace_metrics(trace: list[dict[str, Any]]) -> dict[str, float]:
    if not trace:
        return {"raw_case_count": 0.0}

    rms = [_as_float(item.get("rms")) for item in trace]
    strehl = [_as_float(item.get("strehl")) for item in trace]
    saturation = [_as_float(item.get("saturation_fraction")) for item in trace]
    cmd_l2 = [_as_float(item.get("command_l2")) for item in trace]
    cmd_slew = [_as_float(item.get("command_slew_l2")) for item in trace[1:]]
    anomaly_gaps = [_as_float(item.get("score_gap_best_minus_worst")) for item in trace if "score_gap_best_minus_worst" in item]

    return {
        "raw_case_count": float(len(trace)),
        "trace_mean_rms": float(np.mean(rms)),
        "trace_p95_rms": _percentile(rms, 95),
        "trace_p99_rms": _percentile(rms, 99),
        "trace_worst_rms": float(np.max(rms)),
        "trace_mean_strehl": float(np.mean(strehl)),
        "trace_p05_strehl": _percentile(strehl, 5),
        "trace_mean_saturation_fraction": float(np.mean(saturation)),
        "trace_max_saturation_fraction": float(np.max(saturation)),
        "trace_mean_command_l2": float(np.mean(cmd_l2)),
        "trace_p95_command_l2": _percentile(cmd_l2, 95),
        "trace_mean_command_slew_l2": float(np.mean(cmd_slew)) if cmd_slew else 0.0,
        "trace_p95_command_slew_l2": _percentile(cmd_slew, 95),
        "trace_mean_anomaly_score_gap": float(np.mean(anomaly_gaps)) if anomaly_gaps else 0.0,
    }


def _worst_cases(trace: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = sorted(trace, key=lambda item: _as_float(item.get("rms")), reverse=True)[:limit]
    result: list[dict[str, Any]] = []
    for item in rows:
        result.append(
            {
                "case_index": int(_as_float(item.get("case_index"), 0)),
                "rms": _as_float(item.get("rms")),
                "strehl": _as_float(item.get("strehl")),
                "command_linf": _as_float(item.get("command_linf")),
                "saturation_fraction": _as_float(item.get("saturation_fraction")),
                "bad_ids": item.get("bad_ids") or [],
                "selected_sensor_ids": item.get("selected_sensor_ids") or [],
            }
        )
    return result


def _sensor_selection_stats(trace: list[dict[str, Any]]) -> dict[str, Any]:
    selected_counts = {str(idx): 0 for idx in range(5)}
    bad_selected = 0
    selected_total = 0
    for item in trace:
        bad_ids = {int(x) for x in item.get("bad_ids") or []}
        selected = [int(x) for x in item.get("selected_sensor_ids") or []]
        for idx in selected:
            selected_counts[str(idx)] = selected_counts.get(str(idx), 0) + 1
            selected_total += 1
            if idx in bad_ids:
                bad_selected += 1
    return {
        "selected_counts": selected_counts,
        "bad_selected_fraction": float(bad_selected / selected_total) if selected_total else 0.0,
    }


def _diagnosis(metrics: dict[str, Any], trace_metrics: dict[str, float], sensor_stats: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    if not valid:
        diagnosis.append(f"Invalid controller: {metrics.get('failure_reason', 'unknown failure')}")
        return diagnosis

    score = _as_float(metrics.get("combined_score"), _as_float(metrics.get("candidate_score"), 0.0))
    gap = _as_float(metrics.get("score_gap_oracle_minus_candidate"), 0.0)
    mean_rms = _as_float(metrics.get("candidate_mean_rms"), trace_metrics.get("trace_mean_rms", 0.0))
    p95_rms = _as_float(metrics.get("candidate_p95_rms"), trace_metrics.get("trace_p95_rms", 0.0))
    saturation_mean = trace_metrics.get("trace_mean_saturation_fraction", 0.0)
    bad_selected_fraction = _as_float(sensor_stats.get("bad_selected_fraction"), 0.0)

    if score < 0.55 and gap > 0.3:
        diagnosis.append("Behavior still resembles unrobust averaging; use anomaly scores, robust medians, trimmed means, or sensor consistency checks.")
    elif gap > 0.12:
        diagnosis.append("Good partial robustness, but oracle comparison suggests channel weights or inlier count are not yet well calibrated.")
    else:
        diagnosis.append("Oracle gap is small; focus on reducing tail RMS without increasing saturation.")

    if p95_rms > mean_rms * 1.4:
        diagnosis.append("The high-RMS tail is broad; add safeguards for extreme gain flips and sparse spikes.")
    if saturation_mean > 0.10:
        diagnosis.append("Average saturation is high; command clipping may be hiding over-aggressive fused slopes.")
    if bad_selected_fraction > 0.35:
        diagnosis.append("The anomaly model's selected inliers still include many known-corrupted sensors; combine anomaly score with robust distance checks.")
    if trace_metrics.get("trace_p95_command_slew_l2", 0.0) > trace_metrics.get("trace_mean_command_l2", 0.0) * 1.2:
        diagnosis.append("Command changes are spiky across cases; smoother weighting or shrinkage may improve p95 RMS.")
    return diagnosis


def _format_feedback(metrics: dict[str, Any], trace_metrics: dict[str, float], diagnosis: list[str]) -> str:
    lines = [
        f"Score: {_as_float(metrics.get('combined_score'), _as_float(metrics.get('candidate_score'))):.4f}",
        f"Oracle gap: {_as_float(metrics.get('score_gap_oracle_minus_candidate'), 0.0):.4f}",
        f"RMS mean/p95/p99: {trace_metrics.get('trace_mean_rms', 0.0):.4f} / {trace_metrics.get('trace_p95_rms', 0.0):.4f} / {trace_metrics.get('trace_p99_rms', 0.0):.4f}",
        f"Strehl mean/p05: {trace_metrics.get('trace_mean_strehl', 0.0):.4f} / {trace_metrics.get('trace_p05_strehl', 0.0):.4f}",
        f"Saturation mean/max: {trace_metrics.get('trace_mean_saturation_fraction', 0.0):.4f} / {trace_metrics.get('trace_max_saturation_fraction', 0.0):.4f}",
        f"Command L2 mean/p95: {trace_metrics.get('trace_mean_command_l2', 0.0):.4f} / {trace_metrics.get('trace_p95_command_l2', 0.0):.4f}",
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

    raw = load_raw_artifact(output_dir)
    metrics = _metrics_from(result, raw)
    trace = _case_trace(raw)
    trace_metrics = _trace_metrics(trace)
    sensor_stats = _sensor_selection_stats(trace)
    diagnosis = _diagnosis(metrics, trace_metrics, sensor_stats)
    return {
        "processed_feedback": _format_feedback(metrics, trace_metrics, diagnosis),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score"), 0.0),
            "valid": 1.0 if _as_float(metrics.get("valid"), 0.0) > 0.0 else 0.0,
            "score_gap_oracle_minus_candidate": _as_float(metrics.get("score_gap_oracle_minus_candidate"), 0.0),
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
            **trace_metrics,
        },
        "analysis": {
            "diagnosis": diagnosis,
            "worst_cases": _worst_cases(trace),
            "sensor_selection": sensor_stats,
            "command_stats": (raw or {}).get("command_stats") if raw else {},
            "raw_artifact_present": raw is not None,
        },
    }
