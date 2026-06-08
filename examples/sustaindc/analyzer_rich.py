"""Processed-feedback analyzer for the SustainDC agentic-evolve example."""

from __future__ import annotations

from typing import Any


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


def format_processed_feedback(report: dict[str, Any]) -> str:
    rich = build_rich_feedback(report)
    lines = [f"Score: {rich['average_score']:.4f}"]
    scenario_scores = rich.get("scenario_scores") or {}
    if scenario_scores:
        parts = [f"{name}={score:.2f}" for name, score in sorted(scenario_scores.items())]
        lines.append(f"Scenario scores: {', '.join(parts)}")
    for item in rich.get("diagnosis") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)


def analyze(
    program_path: str,
    output_dir: str,
    result: dict,
    archive_dir: str,
    workspace_dir: str,
) -> dict:
    del program_path, output_dir, archive_dir, workspace_dir

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

    rich = build_rich_feedback(report)
    return {
        "processed_feedback": format_processed_feedback(report),
        "analysis_metrics": {
            "average_score": rich["average_score"],
            "scenario_scores": rich["scenario_scores"],
        },
        "analysis": {
            "scenario_breakdowns": rich["scenario_breakdowns"],
            "diagnosis": rich["diagnosis"],
        },
    }
