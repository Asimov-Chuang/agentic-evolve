"""Processed-feedback analyzer for the PIDTuning agentic-evolve example."""

from __future__ import annotations

from typing import Any


def _scenario_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["name"]): dict(item) for item in report.get("scenarios") or []}


def build_scenario_scores(report: dict[str, Any]) -> dict[str, float]:
    return {
        name: float(info.get("inv_itae", 0.0))
        for name, info in _scenario_map(report).items()
    }


def build_diagnosis(report: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    score = float(report.get("combined_score", 0.0))
    feasible = bool(report.get("feasible", score > 0.0))

    if not feasible:
        diagnosis.append("Submission is infeasible (score=0.0).")
        return diagnosis

    diagnosis.append(f"Feasible submission with combined_score={score:.6f}.")
    scenario_scores = build_scenario_scores(report)
    if scenario_scores:
        ranked = sorted(scenario_scores.items(), key=lambda item: item[1])
        worst = ranked[:2]
        parts = [f"{name} inv_itae={value:.4f}" for name, value in worst]
        diagnosis.append(f"Weakest scenarios: {', '.join(parts)}.")
    return diagnosis


def format_processed_feedback(report: dict[str, Any]) -> str:
    score = float(report.get("combined_score", 0.0))
    feasible = bool(report.get("feasible", score > 0.0))
    lines = [f"Score: {score:.6f} (feasible={int(feasible)})"]
    scenario_parts = [
        f"{name}={value:.4f}"
        for name, value in sorted(build_scenario_scores(report).items())
    ]
    if scenario_parts:
        lines.append(f"Scenario inv_itae: {', '.join(scenario_parts)}")
    for item in build_diagnosis(report):
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

    return {
        "processed_feedback": format_processed_feedback(report),
    }
