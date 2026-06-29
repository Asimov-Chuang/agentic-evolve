"""PRO-mode analyzer for UAV inspection stepwise traces."""

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


def _coverage_timing(scene: dict[str, Any]) -> dict[str, float]:
    first_cover_times: dict[int, float] = {}
    for step in scene.get("trace", []):
        t = _as_float(step.get("t"))
        for idx in step.get("covered_this_step", []) or []:
            point_idx = int(idx)
            first_cover_times.setdefault(point_idx, t)
    if not first_cover_times:
        return {"first_cover_count": 0.0}
    values = list(first_cover_times.values())
    return {
        "first_cover_count": float(len(values)),
        "first_cover_min_t": min(values),
        "first_cover_max_t": max(values),
        "first_cover_mean_t": sum(values) / len(values),
    }


def _near_miss_counts(scene: dict[str, Any]) -> dict[str, float]:
    dynamic_near = 0
    no_fly_near = 0
    boundary_near = 0
    speed_high = 0
    accel_high = 0
    for step in scene.get("trace", []):
        dyn = step.get("post_nearest_dynamic_obstacle") or step.get("nearest_dynamic_obstacle")
        if isinstance(dyn, dict) and dyn.get("clearance") is not None and _as_float(dyn.get("clearance")) < 0.5:
            dynamic_near += 1
        no_fly_clearance = step.get("post_no_fly_clearance", step.get("no_fly_clearance"))
        if no_fly_clearance is not None and _as_float(no_fly_clearance) < 0.5:
            no_fly_near += 1
        boundary_clearance = step.get("post_boundary_clearance", step.get("boundary_clearance"))
        if boundary_clearance is not None and _as_float(boundary_clearance) < 0.5:
            boundary_near += 1
        if _as_float(step.get("speed_norm_after", step.get("speed_norm"))) > 0.95 * _scene_vmax(scene):
            speed_high += 1
        if _as_float(step.get("acceleration_norm")) > 0.95 * _scene_amax(scene):
            accel_high += 1
    return {
        "dynamic_near_miss_steps": float(dynamic_near),
        "no_fly_near_miss_steps": float(no_fly_near),
        "boundary_near_miss_steps": float(boundary_near),
        "speed_high_steps": float(speed_high),
        "acceleration_high_steps": float(accel_high),
    }


def _scene_vmax(scene: dict[str, Any]) -> float:
    summary = scene.get("summary") or {}
    max_speed = _as_float(summary.get("max_speed_norm"))
    max_ratio = _as_float(summary.get("max_speed_ratio"))
    if max_ratio > 0.0:
        return max_speed / max(max_ratio, 1e-12)
    return 1e9


def _scene_amax(scene: dict[str, Any]) -> float:
    summary = scene.get("summary") or {}
    max_acc = _as_float(summary.get("max_acceleration_norm"))
    max_ratio = _as_float(summary.get("max_acceleration_ratio"))
    if max_ratio > 0.0:
        return max_acc / max(max_ratio, 1e-12)
    return 1e9


def extract_trace_metrics(raw: dict[str, Any] | None) -> dict[str, float]:
    if not raw:
        return {}
    metrics: dict[str, float] = {}
    scenes = raw.get("scenes") or []
    metrics["raw_scene_count"] = float(len(scenes))
    metrics["raw_trace_step_count"] = float(sum(len(scene.get("trace", [])) for scene in scenes))

    worst_scene = None
    worst_coverage = 2.0
    for scene in scenes:
        scene_id = str(scene.get("scene_id", "unknown"))
        coverage = _as_float(scene.get("coverage_ratio", scene.get("coverage_ratio_at_failure")))
        if coverage < worst_coverage:
            worst_coverage = coverage
            worst_scene = scene_id
        summary = scene.get("summary") or {}
        metrics[f"trace_steps_{scene_id}"] = float(len(scene.get("trace", [])))
        metrics[f"coverage_{scene_id}"] = coverage
        metrics[f"energy_{scene_id}"] = _as_float(scene.get("energy", scene.get("energy_at_failure")))
        metrics[f"max_speed_ratio_{scene_id}"] = _as_float(summary.get("max_speed_ratio"))
        metrics[f"max_acceleration_ratio_{scene_id}"] = _as_float(summary.get("max_acceleration_ratio"))
        if summary.get("min_dynamic_clearance") is not None:
            metrics[f"min_dynamic_clearance_{scene_id}"] = _as_float(summary.get("min_dynamic_clearance"))
        if summary.get("min_no_fly_clearance") is not None:
            metrics[f"min_no_fly_clearance_{scene_id}"] = _as_float(summary.get("min_no_fly_clearance"))
        if summary.get("min_boundary_clearance") is not None:
            metrics[f"min_boundary_clearance_{scene_id}"] = _as_float(summary.get("min_boundary_clearance"))
        for key, value in _coverage_timing(scene).items():
            metrics[f"{key}_{scene_id}"] = value
        for key, value in _near_miss_counts(scene).items():
            metrics[f"{key}_{scene_id}"] = value
    if worst_scene is not None:
        metrics["worst_scene_coverage"] = worst_coverage
    return metrics


