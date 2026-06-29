"""Evolved analyzer: tracks yaw dynamics, lateral drift profile, and velocity breakdown by gait phase."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_angle(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


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


def _trajectory_steps(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    traj = raw.get("trajectory")
    if not isinstance(traj, dict):
        return []
    steps = traj.get("steps")
    return list(steps) if isinstance(steps, list) else []


def _artifacts_from(raw: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any]:
    if raw and isinstance(raw.get("artifacts"), dict):
        return dict(raw["artifacts"])
    construction = result.get("construction")
    if isinstance(construction, dict) and isinstance(construction.get("summary"), dict):
        return dict(construction["summary"])
    return {}


def _derived(raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw and isinstance(raw.get("derived"), dict):
        return dict(raw["derived"])
    return {}


def _quat_to_yaw(qw: float, qx: float, qy: float, qz: float) -> float:
    """Extract yaw (heading) from quaternion wxyz."""
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)


def _quat_to_roll(qw: float, qx: float, qy: float, qz: float) -> float:
    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    return math.atan2(sinr_cosp, cosr_cosp)


def _quat_to_pitch(qw: float, qx: float, qy: float, qz: float) -> float:
    sinp = 2.0 * (qw * qy - qz * qx)
    return math.asin(max(-1.0, min(1.0, sinp)))


def _compute_advanced(raw: dict[str, Any] | None) -> dict[str, Any]:
    steps = _trajectory_steps(raw)
    if len(steps) < 10:
        return {}

    n = len(steps)
    durations = []
    yaws = []
    roll_vs = []
    pitch_vs = []
    dt = 0.01

    for step in steps:
        qpos = step.get("qpos")
        if isinstance(qpos, list) and len(qpos) >= 7:
            qw, qx, qy, qz = map(_as_float, qpos[3:7])
        else:
            qw, qx, qy, qz = 1.0, 0.0, 0.0, 0.0
        yaws.append(_quat_to_yaw(qw, qx, qy, qz))
        roll_vs.append(_quat_to_roll(qw, qx, qy, qz))
        pitch_vs.append(_quat_to_pitch(qw, qx, qy, qz))
        durations.append(_as_float(step.get("time_s")))

    total_yaw_change = _normalize_angle(yaws[-1] - yaws[0])
    half = n // 2
    first_half_yaw = _normalize_angle(yaws[half - 1] - yaws[0]) if half > 0 else 0.0
    second_half_yaw = _normalize_angle(yaws[-1] - yaws[half]) if n - half > 0 else 0.0

    yaw_diffs = [_normalize_angle(yaws[i + 1] - yaws[i]) for i in range(n - 1)]
    yaw_rate_abs_mean = sum(abs(d) for d in yaw_diffs) / max(1, len(yaw_diffs)) / dt if yaw_diffs else 0.0

    yaw_wrapped = [math.atan2(math.sin(y), math.cos(y)) for y in yaws]
    yaw_zero_crossings = sum(
        1 for i in range(1, len(yaw_wrapped)) if yaw_wrapped[i] * yaw_wrapped[i - 1] < 0
    )

    roll_early = max(abs(r) for r in roll_vs[: n // 4]) if n // 4 > 0 else 0.0
    roll_late = max(abs(r) for r in roll_vs[-n // 4 :]) if n // 4 > 0 else 0.0

    return {
        "total_yaw_rad": round(total_yaw_change, 6),
        "first_half_yaw_rad": round(first_half_yaw, 6),
        "second_half_yaw_rad": round(second_half_yaw, 6),
        "yaw_rate_abs_mean_rad_per_s": round(yaw_rate_abs_mean, 6),
        "yaw_direction_changes": yaw_zero_crossings,
        "roll_early_max_rad": round(roll_early, 6),
        "roll_late_max_rad": round(roll_late, 6),
    }


def _diagnosis(metrics: dict[str, Any], artifacts: dict[str, Any], derived: dict[str, Any], advanced: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    error = str(artifacts.get("error_message") or metrics.get("failure_reason") or "")

    if valid:
        diagnosis.append("Gait is feasible under attitude, actuator-force, and progress constraints.")
    elif "submission.json" in error:
        diagnosis.append("Candidate did not produce the required submission.json file.")
    elif "out of range" in error:
        diagnosis.append("At least one gait parameter is outside its allowed range.")
    elif "candidate timeout" in error:
        diagnosis.append("Candidate timed out before producing a valid submission.")
    elif "attitude" in error or "fell" in error:
        diagnosis.append("Robot exceeded roll/pitch limits; reduce destabilizing phase or stride geometry.")
    elif "force" in error or "torque" in error:
        diagnosis.append("Actuator force limit was exceeded; reduce control aggressiveness via step length/height/frequency.")
    elif "progress" in error or "infeasible" in error:
        diagnosis.append("Rollout failed feasibility, often due to insufficient forward progress or early constraint violation.")
    elif error:
        diagnosis.append(f"Evaluation error: {error}")
    else:
        diagnosis.append("Policy is invalid; inspect raw trajectory events for the first failure.")

    max_roll = _as_float(derived.get("max_abs_roll_rad"), 0.0)
    max_pitch = _as_float(derived.get("max_abs_pitch_rad"), 0.0)
    max_force = _as_float(derived.get("max_abs_actuator_force"), 0.0)
    distance = _as_float(derived.get("final_distance_m"), 0.0)
    torque_sat = _as_float(derived.get("torque_saturation_fraction"), 0.0)

    if max_roll > 0.5 or max_pitch > 0.5:
        diagnosis.append(f"Attitude margin is thin: max roll={max_roll:.3f}, max pitch={max_pitch:.3f} rad.")
    if max_force > 0.9:
        diagnosis.append(f"Actuator force is near limit: max abs force={max_force:.3f}.")
    if torque_sat > 0.05:
        diagnosis.append(f"Torque saturation appears on {torque_sat:.1%} of traced steps.")
    if distance < 0.15:
        diagnosis.append(f"Forward progress is low: distance={distance:.4f} m.")

    total_yaw = advanced.get("total_yaw_rad", 0.0)
    if abs(total_yaw) > 1.0:
        direction = "right" if total_yaw > 0 else "left"
        diagnosis.append(f"Large net yaw of {total_yaw:.2f} rad to the {direction} may limit forward speed.")
    elif abs(total_yaw) > 0.3:
        direction = "right" if total_yaw > 0 else "left"
        diagnosis.append(f"Moderate net yaw of {total_yaw:.2f} rad to the {direction}.")

    stance_fractions = derived.get("stance_fractions")
    if isinstance(stance_fractions, dict):
        for leg, frac in sorted(stance_fractions.items()):
            value = _as_float(frac)
            if value < 0.25 or value > 0.90:
                diagnosis.append(f"{leg} stance fraction is unusual ({value:.2f}); check duty factor and phase offsets.")

    return diagnosis


def _format_feedback(metrics: dict[str, Any], artifacts: dict[str, Any], derived: dict[str, Any], advanced: dict[str, Any], raw_present: bool) -> str:
    score = _as_float(metrics.get("combined_score"), _as_float(metrics.get("score"), 0.0))
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    lines = [
        f"Score: {score:.6f}",
        f"Valid: {valid}",
        f"Feasible: {_as_float(metrics.get('feasible'), 0.0) > 0.0}",
        f"Speed m/s: {_as_float(metrics.get('speed_mps'), score):.6f}",
        f"Final distance m: {_as_float(derived.get('final_distance_m')):.4f}",
        f"Trace steps: {int(_as_float(derived.get('step_count')))}",
        f"Max abs roll rad: {_as_float(derived.get('max_abs_roll_rad')):.4f}",
        f"Max abs pitch rad: {_as_float(derived.get('max_abs_pitch_rad')):.4f}",
        f"Max abs actuator force: {_as_float(derived.get('max_abs_actuator_force')):.4f}",
        f"Torque saturation fraction: {_as_float(derived.get('torque_saturation_fraction')):.3f}",
        f"Total yaw rad: {advanced.get('total_yaw_rad', 0.0):.4f}",
        f"Yaw rate mean rad/s: {advanced.get('yaw_rate_abs_mean_rad_per_s', 0.0):.4f}",
    ]
    submission = derived.get("submission")
    if isinstance(submission, dict) and submission:
        lines.append(f"Submission: {submission}")
    for item in _diagnosis(metrics, artifacts, derived, advanced):
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
    artifacts = _artifacts_from(raw, result)
    derived = _derived(raw)
    advanced = _compute_advanced(raw)
    diagnosis = _diagnosis(metrics, artifacts, derived, advanced)
    return {
        "processed_feedback": _format_feedback(metrics, artifacts, derived, advanced, raw is not None),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score"), 0.0),
            "valid": 1.0 if _as_float(metrics.get("valid"), 0.0) > 0.0 else 0.0,
            "speed_mps": _as_float(metrics.get("speed_mps"), 0.0),
            "final_distance_m": _as_float(derived.get("final_distance_m"), 0.0),
            "trajectory_step_count": _as_float(derived.get("step_count"), 0.0),
            "max_abs_roll_rad": _as_float(derived.get("max_abs_roll_rad"), 0.0),
            "max_abs_pitch_rad": _as_float(derived.get("max_abs_pitch_rad"), 0.0),
            "max_abs_actuator_force": _as_float(derived.get("max_abs_actuator_force"), 0.0),
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
            **advanced,
        },
        "analysis": {
            "diagnosis": diagnosis,
            "derived": derived,
            "advanced_yaw": advanced,
            "raw_artifact_present": raw is not None,
        },
    }
