"""PRO-mode analyzer: rich feedback from construction plus raw-artifact trajectory signals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_raw_artifact(output_dir: str | Path) -> dict[str, Any] | None:
    path = Path(output_dir) / "raw-artifact.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_scenario_scores(report: dict[str, Any]) -> dict[str, float]:
    return {
        item["scenario"]["name"]: float(item["score_breakdown"]["score"])
        for item in report["scenario_reports"]
    }


def build_scenario_breakdowns(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    breakdowns: dict[str, dict[str, Any]] = {}
    for item in report["scenario_reports"]:
        name = item["scenario"]["name"]
        score_breakdown = item["score_breakdown"]
        breakdowns[name] = {
            "score": float(score_breakdown["score"]),
            "carbon_gain": float(score_breakdown["carbon_gain"]),
            "water_gain": float(score_breakdown["water_gain"]),
            "safety_penalty": float(score_breakdown["safety_penalty"]),
            "candidate": dict(item["candidate"]),
            "noop_reference": dict(item["noop_reference"]),
        }
    return breakdowns


def build_diagnosis(report: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    scenario_reports = list(report["scenario_reports"])
    ranked = sorted(
        scenario_reports,
        key=lambda item: float(item["score_breakdown"]["score"]),
    )
    worst = ranked[:2]
    if worst:
        parts = [
            f"{item['scenario']['name']}={float(item['score_breakdown']['score']):.2f}"
            for item in worst
        ]
        diagnosis.append(f"Worst scenarios: {', '.join(parts)}")

    candidate = report["candidate_aggregate"]
    noop = report["noop_aggregate"]
    dropped = float(candidate.get("dropped_tasks", 0.0))
    overdue = float(candidate.get("overdue_tasks", 0.0))

    if dropped > 0:
        diagnosis.append(
            f"Dropped tasks={dropped:.0f}; load shifting may be too aggressive."
        )
    else:
        diagnosis.append("No dropped tasks observed; load shifting appears feasible.")

    if overdue > 0:
        diagnosis.append(
            f"Overdue tasks={overdue:.0f}; queue draining may be too late."
        )

    candidate_carbon = float(candidate.get("carbon_kg", 0.0))
    noop_carbon = float(noop.get("carbon_kg", 0.0))
    if candidate_carbon >= noop_carbon:
        diagnosis.append(
            "Candidate carbon is not below noop carbon; carbon policy is not improving over noop."
        )
    else:
        diagnosis.append("Candidate improves carbon relative to noop.")

    candidate_water = float(candidate.get("water_l", 0.0))
    noop_water = float(noop.get("water_l", 0.0))
    if candidate_water >= noop_water:
        diagnosis.append(
            "Candidate water usage is not below noop; cooling/water tradeoff is not improving over noop."
        )
    else:
        diagnosis.append("Candidate improves water usage relative to noop.")

    avg_soc = float(candidate.get("avg_soc", 0.0))
    if avg_soc > 0.85:
        diagnosis.append(
            "Average battery SOC is very high; battery dispatch may be too conservative."
        )
    elif avg_soc < 0.15:
        diagnosis.append(
            "Average battery SOC is very low; battery dispatch may be too aggressive."
        )

    return diagnosis


def build_rich_feedback(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "average_score": float(report["average_score"]),
        "scenario_scores": build_scenario_scores(report),
        "scenario_breakdowns": build_scenario_breakdowns(report),
        "candidate_aggregate": dict(report["candidate_aggregate"]),
        "noop_aggregate": dict(report["noop_aggregate"]),
        "diagnosis": build_diagnosis(report),
    }


def _iter_steps(raw: dict[str, Any]):
    for scenario in raw.get("scenarios") or []:
        for step in scenario.get("steps") or []:
            yield step


def _obs(step: dict[str, Any], agent: str) -> list[float]:
    return list((step.get("observations") or {}).get(agent) or [])


def _action(step: dict[str, Any], agent: str) -> int:
    return int((step.get("actions") or {}).get(agent, 1))


def _action_fraction(steps: list[dict[str, Any]], agent: str, action_id: int) -> float:
    if not steps:
        return 0.0
    hits = sum(1 for step in steps if _action(step, agent) == action_id)
    return hits / len(steps)


def extract_trajectory_metrics(raw: dict[str, Any] | None) -> dict[str, float]:
    if not raw:
        return {}

    steps = list(_iter_steps(raw))
    if not steps:
        return {}

    ls_defer = _action_fraction(steps, "ls", 0)
    ls_execute = _action_fraction(steps, "ls", 2)
    dc_more = _action_fraction(steps, "dc", 0)
    dc_less = _action_fraction(steps, "dc", 2)
    bat_charge = _action_fraction(steps, "bat", 0)
    bat_discharge = _action_fraction(steps, "bat", 2)

    high_ci_steps = [
        step
        for step in steps
        if len(_obs(step, "ls")) > 2 and _obs(step, "ls")[2] > 0.7
    ]
    discharge_under_high_ci = _action_fraction(high_ci_steps, "bat", 2)

    metrics = {
        "trajectory_step_count": float(len(steps)),
        "ls_defer_fraction": ls_defer,
        "ls_execute_fraction": ls_execute,
        "dc_more_cooling_fraction": dc_more,
        "dc_less_cooling_fraction": dc_less,
        "bat_charge_fraction": bat_charge,
        "bat_discharge_fraction": bat_discharge,
    }
    if high_ci_steps:
        metrics["bat_discharge_fraction_under_high_ci"] = discharge_under_high_ci
    return metrics


def _trajectory_diagnosis(metrics: dict[str, float]) -> list[str]:
    diagnosis: list[str] = []
    if not metrics:
        return diagnosis

    ls_defer = metrics.get("ls_defer_fraction", 0.0)
    ls_execute = metrics.get("ls_execute_fraction", 0.0)
    if ls_defer > 0.35 and ls_execute < 0.15:
        diagnosis.append(
            f"Load shifting defers often ({ls_defer:.0%}) but executes rarely "
            f"({ls_execute:.0%}); queue may not be draining."
        )

    dc_more = metrics.get("dc_more_cooling_fraction", 0.0)
    dc_less = metrics.get("dc_less_cooling_fraction", 0.0)
    if dc_more > 0.45:
        diagnosis.append(
            f"Cooling agent chooses MORE_COOL on {dc_more:.0%} of steps; "
            "check hot-scenario water/carbon tradeoffs."
        )
    if dc_less > 0.45:
        diagnosis.append(
            f"Cooling agent chooses LESS_COOL on {dc_less:.0%} of steps; "
            "cooling may be insufficient under high outdoor temp."
        )

    bat_discharge = metrics.get("bat_discharge_fraction", 0.0)
    discharge_hi_ci = metrics.get("bat_discharge_fraction_under_high_ci")
    if discharge_hi_ci is not None and discharge_hi_ci < 0.05 and bat_discharge < 0.05:
        diagnosis.append(
            "Battery rarely discharges, even under high carbon intensity; "
            "carbon-aware dispatch may be too conservative."
        )
    elif discharge_hi_ci is not None and discharge_hi_ci > 0.25:
        diagnosis.append(
            f"Battery discharges on {discharge_hi_ci:.0%} of high-CI steps; "
            "verify SOC stays within safe bounds."
        )

    return diagnosis


def format_processed_feedback(
    report: dict[str, Any],
    trajectory_metrics: dict[str, float],
) -> str:
    rich = build_rich_feedback(report)
    lines = [f"Score: {rich['average_score']:.4f}"]
    scenario_scores = rich.get("scenario_scores") or {}
    if scenario_scores:
        parts = [f"{name}={score:.2f}" for name, score in sorted(scenario_scores.items())]
        lines.append(f"Scenario scores: {', '.join(parts)}")
    for item in rich.get("diagnosis") or []:
        lines.append(f"- {item}")
    if trajectory_metrics:
        traj_parts = [
            f"{name}={value:.3f}" if name.endswith("_fraction") else f"{name}={value:.0f}"
            for name, value in sorted(trajectory_metrics.items())
            if name != "trajectory_step_count"
        ]
        if traj_parts:
            lines.append(f"Trajectory: {', '.join(traj_parts)}")
    for item in _trajectory_diagnosis(trajectory_metrics):
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
                "Invalid policy; fix runtime errors before tuning control logic. "
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
    trajectory_metrics = extract_trajectory_metrics(raw)
    rich = build_rich_feedback(report)
    diagnosis = build_diagnosis(report) + _trajectory_diagnosis(trajectory_metrics)

    return {
        "processed_feedback": format_processed_feedback(report, trajectory_metrics),
        "analysis_metrics": {
            "average_score": rich["average_score"],
            "scenario_scores": rich["scenario_scores"],
            "trajectory": trajectory_metrics,
        },
        "analysis": {
            "scenario_breakdowns": rich["scenario_breakdowns"],
            "diagnosis": diagnosis,
            "trajectory_metrics": trajectory_metrics,
            "raw_artifact_present": raw is not None,
        },
    }