def _scene_rankings(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    scenes = (raw or {}).get("scenes") or []
    ranking = []
    for scene in scenes:
        summary = scene.get("summary") or {}
        ranking.append(
            {
                "scene_id": scene.get("scene_id"),
                "success": bool(scene.get("success")),
                "reason": scene.get("reason"),
                "coverage": scene.get("coverage_ratio", scene.get("coverage_ratio_at_failure")),
                "energy": scene.get("energy", scene.get("energy_at_failure")),
                "score": scene.get("scene_score"),
                "max_speed_ratio": summary.get("max_speed_ratio"),
                "max_acceleration_ratio": summary.get("max_acceleration_ratio"),
                "min_dynamic_clearance": summary.get("min_dynamic_clearance"),
                "min_no_fly_clearance": summary.get("min_no_fly_clearance"),
                "first_failure": scene.get("first_failure"),
            }
        )
    return sorted(ranking, key=lambda item: (_as_float(item.get("coverage")), bool(item.get("success"))))


def _diagnosis(result: dict[str, Any], raw: dict[str, Any] | None, metrics: dict[str, Any], trace_metrics: dict[str, float]) -> list[str]:
    diagnosis: list[str] = []
    if not raw:
        return ["Raw trace artifact missing; pro feedback cannot inspect trajectory."]

    ranking = _scene_rankings(raw)
    if ranking:
        worst = ranking[0]
        diagnosis.append(
            f"Worst scene is {worst['scene_id']} with coverage={_as_float(worst.get('coverage')):.3f}, "
            f"success={worst.get('success')}."
        )
        if not worst.get("success"):
            diagnosis.append(f"Failure details: {worst.get('first_failure') or worst.get('reason')}.")

    if _as_float(metrics.get("max_speed_ratio")) > 0.98:
        diagnosis.append("Trajectory reaches the speed limit; maintain margin before turns and obstacle avoidance.")
    elif _as_float(metrics.get("max_speed_ratio")) < 0.75 and _as_float(metrics.get("mean_coverage_ratio")) < 0.9:
        diagnosis.append("Speed usage is conservative while coverage is incomplete; consider more aggressive cruise targets.")

    if _as_float(metrics.get("max_acceleration_ratio")) > 0.98:
        diagnosis.append("Acceleration commands saturate; smooth repulsion or target switching to avoid invalid spikes.")

    min_dynamic = metrics.get("min_dynamic_clearance")
    if min_dynamic is not None and _as_float(min_dynamic) < 0.5:
        diagnosis.append("Dynamic obstacle clearance is low; add earlier prediction or route around moving obstacle corridors.")

    min_no_fly = metrics.get("min_no_fly_clearance")
    if min_no_fly is not None and _as_float(min_no_fly) < 0.5:
        diagnosis.append("No-fly-zone clearance is low; repel from nearest box face earlier instead of reacting late.")

    near_dynamic_total = sum(value for key, value in trace_metrics.items() if key.startswith("dynamic_near_miss_steps_"))
    if near_dynamic_total > 20:
        diagnosis.append(f"There are many dynamic-obstacle near-miss steps ({near_dynamic_total:.0f}); avoidance may be too late.")

    if not result.get("is_valid") and not diagnosis:
        diagnosis.append(f"Invalid attempt: {result.get('feedback', '')}")
    return diagnosis


def format_processed_feedback(
    result: dict[str, Any],
    metrics: dict[str, Any],
    raw: dict[str, Any] | None,
    trace_metrics: dict[str, float],
    diagnosis: list[str],
) -> str:
    lines = [
        f"Score: {_as_float(metrics.get('combined_score')):.6f} (valid={int(bool(result.get('is_valid')))})",
        f"Scenes ok: {int(_as_float(metrics.get('successful_scene_count')))}/{int(_as_float(metrics.get('scene_count')))}",
        f"Coverage mean/min: {_as_float(metrics.get('mean_coverage_ratio')):.3f}/{_as_float(metrics.get('min_coverage_ratio')):.3f}",
        f"Total energy: {_as_float(metrics.get('total_energy')):.3f}",
        f"Speed/acc max ratios: {_as_float(metrics.get('max_speed_ratio')):.3f}/{_as_float(metrics.get('max_acceleration_ratio')):.3f}",
        f"Trace steps: {int(_as_float(trace_metrics.get('raw_trace_step_count')))}",
    ]
    for item in _scene_rankings(raw):
        lines.append(
            f"{item['scene_id']}: coverage={_as_float(item.get('coverage')):.3f}, "
            f"energy={_as_float(item.get('energy')):.3f}, success={int(bool(item.get('success')))}, "
            f"min_dyn={item.get('min_dynamic_clearance')}, min_no_fly={item.get('min_no_fly_clearance')}"
        )
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
    trace_metrics = extract_trace_metrics(raw)
    diagnosis = _diagnosis(result, raw, metrics, trace_metrics)

    return {
        "processed_feedback": format_processed_feedback(result, metrics, raw, trace_metrics, diagnosis),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score")),
            "valid": 1.0 if result.get("is_valid") else 0.0,
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
            "mean_coverage_ratio": _as_float(metrics.get("mean_coverage_ratio")),
            "min_coverage_ratio": _as_float(metrics.get("min_coverage_ratio")),
            "total_energy": _as_float(metrics.get("total_energy")),
            "max_speed_ratio": _as_float(metrics.get("max_speed_ratio")),
            "max_acceleration_ratio": _as_float(metrics.get("max_acceleration_ratio")),
            **trace_metrics,
        },
        "analysis": {
            "diagnosis": diagnosis,
            "scene_rankings": _scene_rankings(raw),
            "trace_metrics": trace_metrics,
            "derived": (raw or {}).get("derived", {}),
            "submission_summary": (raw or {}).get("submission_summary", {}),
        },
    }