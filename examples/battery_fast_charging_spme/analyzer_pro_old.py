"""PRO-mode analyzer for BatteryFastChargingSPMe raw trajectories."""

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


def _policy(raw: dict[str, Any] | None, metrics: dict[str, Any]) -> dict[str, Any]:
    if raw and isinstance(raw.get("policy"), dict):
        return dict(raw["policy"])
    return {
        "currents_c": metrics.get("currents_c", []),
        "switch_soc": metrics.get("switch_soc", []),
    }


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


def _trajectory_metrics(raw: dict[str, Any] | None) -> dict[str, float]:
    steps, events = _trajectory(raw)
    stage_stats = _stage_stats(raw)
    crossings = _first_crossings(raw)
    high_soc_high_current_steps = _as_float((raw or {}).get("derived", {}).get("high_soc_high_current_steps", 0.0)) if isinstance((raw or {}).get("derived"), dict) else 0.0

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


def _diagnosis(metrics: dict[str, Any], raw: dict[str, Any] | None) -> list[str]:
    diagnosis: list[str] = []
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    failure_reason = str(metrics.get("failure_reason") or "")
    stage_stats = _stage_stats(raw)
    soc_bands = _soc_band_stats(raw)
    crossings = _first_crossings(raw)
    policy = _policy(raw, metrics)

    if valid:
        diagnosis.append("Hard constraints passed; tune tradeoffs among time, voltage, thermal, plating, and aging scores.")
    elif failure_reason:
        diagnosis.append(f"Invalid policy due to {failure_reason}; use the first crossing and worst-stage data below to localize the fix.")
    else:
        diagnosis.append("Invalid policy with no explicit failure reason; inspect policy validation and raw artifact warnings.")

    if crossings:
        ordered = sorted(crossings.items(), key=lambda item: _as_float(item[1].get("time_s")))
        first_name, first = ordered[0]
        diagnosis.append(
            f"First constraint crossing is {first_name} at t={_as_float(first.get('time_s')):.0f}s, SOC={_as_float(first.get('soc')):.3f}, value={_as_float(first.get('value')):.5f}."
        )

    voltage_stage = _worst_stage(stage_stats, "max_voltage_v", higher_is_worse=True)
    if voltage_stage:
        diagnosis.append(
            f"Highest-voltage stage {int(_as_float(voltage_stage.get('stage_idx')))} reaches {_as_float(voltage_stage.get('max_voltage_v')):.4f} V over {int(_as_float(voltage_stage.get('step_count')))} steps."
        )

    plating_stage = _worst_stage(stage_stats, "min_plating_margin_v", higher_is_worse=False)
    if plating_stage:
        diagnosis.append(
            f"Lowest plating-margin stage {int(_as_float(plating_stage.get('stage_idx')))} reaches {_as_float(plating_stage.get('min_plating_margin_v')):.5f} V."
        )

    temp_stage = _worst_stage(stage_stats, "max_temp_c", higher_is_worse=True)
    if temp_stage and _as_float(temp_stage.get("max_temp_c")) > 33.0:
        diagnosis.append(
            f"Thermal stress peaks in stage {int(_as_float(temp_stage.get('stage_idx')))} at {_as_float(temp_stage.get('max_temp_c')):.2f} C."
        )

    late_band = soc_bands.get("soc_0.70_0.90") if isinstance(soc_bands, dict) else None
    if isinstance(late_band, dict):
        avg_current = _as_float(late_band.get("avg_current_c"))
        min_margin = _as_float(late_band.get("min_plating_margin_v"))
        max_voltage = _as_float(late_band.get("max_voltage_v"))
        if avg_current > 2.5 and (min_margin < 0.02 or max_voltage > 4.2):
            diagnosis.append(
                f"Late SOC band averages {avg_current:.2f}C with max voltage {max_voltage:.4f} V and min plating margin {min_margin:.5f} V; consider a gentler late stage."
            )

    currents = policy.get("currents_c") or []
    switches = policy.get("switch_soc") or []
    diagnosis.append(f"Policy stages: currents={currents}, switch_soc={switches}.")
    return diagnosis


def _format_feedback(metrics: dict[str, Any], raw: dict[str, Any] | None, trajectory_metrics: dict[str, float]) -> str:
    lines = [
        f"Score: {_as_float(metrics.get('combined_score'), _as_float(metrics.get('score'))):.4f}",
        f"Valid: {_as_float(metrics.get('valid'), 0.0) > 0.0}",
        f"Failure reason: {metrics.get('failure_reason', '') or 'none'}",
        f"Charge time seconds: {_as_float(metrics.get('charge_time_s')):.1f}",
        f"Max voltage V: {_as_float(metrics.get('max_voltage_v')):.4f}",
        f"Max temp C: {_as_float(metrics.get('max_temp_c')):.3f}",
        f"Min plating margin V: {_as_float(metrics.get('min_plating_margin_v')):.5f}",
        f"Trajectory steps: {int(trajectory_metrics.get('trajectory_step_count', 0.0))}",
    ]
    for item in _diagnosis(metrics, raw):
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
    trajectory_metrics = _trajectory_metrics(raw)
    diagnosis = _diagnosis(metrics, raw)
    stage_stats = _stage_stats(raw)
    soc_band_stats = _soc_band_stats(raw)
    first_crossings = _first_crossings(raw)
    return {
        "processed_feedback": _format_feedback(metrics, raw, trajectory_metrics),
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
            "diagnosis": diagnosis,
            "stage_stats": stage_stats,
            "soc_band_stats": soc_band_stats,
            "first_limit_crossings": first_crossings,
            "raw_artifact_present": raw is not None,
        },
    }
