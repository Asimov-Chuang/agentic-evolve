#!/usr/bin/env python3
"""PRO-mode analyzer for BatteryFastChargingSPMe raw trajectories.
Enhanced with per-stage voltage slope, headroom, and bottleneck diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
    construction = result.get("construction")
    if isinstance(construction, dict) and isinstance(construction.get("metrics"), dict):
        return dict(construction["metrics"])
    if raw and isinstance(raw.get("metrics"), dict):
        return dict(raw["metrics"])
    return {}


def _trajectory(raw: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not raw:
        return [], []
    trajectory = raw.get("trajectory")
    if not isinstance(trajectory, dict):
        return [], []
    steps = trajectory.get("steps")
    events = trajectory.get("events")
    return (
        list(steps) if isinstance(steps, list) else [],
        list(events) if isinstance(events, list) else [],
    )


def _stage_stats(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    derived = (raw or {}).get("derived")
    if isinstance(derived, dict) and isinstance(derived.get("stage_stats"), list):
        return list(derived["stage_stats"])
    return []


def _soc_band_stats(raw: dict[str, Any] | None) -> dict[str, Any]:
    derived = (raw or {}).get("derived")
    if isinstance(derived, dict) and isinstance(derived.get("soc_band_stats"), dict):
        return dict(derived["soc_band_stats"])
    return {}


def _first_crossings(raw: dict[str, Any] | None) -> dict[str, Any]:
    derived = (raw or {}).get("derived")
    if isinstance(derived, dict) and isinstance(derived.get("first_limit_crossings"), dict):
        return dict(derived["first_limit_crossings"])
    return {}


def _worst_stage(stage_stats: list[dict[str, Any]], field: str, *, higher_is_worse: bool) -> dict[str, Any] | None:
    populated = [item for item in stage_stats if _as_float(item.get("step_count"), 0.0) > 0.0 and field in item]
    if not populated:
        return None
    return sorted(populated, key=lambda item: _as_float(item.get(field)), reverse=higher_is_worse)[0]


def compute_headroom(
    steps: list[dict[str, Any]], stage_stats: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compute voltage/thermal headroom and slope for each stage."""
    if not steps:
        return {}

    # Group steps by stage
    stages: dict[int, list[dict[str, Any]]] = {}
    for s in steps:
        idx = int(_as_float(s.get("stage_idx"), 0))
        stages.setdefault(idx, []).append(s)

    info = {}
    for idx, stage_steps in sorted(stages.items()):
        if len(stage_steps) < 3:
            continue
        first = stage_steps[0]
        last = stage_steps[-1]
        soc_start = _as_float(first.get("soc"))
        soc_end = _as_float(last.get("soc"))
        v_start = _as_float(first.get("voltage_v"))
        v_end = _as_float(last.get("voltage_v"))
        dv = v_end - v_start
        dsoc = soc_end - soc_start
        slope_v_per_soc = dv / dsoc if dsoc > 0 else 0.0

        t_start = _as_float(first.get("temp_c"))
        t_end = _as_float(last.get("temp_c"))

        max_v = max(_as_float(s.get("voltage_v")) for s in stage_steps)
        min_v = min(_as_float(s.get("voltage_v")) for s in stage_steps)
        max_t = max(_as_float(s.get("temp_c")) for s in stage_steps)

        # Overpotential breakdown
        eta_n = _as_float(last.get("eta_n_v", 0))
        eta_p = _as_float(last.get("eta_p_v", 0))
        ocv = _as_float(last.get("open_circuit_voltage_v", 0))

        info[str(idx)] = {
            "soc_range": [round(soc_start, 4), round(soc_end, 4)],
            "current_c": _as_float(first.get("current_c")),
            "v_start": round(v_start, 4),
            "v_end": round(v_end, 4),
            "v_max": round(max_v, 4),
            "v_min": round(min_v, 4),
            "v_slope_per_soc": round(slope_v_per_soc, 4),
            "temp_rise_c": round(t_end - t_start, 3),
            "temp_max": round(max_t, 3),
            "eta_n_v": round(eta_n, 4),
            "eta_p_v": round(eta_p, 4),
            "ocv_v": round(ocv, 4),
            "v_headroom_to_soft": round(4.2 - max_v, 4),
            "v_headroom_to_hard": round(4.25 - max_v, 4),
        }
    return info


