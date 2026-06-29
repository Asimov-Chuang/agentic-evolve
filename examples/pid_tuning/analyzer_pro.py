"""PRO-mode analyzer: rich feedback from construction plus raw-artifact gain/bound signals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analyzer_rich import (
    build_diagnosis,
    build_rich_feedback,
    build_scenario_scores,
)

_KEY_TO_GROUP: dict[str, tuple[str, str]] = {
    "Kp_z": ("altitude", "Kp"),
    "Ki_z": ("altitude", "Ki"),
    "Kd_z": ("altitude", "Kd"),
    "N_z": ("altitude", "N"),
    "Kp_x": ("horizontal", "Kp"),
    "Ki_x": ("horizontal", "Ki"),
    "Kd_x": ("horizontal", "Kd"),
    "N_x": ("horizontal", "N"),
    "Kp_theta": ("pitch", "Kp"),
    "Ki_theta": ("pitch", "Ki"),
    "Kd_theta": ("pitch", "Kd"),
    "N_theta": ("pitch", "N"),
}


def load_raw_artifact(output_dir: str | Path) -> dict[str, Any] | None:
    path = Path(output_dir) / "raw-artifact.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_gain_utilization(raw: dict[str, Any] | None) -> dict[str, float]:
    """Fraction of each gain's allowed range [0, 1] from raw-artifact gains + gain_bounds."""
    if not raw:
        return {}

    gains = dict(raw.get("gains") or {})
    bounds = dict(raw.get("gain_bounds") or {})
    if not gains or not bounds:
        return {}

    utilization: dict[str, float] = {}
    for key, value in gains.items():
        mapping = _KEY_TO_GROUP.get(key)
        if mapping is None:
            continue
        group, param = mapping
        range_pair = bounds.get(group, {}).get(param)
        if not range_pair or len(range_pair) < 2:
            continue
        lo, hi = float(range_pair[0]), float(range_pair[1])
        span = hi - lo
        if span <= 0:
            continue
        utilization[f"gain_frac_{key}"] = float((float(value) - lo) / span)
    return utilization


def extract_scenario_itae_metrics(raw: dict[str, Any] | None) -> dict[str, float]:
    if not raw:
        return {}

    scenarios = list(raw.get("scenarios") or [])
    metrics: dict[str, float] = {}
    itaes: dict[str, float] = {}
    for item in scenarios:
        name = str(item.get("name", "unknown"))
        itae = float(item.get("itae", 0.0))
        metrics[f"itae_{name}"] = itae
        metrics[f"feasible_{name}"] = 1.0 if bool(item.get("feasible", False)) else 0.0
        if itae > 0.0:
            itaes[name] = itae

    if len(itaes) >= 2:
        values = list(itaes.values())
        metrics["itae_max_over_min"] = float(max(values) / max(min(values), 1e-12))
        worst = max(itaes.items(), key=lambda pair: pair[1])
        metrics["itae_worst_scenario_value"] = float(worst[1])
    return metrics


def _raw_diagnosis(
    raw: dict[str, Any] | None,
    gain_util: dict[str, float],
    scenario_metrics: dict[str, float],
) -> list[str]:
    if not raw:
        return []

    diagnosis: list[str] = []
    pinned_low = [key.removeprefix("gain_frac_") for key, frac in gain_util.items() if frac <= 0.05]
    pinned_high = [key.removeprefix("gain_frac_") for key, frac in gain_util.items() if frac >= 0.95]
    if pinned_low:
        diagnosis.append(
            f"Gains near lower bound: {', '.join(pinned_low)}; "
            "may have room to increase authority."
        )
    if pinned_high:
        diagnosis.append(
            f"Gains near upper bound: {', '.join(pinned_high)}; "
            "saturated tuning — try rebalancing other loops."
        )

    itae_spread = scenario_metrics.get("itae_max_over_min")
    if itae_spread is not None and itae_spread > 5.0:
        diagnosis.append(
            f"ITAE spread across scenarios is high (max/min={itae_spread:.2f}); "
            "one scenario dominates failure risk."
        )

    constraints = dict(raw.get("constraints") or {})
    if constraints:
        diagnosis.append(
            "Simulation constraints from raw-artifact: "
            f"max_pitch_rad={constraints.get('max_pitch_rad')}, "
            f"max_thrust_factor={constraints.get('max_thrust_factor')}."
        )

    return diagnosis


def format_processed_feedback(
    report: dict[str, Any],
    gain_util: dict[str, float],
    scenario_metrics: dict[str, float],
    extra_diagnosis: list[str],
) -> str:
    rich = build_rich_feedback(report)
    lines = [f"Score: {rich['combined_score']:.6f} (feasible={int(rich['feasible'])})"]
    scenario_parts = [
        f"{name}={score:.4f}"
        for name, score in sorted(rich.get("scenario_scores", {}).items())
    ]
    if scenario_parts:
        lines.append(f"Scenario inv_itae: {', '.join(scenario_parts)}")
    if gain_util:
        util_parts = [
            f"{name.removeprefix('gain_frac_')}={value:.2f}"
            for name, value in sorted(gain_util.items())
        ]
        lines.append(f"Gain range utilization: {', '.join(util_parts)}")
    if scenario_metrics:
        itae_parts = [
            f"{name}={value:.4f}"
            for name, value in sorted(scenario_metrics.items())
            if name.startswith("itae_") and not name.endswith("_value")
        ]
        if itae_parts:
            lines.append(f"Raw ITAE: {', '.join(itae_parts)}")
    for item in rich.get("diagnosis") or []:
        lines.append(f"- {item}")
    for item in extra_diagnosis:
        lines.append(f"- {item}")
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
                "Invalid optimizer; fix runtime errors before tuning PID search. "
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
    gain_util = extract_gain_utilization(raw)
    scenario_metrics = extract_scenario_itae_metrics(raw)
    extra_diagnosis = _raw_diagnosis(raw, gain_util, scenario_metrics)
    rich = build_rich_feedback(report)
    diagnosis = build_diagnosis(report) + extra_diagnosis

    return {
        "processed_feedback": format_processed_feedback(
            report, gain_util, scenario_metrics, extra_diagnosis
        ),
        "analysis_metrics": {
            "combined_score": rich["combined_score"],
            "scenario_scores": rich["scenario_scores"],
            "gain_utilization": gain_util,
            "scenario_itae": scenario_metrics,
        },
        "analysis": {
            "scenario_breakdowns": rich["scenario_breakdowns"],
            "gains": rich.get("gains") or dict(report.get("gains") or {}),
            "diagnosis": diagnosis,
            "gain_utilization": gain_util,
            "scenario_itae_metrics": scenario_metrics,
            "raw_artifact_present": raw is not None,
        },
    }
