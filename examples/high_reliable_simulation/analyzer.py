"""Score-only analyzer for the HighReliableSimulation example."""

from __future__ import annotations

from typing import Any


def format_processed_feedback(report: dict[str, Any]) -> str:
    aggregate = report.get("aggregate") or {}
    score = float(report.get("combined_score", aggregate.get("combined_score", -1e18)))
    valid = float(report.get("valid", aggregate.get("valid", 0.0)))
    return f"Score: {score:.6g} (valid={int(valid)})"


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
                "Invalid sampler; fix runtime/interface errors before tuning logic. "
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