def compute_transition_analysis(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Analyze the voltage behavior at each stage switch."""
    if not steps:
        return []
    transitions = []
    for i in range(1, len(steps)):
        prev = steps[i-1]
        curr = steps[i]
        if _as_float(prev.get("stage_idx")) != _as_float(curr.get("stage_idx")):
            transitions.append({
                "switch_soc": round(_as_float(curr.get("soc")), 4),
                "from_stage": int(_as_float(prev.get("stage_idx"))),
                "to_stage": int(_as_float(curr.get("stage_idx"))),
                "v_before_v": round(_as_float(prev.get("voltage_v")), 4),
                "v_after_v": round(_as_float(curr.get("voltage_v")), 4),
                "current_before_c": _as_float(prev.get("current_c")),
                "current_after_c": _as_float(curr.get("current_c")),
                "ocv_v": round(_as_float(curr.get("open_circuit_voltage_v")), 4),
            })
    return transitions


def _trajectory_metrics(raw: dict[str, Any] | None) -> dict[str, float]:
    steps, events = _trajectory(raw)
    stage_stats = _stage_stats(raw)
    crossings = _first_crossings(raw)

    derived = raw.get("derived") if raw else {}
    high_soc_high_current_steps = _as_float(derived.get("high_soc_high_current_steps", 0.0)) if isinstance(derived, dict) else 0.0

    metrics = {
        "trajectory_step_count": float(len(steps)),
        "trajectory_event_count": float(len(events)),
        "stage_count_with_steps": float(sum(1 for item in stage_stats if _as_float(item.get("step_count"), 0.0) > 0.0)),
        "constraint_crossing_count": float(len(crossings)),
        "high_soc_high_current_steps": high_soc_high_current_steps,
    }
    voltage_stage = _worst_stage(stage_stats, "max_voltage_v", higher_is_worse=True)
    temp_stage = _worst_stage(stage_stats, "max_temp_c", higher_is_worse=True)
    plating_stage = _worst_stage(stage_stats, "min_plating_margin_v", higher_is_worse=False)
    if voltage_stage:
        metrics["worst_voltage_stage"] = _as_float(voltage_stage.get("stage_idx"))
        metrics["worst_voltage_stage_max_v"] = _as_float(voltage_stage.get("max_voltage_v"))
    if temp_stage:
        metrics["worst_temp_stage"] = _as_float(temp_stage.get("stage_idx"))
        metrics["worst_temp_stage_max_c"] = _as_float(temp_stage.get("max_temp_c"))
    if plating_stage:
        metrics["worst_plating_stage"] = _as_float(plating_stage.get("stage_idx"))
        metrics["worst_plating_stage_margin_v"] = _as_float(plating_stage.get("min_plating_margin_v"))
    return metrics


def _format_feedback(metrics: dict[str, Any], raw: dict[str, Any] | None, trajectory_metrics: dict[str, float],
                     headroom: dict[str, Any], transitions: list[dict[str, Any]]) -> str:
    lines = [
        f"Score: {_as_float(metrics.get('combined_score'), _as_float(metrics.get('score'))):.4f}",
        f"Valid: {_as_float(metrics.get('valid'), 0.0) > 0.0}",
        f"Failure reason: {metrics.get('failure_reason', '') or 'none'}",
        f"Charge time seconds: {_as_float(metrics.get('charge_time_s')):.1f}",
        f"Max voltage V: {_as_float(metrics.get('max_voltage_v')):.4f}",
        f"Max temp C: {_as_float(metrics.get('max_temp_c')):.3f}",
        f"Min plating margin V: {_as_float(metrics.get('min_plating_margin_v')):.5f}",
    ]
    # Add headroom for bottleneck stages
    bottleneck = None
    min_headroom = 1.0
    for sidx, h in headroom.items():
        hr = h.get("v_headroom_to_soft", 1.0)
        if hr < min_headroom:
            min_headroom = hr
            bottleneck = sidx
    if bottleneck is not None:
        h = headroom[bottleneck]
        lines.append(
            f"Bottleneck: stage {bottleneck} "
            f"(v_headroom={h['v_headroom_to_soft']:.4f}V, "
            f"slope={h['v_slope_per_soc']:.4f} V/SOC, "
            f"temp_max={h['temp_max']:.1f}C)"
        )
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
    trajectory_metrics = _trajectory_metrics(raw)
    stage_stats = _stage_stats(raw)
    soc_band_stats = _soc_band_stats(raw)
    first_crossings = _first_crossings(raw)

    steps, _ = _trajectory(raw)
    headroom = compute_headroom(steps, stage_stats)
    transitions = compute_transition_analysis(steps)

    return {
        "processed_feedback": _format_feedback(metrics, raw, trajectory_metrics, headroom, transitions),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score"), 0.0),
            "valid": 1.0 if _as_float(metrics.get("valid"), 0.0) > 0.0 else 0.0,
            "charge_time_s": _as_float(metrics.get("charge_time_s"), 0.0),
            "max_voltage_v": _as_float(metrics.get("max_voltage_v"), 0.0),
            "max_temp_c": _as_float(metrics.get("max_temp_c"), 0.0),
            "min_plating_margin_v": _as_float(metrics.get("min_plating_margin_v"), 0.0),
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
            **trajectory_metrics,
        },
        "analysis": {
            "stage_stats": stage_stats,
            "soc_band_stats": soc_band_stats,
            "first_limit_crossings": first_crossings,
            "headroom": headroom,
            "transitions": transitions,
            "raw_artifact_present": raw is not None,
        },
    }
