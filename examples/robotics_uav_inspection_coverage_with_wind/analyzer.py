"""Standard analyzer for UAV inspection coverage raw traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def _scene_lines(raw: dict[str, Any] | None) -> list[str]:
    if not raw:
        return []
    lines: list[str] = []
    for scene in raw.get("scenes", []):
        scene_id = scene.get("scene_id", "unknown")
        summary = scene.get("summary") or {}
        trace_steps = int(summary.get("trace_steps", 0) or 0)
        if scene.get("success"):
            lines.append(
                f"{scene_id}: ok, coverage={_as_float(scene.get('coverage_ratio')):.3f}, "
                f"energy={_as_float(scene.get('energy')):.3f}, "
                f"score={_as_float(scene.get('scene_score')):.3f}, steps={trace_steps}"
            )
        else:
            failure = scene.get("first_failure") or {}
            lines.append(
                f"{scene_id}: failed reason={scene.get('reason')}, "
                f"coverage_at_failure={_as_float(scene.get('coverage_ratio_at_failure')):.3f}, "
                f"failure_step={failure.get('step_index')}, failure_t={failure.get('t')}, steps={trace_steps}"
            )
    return lines


def _diagnosis(result: dict[str, Any], raw: dict[str, Any] | None, metrics: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    if not raw:
        diagnosis.append("No raw trace artifact was available; inspect evaluator setup.")
        return diagnosis

    if not result.get("is_valid"):
        first_failure = (raw.get("derived") or {}).get("first_failure")
        if first_failure:
            diagnosis.append(f"First failure: {first_failure}.")
        else:
            diagnosis.append(f"Invalid attempt: {result.get('feedback', '')}")

    min_coverage = _as_float(metrics.get("min_coverage_ratio"))
    if min_coverage < 0.75:
        diagnosis.append(
            f"Worst-scene coverage is low ({min_coverage:.3f}); improve inspection point ordering or cruise speed."
        )

    max_speed_ratio = _as_float(metrics.get("max_speed_ratio"))
    if max_speed_ratio > 0.98:
        diagnosis.append("Speed limit is nearly saturated; add margin before obstacle/boundary maneuvers.")

    max_acc_ratio = _as_float(metrics.get("max_acceleration_ratio"))
    if max_acc_ratio > 0.98:
        diagnosis.append("Acceleration limit is nearly saturated; smooth target changes or reduce repulsion spikes.")

    min_dynamic = metrics.get("min_dynamic_clearance")
    if min_dynamic is not None and _as_float(min_dynamic) < 0.5:
        diagnosis.append(
            f"Dynamic obstacle clearance is tight ({_as_float(min_dynamic):.3f}); increase predictive avoidance horizon."
        )

    min_no_fly = metrics.get("min_no_fly_clearance")
    if min_no_fly is not None and _as_float(min_no_fly) < 0.5:
        diagnosis.append(
            f"No-fly clearance is tight ({_as_float(min_no_fly):.3f}); route around boxes earlier."
        )

    return diagnosis


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
    diagnosis = _diagnosis(result, raw, metrics)

    lines = [
        f"Score: {_as_float(metrics.get('combined_score')):.6f}",
        f"Valid: {bool(result.get('is_valid'))}",
        f"Scenes ok: {int(_as_float(metrics.get('successful_scene_count')))}/{int(_as_float(metrics.get('scene_count')))}",
        f"Mean coverage: {_as_float(metrics.get('mean_coverage_ratio')):.3f}",
        f"Total energy: {_as_float(metrics.get('total_energy')):.3f}",
        f"Trace steps: {int(_as_float(metrics.get('trace_step_count')))}",
    ]
    lines.extend(_scene_lines(raw))
    lines.extend(f"- {item}" for item in diagnosis)

    return {
        "processed_feedback": "\n".join(lines),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score")),
            "valid": 1.0 if result.get("is_valid") else 0.0,
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
            "mean_coverage_ratio": _as_float(metrics.get("mean_coverage_ratio")),
            "min_coverage_ratio": _as_float(metrics.get("min_coverage_ratio")),
            "total_energy": _as_float(metrics.get("total_energy")),
            "trace_step_count": _as_float(metrics.get("trace_step_count")),
        },
        "analysis": {
            "diagnosis": diagnosis,
            "scene_summaries": [
                {
                    "scene_id": scene.get("scene_id"),
                    "success": bool(scene.get("success")),
                    "reason": scene.get("reason"),
                    "coverage_ratio": scene.get("coverage_ratio", scene.get("coverage_ratio_at_failure")),
                    "energy": scene.get("energy", scene.get("energy_at_failure")),
                    "summary": scene.get("summary"),
                }
                for scene in ((raw or {}).get("scenes") or [])
            ],
        },
    }