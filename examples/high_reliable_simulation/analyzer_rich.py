"""Rich-feedback analyzer for the HighReliableSimulation example."""

from __future__ import annotations

from typing import Any


def _aggregate(report: dict[str, Any]) -> dict[str, Any]:
    return dict(report.get("aggregate") or {})


def _dev_constants(report: dict[str, Any]) -> dict[str, Any]:
    return dict(report.get("dev_constants") or {})


def build_metric_breakdown(report: dict[str, Any]) -> dict[str, float]:
    aggregate = _aggregate(report)
    return {
        "combined_score": float(report.get("combined_score", aggregate.get("combined_score", -1e18))),
        "valid": float(report.get("valid", aggregate.get("valid", 0.0))),
        "runtime_s": float(aggregate.get("runtime_s", 0.0)),
        "error_log_ratio": float(aggregate.get("error_log_ratio", float("inf"))),
        "err_rate_log_median": float(aggregate.get("err_rate_log_median", 0.0)),
        "actual_std_median": float(aggregate.get("actual_std_median", 0.0)),
        "target_std_attainment_rate": float(aggregate.get("target_std_attainment_rate", 0.0)),
        "converged_rate": float(aggregate.get("converged_rate", 0.0)),
    }


def build_repeat_breakdown(report: dict[str, Any]) -> list[dict[str, float]]:
    repeats: list[dict[str, float]] = []
    for block in report.get("repeats") or []:
        repeats.append(
            {
                "repeat": float(block.get("repeat", 0.0)),
                "runtime_s": float(block.get("runtime_s", 0.0)),
                "err_rate_log": float(block.get("err_rate_log", 0.0)),
                "actual_std": float(block.get("actual_std", 0.0)),
                "converged": float(block.get("converged", 0.0)),
            }
        )
    return repeats


def build_diagnosis(report: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    metrics = build_metric_breakdown(report)
    dev = _dev_constants(report)
    target_std = float(dev.get("target_std", 0.05))
    epsilon = float(dev.get("epsilon", 0.8))

    if metrics["valid"] <= 0.0:
        diagnosis.append("Submission is invalid under frozen scoring rules.")
        if metrics["error_log_ratio"] >= epsilon:
            diagnosis.append(
                f"error_log_ratio={metrics['error_log_ratio']:.4f} >= epsilon={epsilon:.4f}; "
                "BER log estimate is too far from reference r0."
            )
        if metrics["actual_std_median"] > target_std:
            diagnosis.append(
                f"actual_std_median={metrics['actual_std_median']:.4f} > target_std={target_std:.4f}; "
                "variance control failed."
            )
    else:
        diagnosis.append(
            f"Valid submission with combined_score={metrics['combined_score']:.6g} "
            f"and runtime_s={metrics['runtime_s']:.3f}."
        )

    if metrics["target_std_attainment_rate"] < 1.0:
        diagnosis.append(
            f"Only {metrics['target_std_attainment_rate']:.0%} of repeats met target_std={target_std:.3f}."
        )

    if metrics["converged_rate"] < 1.0:
        diagnosis.append(
            f"converged_rate={metrics['converged_rate']:.2f}; some repeats did not converge within max_samples."
        )

    slow_repeats = [
        block for block in build_repeat_breakdown(report) if block["runtime_s"] > metrics["runtime_s"] * 1.5
    ]
    if slow_repeats:
        diagnosis.append(
            f"{len(slow_repeats)} repeat(s) are much slower than the median runtime; "
            "check sampler caching and batch design."
        )

    return diagnosis


def build_rich_feedback(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "combined_score": build_metric_breakdown(report)["combined_score"],
        "metrics": build_metric_breakdown(report),
        "repeat_breakdowns": build_repeat_breakdown(report),
        "diagnosis": build_diagnosis(report),
    }


def format_processed_feedback(report: dict[str, Any]) -> str:
    rich = build_rich_feedback(report)
    metrics = rich["metrics"]
    lines = [
        f"Score: {metrics['combined_score']:.6g} (valid={int(metrics['valid'])})",
        (
            "Metrics: "
            f"runtime_s={metrics['runtime_s']:.3f}, "
            f"error_log_ratio={metrics['error_log_ratio']:.4f}, "
            f"actual_std_median={metrics['actual_std_median']:.4f}"
        ),
    ]
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

    rich = build_rich_feedback(report)
    return {
        "processed_feedback": format_processed_feedback(report),
        "analysis_metrics": rich["metrics"],
        "analysis": {
            "repeat_breakdowns": rich["repeat_breakdowns"],
            "diagnosis": rich["diagnosis"],
        },
    }
