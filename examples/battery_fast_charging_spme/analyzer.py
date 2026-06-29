"""Fixed feedback analyzer for BatteryFastChargingSPMe."""

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


def _policy_from(metrics: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw and isinstance(raw.get("policy"), dict):
        return dict(raw["policy"])
    return {
        "currents_c": metrics.get("currents_c", []),
        "switch_soc": metrics.get("switch_soc", []),
    }


def _diagnosis(metrics: dict[str, Any], raw: dict[str, Any] | None) -> list[str]:
    diagnosis: list[str] = []
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    failure_reason = str(metrics.get("failure_reason") or "")

    if valid:
        diagnosis.append("Policy is feasible under hard voltage, temperature, plating, and horizon constraints.")
    elif "voltage_cutoff" in failure_reason:
        diagnosis.append("Hard voltage cutoff was hit; reduce early or high-SOC currents, or add a lower-current late stage.")
    elif "plating_margin_cutoff" in failure_reason:
        diagnosis.append("Hard plating margin cutoff was hit; lower current where plating margin first collapses.")
    elif "thermal_cutoff" in failure_reason:
        diagnosis.append("Hard thermal cutoff was hit; reduce sustained high-current dwell time.")
    elif "timeout" in failure_reason:
        diagnosis.append("Policy did not reach target SOC; raise one or more currents while staying within safety limits.")
    elif failure_reason:
        diagnosis.append(f"Evaluator failure: {failure_reason}")
    else:
        diagnosis.append("Policy is invalid; inspect metric fields and raw artifacts.")

    if _as_float(metrics.get("soft_voltage_violation"), 0.0) > 0.0:
        diagnosis.append("Soft voltage limit was exceeded; voltage score may be the active tradeoff.")
    if _as_float(metrics.get("soft_temp_violation"), 0.0) > 0.0:
        diagnosis.append("Soft temperature limit was exceeded; thermal score may be the active tradeoff.")
    if _as_float(metrics.get("soft_plating_violation"), 0.0) > 0.0:
        diagnosis.append("Soft plating margin was violated; plating and aging scores may be constrained.")

    policy = _policy_from(metrics, raw)
    currents = [_as_float(item) for item in policy.get("currents_c", [])]
    switches = [_as_float(item) for item in policy.get("switch_soc", [])]
    if currents and switches:
        for idx, current in enumerate(currents):
            low_soc = 0.10 if idx == 0 else switches[idx - 1]
            high_soc = 0.90 if idx >= len(switches) else switches[idx]
            if low_soc >= 0.70 and current > 2.5:
                diagnosis.append(
                    f"Stage {idx} uses {current:.2f}C above SOC {low_soc:.2f}; late high-current charging often drives voltage/plating stress."
                )
            if high_soc - low_soc < 0.03:
                diagnosis.append(f"Stage {idx} has a very narrow SOC band; simplify unless it targets a known constraint crossing.")

    derived = (raw or {}).get("derived") if raw else None
    if isinstance(derived, dict):
        crossings = derived.get("first_limit_crossings")
        if isinstance(crossings, dict) and crossings:
            first = sorted(crossings.items(), key=lambda item: _as_float(item[1].get("time_s")))[0]
            diagnosis.append(
                f"First recorded constraint crossing: {first[0]} at SOC {_as_float(first[1].get('soc')):.3f}."
            )

    return diagnosis


def _format_feedback(metrics: dict[str, Any], raw: dict[str, Any] | None) -> str:
    score = _as_float(metrics.get("combined_score"), _as_float(metrics.get("score"), 0.0))
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    policy = _policy_from(metrics, raw)
    lines = [
        f"Score: {score:.4f}",
        f"Valid: {valid}",
        f"Failure reason: {metrics.get('failure_reason', '') or 'none'}",
        f"Charge time seconds: {_as_float(metrics.get('charge_time_s')):.1f}",
        f"Max voltage V: {_as_float(metrics.get('max_voltage_v')):.4f}",
        f"Max temp C: {_as_float(metrics.get('max_temp_c')):.3f}",
        f"Min plating margin V: {_as_float(metrics.get('min_plating_margin_v')):.5f}",
        f"Plating loss Ah: {_as_float(metrics.get('plating_loss_ah')):.8g}",
        f"Aging loss Ah: {_as_float(metrics.get('aging_loss_ah')):.8g}",
        f"Currents C: {policy.get('currents_c', [])}",
        f"Switch SOC: {policy.get('switch_soc', [])}",
        f"Raw artifact present: {raw is not None}",
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

    raw = _load_raw_artifact(output_dir)
    metrics = _metrics_from(result, raw)
    diagnosis = _diagnosis(metrics, raw)
    return {
        "processed_feedback": _format_feedback(metrics, raw),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score"), 0.0),
            "valid": 1.0 if _as_float(metrics.get("valid"), 0.0) > 0.0 else 0.0,
            "charge_time_s": _as_float(metrics.get("charge_time_s"), 0.0),
            "max_voltage_v": _as_float(metrics.get("max_voltage_v"), 0.0),
            "max_temp_c": _as_float(metrics.get("max_temp_c"), 0.0),
            "min_plating_margin_v": _as_float(metrics.get("min_plating_margin_v"), 0.0),
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
        },
        "analysis": {
            "diagnosis": diagnosis,
            "raw_artifact_present": raw is not None,
        },
    }
