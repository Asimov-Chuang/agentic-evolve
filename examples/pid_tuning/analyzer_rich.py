"""Rich-feedback analyzer for the PIDTuning agentic-evolve example."""

from __future__ import annotations

from typing import Any


def _scenario_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["name"]): dict(item) for item in report.get("scenarios") or []}


def build_scenario_scores(report: dict[str, Any]) -> dict[str, float]:
    return {
        name: float(info.get("inv_itae", 0.0))
        for name, info in _scenario_map(report).items()
    }


def build_scenario_breakdowns(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    breakdowns: dict[str, dict[str, Any]] = {}
    for name, info in _scenario_map(report).items():
        breakdowns[name] = {
            "itae": float(info.get("itae", 0.0)),
            "inv_itae": float(info.get("inv_itae", 0.0)),
            "feasible": bool(info.get("feasible", False)),
            "duration": float(info.get("duration", 0.0)),
            "wind": list(info.get("wind") or [0.0, 0.0]),
        }
    return breakdowns


def build_diagnosis(report: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    score = float(report.get("combined_score", 0.0))
    feasible = bool(report.get("feasible", score > 0.0))

    if not feasible:
        diagnosis.append("Submission is infeasible (score=0.0).")
        failed = [
            name
            for name, info in _scenario_map(report).items()
            if not bool(info.get("feasible", False))
        ]
        if failed:
            diagnosis.append(f"Infeasible scenarios (pitch limit or bad ITAE): {', '.join(failed)}.")
        return diagnosis

    diagnosis.append(f"Feasible submission with combined_score={score:.6f}.")

    scenario_scores = build_scenario_scores(report)
    if scenario_scores:
        ranked = sorted(scenario_scores.items(), key=lambda item: item[1])
        worst = ranked[:2]
        parts = [f"{name} inv_itae={value:.4f}" for name, value in worst]
        diagnosis.append(f"Weakest scenarios: {', '.join(parts)}.")

        values = [value for value in scenario_scores.values() if value > 0.0]
        if len(values) >= 2:
            spread = max(values) / max(min(values), 1e-12)
            if spread > 3.0:
                diagnosis.append(
                    f"Large scenario spread (max/min inv_itae ratio={spread:.2f}); "
                    "some scenarios are much harder than others for the current gains."
                )

    gains = dict(report.get("gains") or {})
    if float(gains.get("Kp_x", 0.0)) < 0.3:
        diagnosis.append("Horizontal Kp_x is low; lateral and multi-waypoint tracking may be weak.")
    if float(gains.get("Ki_z", 0.0)) > 5.0:
        diagnosis.append("Altitude Ki_z is high; watch for windup under combined_wind.")

    wind_score = scenario_scores.get("combined_wind", 0.0)
    hover_score = scenario_scores.get("vertical_hover", 0.0)
    if hover_score > 0.0 and wind_score < 0.5 * hover_score:
        diagnosis.append(
            "combined_wind inv_itae is much lower than vertical_hover; "
            "gains may not be robust to wind disturbance."
        )

    return diagnosis


def build_rich_feedback(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "combined_score": float(report.get("combined_score", 0.0)),
        "feasible": bool(report.get("feasible", False)),
        "gains": dict(report.get("gains") or {}),
        "scenario_scores": build_scenario_scores(report),
        "scenario_breakdowns": build_scenario_breakdowns(report),
        "diagnosis": build_diagnosis(report),
    }


def format_processed_feedback(report: dict[str, Any]) -> str:
    rich = build_rich_feedback(report)
    lines = [f"Score: {rich['combined_score']:.6f} (feasible={int(rich['feasible'])})"]
    scenario_parts = [
        f"{name}={score:.4f}"
        for name, score in sorted(rich.get("scenario_scores", {}).items())
    ]
    if scenario_parts:
        lines.append(f"Scenario inv_itae: {', '.join(scenario_parts)}")
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

    rich = build_rich_feedback(report)
    return {
        "processed_feedback": format_processed_feedback(report),
        "analysis_metrics": {
            "combined_score": rich["combined_score"],
            "scenario_scores": rich["scenario_scores"],
        },
        "analysis": {
            "scenario_breakdowns": rich["scenario_breakdowns"],
            "diagnosis": rich["diagnosis"],
        },
    }
