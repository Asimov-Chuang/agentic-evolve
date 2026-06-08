"""Processed-feedback analyzer for the general_meio agentic-evolve example."""

from __future__ import annotations

from typing import Any

SINK_NODES = (40, 50)
DEMAND_MEAN = {40: 8.0, 50: 7.0}


def build_subscore_breakdown(report: dict[str, Any]) -> dict[str, float]:
    metrics = report.get("metrics") or {}
    return {
        "cost_score": float(metrics.get("cost_score", 0.0)),
        "service_score": float(metrics.get("service_score", 0.0)),
        "robustness_score": float(metrics.get("robustness_score", 0.0)),
        "balance_score": float(metrics.get("balance_score", 0.0)),
    }


def build_scenario_breakdowns(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    breakdowns: dict[str, dict[str, Any]] = {}
    for scenario_name in ("nominal", "stress"):
        block = report.get(scenario_name) or {}
        solution = dict(block.get("solution") or {})
        breakdowns[scenario_name] = {
            "cost_per_period": float(solution.get("cost_per_period", 0.0)),
            "fill_rate": float(solution.get("fill_rate", 0.0)),
            "fill_by_sink": dict(solution.get("fill_by_sink") or {}),
            "stockout_per_period": float(solution.get("stockout_per_period", 0.0)),
        }
    return breakdowns


def build_diagnosis(report: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    subscores = build_subscore_breakdown(report)
    ranked = sorted(subscores.items(), key=lambda item: item[1])
    if ranked:
        parts = [f"{name}={value:.3f}" for name, value in ranked[:2]]
        diagnosis.append(f"Weakest subscores: {', '.join(parts)}")

    solution = report.get("solution_base_stock") or {}
    for node in SINK_NODES:
        key = str(node)
        if key in solution and DEMAND_MEAN[node] > 0:
            ratio = float(solution[key]) / DEMAND_MEAN[node]
            diagnosis.append(f"Node {node} base-stock / mean demand ratio = {ratio:.2f}")

    nominal = (report.get("nominal") or {}).get("solution") or {}
    stress = (report.get("stress") or {}).get("solution") or {}
    nom_fill = dict(nominal.get("fill_by_sink") or {})
    stress_fill = dict(stress.get("fill_by_sink") or {})
    for node in SINK_NODES:
        key = str(node)
        if key in nom_fill and key in stress_fill:
            drop = float(nom_fill[key]) - float(stress_fill[key])
            if drop > 0.05:
                diagnosis.append(
                    f"Sink {node} fill-rate drops by {drop:.2f} under stress "
                    f"({float(nom_fill[key]):.2f} -> {float(stress_fill[key]):.2f})."
                )

    fill40 = float(nom_fill.get("40", 0.0))
    fill50 = float(nom_fill.get("50", 0.0))
    gap = abs(fill40 - fill50)
    if gap > 0.03:
        diagnosis.append(
            f"Sink balance gap |fill40-fill50| = {gap:.3f}; "
            "consider rebalancing base-stock at nodes 40 and 50."
        )
    elif subscores["balance_score"] >= 0.99:
        diagnosis.append("Sink fill-rates are well balanced in nominal scenario.")

    if subscores["service_score"] < 0.5:
        diagnosis.append(
            "Nominal service score is low; increase sink or upstream base-stock levels."
        )
    if subscores["robustness_score"] < 0.5:
        diagnosis.append(
            "Stress robustness is low; protect upstream nodes against demand_scale=1.2."
        )
    if subscores["cost_score"] < 0.5:
        diagnosis.append(
            "Nominal cost score is low; current base-stock levels may be too high."
        )

    return diagnosis


def build_rich_feedback(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_score": float(report.get("final_score", 0.0)),
        "subscores": build_subscore_breakdown(report),
        "solution_base_stock": dict(report.get("solution_base_stock") or {}),
        "scenario_breakdowns": build_scenario_breakdowns(report),
        "diagnosis": build_diagnosis(report),
    }


def format_processed_feedback(report: dict[str, Any]) -> str:
    rich = build_rich_feedback(report)
    lines = [f"Score: {rich['final_score']:.4f}"]
    subscores = rich.get("subscores") or {}
    if subscores:
        parts = [f"{name}={value:.3f}" for name, value in sorted(subscores.items())]
        lines.append(f"Subscores: {', '.join(parts)}")
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
                "Invalid solution; fix runtime errors before tuning base-stock logic. "
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
            "final_score": rich["final_score"],
            "subscores": rich["subscores"],
        },
        "analysis": {
            "scenario_breakdowns": rich["scenario_breakdowns"],
            "diagnosis": rich["diagnosis"],
        },
    }
