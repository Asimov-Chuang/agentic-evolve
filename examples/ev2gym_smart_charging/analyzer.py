"""Score-only analyzer for the EV2Gym smart charging example."""

from __future__ import annotations

from typing import Any


def format_processed_feedback(report: dict[str, Any]) -> str:
    score = float(report.get("score", 0.0))
    return f"Score: {score:.4f}"


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
                "Invalid policy; fix runtime errors before tuning charging logic. "
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
