"""Processed-feedback analyzer for the general_meio agentic-evolve example."""

from __future__ import annotations

from typing import Any


def build_subscore_breakdown(report: dict[str, Any]) -> dict[str, float]:
    metrics = report.get("metrics") or {}
    return {
        "cost_score": float(metrics.get("cost_score", 0.0)),
        "service_score": float(metrics.get("service_score", 0.0)),
        "robustness_score": float(metrics.get("robustness_score", 0.0)),
        "balance_score": float(metrics.get("balance_score", 0.0)),
    }


def format_processed_feedback(report: dict[str, Any]) -> str:
    lines = [f"Score: {float(report.get('final_score', 0.0)):.4f}"]
    subscores = build_subscore_breakdown(report)
    if subscores:
        parts = [f"{name}={value:.3f}" for name, value in sorted(subscores.items())]
        lines.append(f"Subscores: {', '.join(parts)}")
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

    return {
        "processed_feedback": format_processed_feedback(report),
    }
