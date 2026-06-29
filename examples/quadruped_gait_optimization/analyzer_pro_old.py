"""PRO-mode analyzer for Quadruped Gait Optimization raw MuJoCo traces."""

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


def _derived(raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw and isinstance(raw.get("derived"), dict):
        return dict(raw["derived"])
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


def _trajectory_metrics(raw: dict[str, Any] | None) -> dict[str, float]:
    derived = _derived(raw)
    steps, events = _trajectory(raw)
    metrics = {
        "trajectory_step_count": float(len(steps)),
        "trajectory_event_count": float(len(events)),
        "final_distance_m": _as_float(derived.get("final_distance_m"), 0.0),
        "derived_speed_mps": _as_float(derived.get("derived_speed_mps"), 0.0),
        "max_abs_roll_rad": _as_float(derived.get("max_abs_roll_rad"), 0.0),
        "max_abs_pitch_rad": _as_float(derived.get("max_abs_pitch_rad"), 0.0),
        "max_abs_actuator_force": _as_float(derived.get("max_abs_actuator_force"), 0.0),
        "max_abs_ctrl": _as_float(derived.get("max_abs_ctrl"), 0.0),
        "min_body_height_m": _as_float(derived.get("min_body_height_m"), 0.0),
        "max_abs_lateral_y_m": _as_float(derived.get("max_abs_lateral_y_m"), 0.0),
        "avg_forward_velocity_mps": _as_float(derived.get("avg_forward_velocity_mps"), 0.0),
        "avg_abs_ctrl": _as_float(derived.get("avg_abs_ctrl"), 0.0),
        "torque_saturation_fraction": _as_float(derived.get("torque_saturation_fraction"), 0.0),
    }
    stance = derived.get("stance_fractions")
    if isinstance(stance, dict):
        for leg, value in stance.items():
            metrics[f"stance_fraction_{leg}"] = _as_float(value)
    if steps:
        early = steps[: max(1, len(steps) // 4)]
        late = steps[-max(1, len(steps) // 4) :]
        metrics["early_avg_velocity_mps"] = sum(_as_float(step.get("forward_velocity_mps")) for step in early) / len(early)
        metrics["late_avg_velocity_mps"] = sum(_as_float(step.get("forward_velocity_mps")) for step in late) / len(late)
    return metrics


def _diagnosis(metrics: dict[str, Any], raw: dict[str, Any] | None, trajectory_metrics: dict[str, float]) -> list[str]:
    diagnosis: list[str] = []
    derived = _derived(raw)
    _, events = _trajectory(raw)
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    if valid:
        diagnosis.append("Hard constraints passed; optimize speed while preserving stability and force margins.")
    else:
        first_event = events[0] if events else derived.get("first_constraint_crossing")
        if isinstance(first_event, dict) and first_event:
            diagnosis.append(f"First trajectory event: {first_event}.")
        else:
            diagnosis.append("Invalid rollout; inspect candidate execution and trace availability.")

    max_roll = trajectory_metrics.get("max_abs_roll_rad", 0.0)
    max_pitch = trajectory_metrics.get("max_abs_pitch_rad", 0.0)
    max_force = trajectory_metrics.get("max_abs_actuator_force", 0.0)
    torque_sat = trajectory_metrics.get("torque_saturation_fraction", 0.0)
    distance = trajectory_metrics.get("final_distance_m", 0.0)
    late_velocity = trajectory_metrics.get("late_avg_velocity_mps")
    early_velocity = trajectory_metrics.get("early_avg_velocity_mps")

    if max_roll > 0.45 or max_pitch > 0.45:
        diagnosis.append(f"Attitude oscillation is high: roll={max_roll:.3f}, pitch={max_pitch:.3f} rad.")
    if max_force > 0.9:
        diagnosis.append(f"Actuator force approaches the limit: max={max_force:.3f}; reduce aggressive step geometry or frequency.")
    if torque_sat > 0.02:
        diagnosis.append(f"Torque saturation fraction is {torque_sat:.1%}; this can cap speed and destabilize the gait.")
    if distance < 0.15:
        diagnosis.append(f"Forward progress is below threshold: {distance:.4f} m.")
    if late_velocity is not None and early_velocity is not None and late_velocity < 0.5 * max(early_velocity, 1e-9):
        diagnosis.append(f"Late rollout velocity ({late_velocity:.3f}) drops far below early velocity ({early_velocity:.3f}); gait may stall or destabilize.")

    stance = derived.get("stance_fractions")
    if isinstance(stance, dict) and stance:
        stance_parts = ", ".join(f"{leg}={_as_float(value):.2f}" for leg, value in sorted(stance.items()))
        diagnosis.append(f"Stance fractions: {stance_parts}.")
    phase_offsets = derived.get("phase_offsets")
    if isinstance(phase_offsets, dict) and phase_offsets:
        diagnosis.append(f"Phase offsets: {phase_offsets}.")

    return diagnosis


def _format_feedback(metrics: dict[str, Any], raw: dict[str, Any] | None, trajectory_metrics: dict[str, float]) -> str:
    score = _as_float(metrics.get("combined_score"), _as_float(metrics.get("score"), 0.0))
    lines = [
        f"Score: {score:.6f}",
        f"Valid: {_as_float(metrics.get('valid'), 0.0) > 0.0}",
        f"Speed m/s: {_as_float(metrics.get('speed_mps'), score):.6f}",
        f"Final distance m: {trajectory_metrics.get('final_distance_m', 0.0):.4f}",
        f"Trace steps: {int(trajectory_metrics.get('trajectory_step_count', 0.0))}",
        f"Max abs roll rad: {trajectory_metrics.get('max_abs_roll_rad', 0.0):.4f}",
        f"Max abs pitch rad: {trajectory_metrics.get('max_abs_pitch_rad', 0.0):.4f}",
        f"Max abs actuator force: {trajectory_metrics.get('max_abs_actuator_force', 0.0):.4f}",
        f"Torque saturation fraction: {trajectory_metrics.get('torque_saturation_fraction', 0.0):.3f}",
    ]
    for item in _diagnosis(metrics, raw, trajectory_metrics):
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
    diagnosis = _diagnosis(metrics, raw, trajectory_metrics)
    return {
        "processed_feedback": _format_feedback(metrics, raw, trajectory_metrics),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score"), 0.0),
            "valid": 1.0 if _as_float(metrics.get("valid"), 0.0) > 0.0 else 0.0,
            "speed_mps": _as_float(metrics.get("speed_mps"), 0.0),
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
            **trajectory_metrics,
        },
        "analysis": {
            "diagnosis": diagnosis,
            "derived": _derived(raw),
            "trajectory_metrics": trajectory_metrics,
            "raw_artifact_present": raw is not None,
        },
    }
