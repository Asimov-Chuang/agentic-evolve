"""Rich-feedback analyzer for the adaptive temporal smooth control example."""

from __future__ import annotations

from typing import Any


def _baseline(report: dict[str, Any]) -> dict[str, Any]:
    return dict(report.get("baseline") or {})


def _reference(report: dict[str, Any]) -> dict[str, Any]:
    return dict(report.get("reference") or {})


def build_metric_breakdown(report: dict[str, Any]) -> dict[str, float]:
    baseline = _baseline(report)
    return {
        "score_0_to_1_higher_is_better": float(
            baseline.get("score_0_to_1_higher_is_better", 0.0)
        ),
        "mean_rms": float(baseline.get("mean_rms", 0.0)),
        "mean_slew": float(baseline.get("mean_slew", 0.0)),
        "mean_strehl": float(baseline.get("mean_strehl", 0.0)),
        "raw_cost_lower_is_better": float(baseline.get("raw_cost_lower_is_better", 0.0)),
    }


def build_utility_breakdown(report: dict[str, Any]) -> dict[str, float]:
    baseline = _baseline(report)
    utility = dict(baseline.get("utility_breakdown") or {})
    return {
        "u_mean_rms": float(utility.get("u_mean_rms", 0.0)),
        "u_mean_slew": float(utility.get("u_mean_slew", 0.0)),
        "u_strehl": float(utility.get("u_strehl", 0.0)),
    }


def build_reference_comparison(report: dict[str, Any]) -> dict[str, dict[str, float]]:
    baseline = _baseline(report)
    reference = _reference(report)
    keys = ("mean_rms", "mean_slew", "mean_strehl", "score_0_to_1_higher_is_better")
    return {
        "candidate": {key: float(baseline.get(key, 0.0)) for key in keys},
        "reference": {key: float(reference.get(key, 0.0)) for key in keys},
    }


def build_diagnosis(report: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    baseline = _baseline(report)
    reference = _reference(report)
    utility = build_utility_breakdown(report)
    comparison = build_reference_comparison(report)

    score = float(baseline.get("score_0_to_1_higher_is_better", 0.0))
    ref_score = float(reference.get("score_0_to_1_higher_is_better", 0.0))
    diagnosis.append(
        f"Candidate score={score:.3f} vs reference={ref_score:.3f} "
        f"(gap={ref_score - score:.3f})."
    )

    mean_slew = float(baseline.get("mean_slew", 0.0))
    ref_slew = float(reference.get("mean_slew", 0.0))
    if mean_slew > ref_slew * 1.25:
        diagnosis.append(
            f"mean_slew={mean_slew:.4f} is much higher than reference={ref_slew:.4f}; "
            "reduce command jitter and use prev_commands / smooth_reconstructor."
        )
    elif mean_slew <= ref_slew * 1.05:
        diagnosis.append("Command slew is close to reference; temporal smoothing looks reasonable.")

    mean_rms = float(baseline.get("mean_rms", 0.0))
    ref_rms = float(reference.get("mean_rms", 0.0))
    if mean_rms > ref_rms * 1.15:
        diagnosis.append(
            f"mean_rms={mean_rms:.4f} exceeds reference={ref_rms:.4f}; "
            "accuracy may be sacrificed or delayed-slope compensation is weak."
        )

    mean_strehl = float(baseline.get("mean_strehl", 0.0))
    ref_strehl = float(reference.get("mean_strehl", 0.0))
    if mean_strehl < ref_strehl * 0.85:
        diagnosis.append(
            f"mean_strehl={mean_strehl:.4f} lags reference={ref_strehl:.4f}; "
            "residual wavefront correction is weak."
        )

    ranked = sorted(utility.items(), key=lambda item: item[1])
    if ranked:
        weakest = ranked[:2]
        parts = [f"{name}={value:.3f}" for name, value in weakest]
        diagnosis.append(f"Weakest utility terms: {', '.join(parts)} (slew weight is 65%).")

    if comparison["candidate"]["score_0_to_1_higher_is_better"] >= comparison["reference"]["score_0_to_1_higher_is_better"]:
        diagnosis.append("Candidate meets or beats the analytical reference controller.")

    return diagnosis


def build_rich_feedback(report: dict[str, Any]) -> dict[str, Any]:
    baseline = _baseline(report)
    return {
        "score_0_to_1_higher_is_better": float(
            baseline.get("score_0_to_1_higher_is_better", 0.0)
        ),
        "metrics": build_metric_breakdown(report),
        "utility_breakdown": build_utility_breakdown(report),
        "reference_comparison": build_reference_comparison(report),
        "diagnosis": build_diagnosis(report),
    }


def format_processed_feedback(report: dict[str, Any]) -> str:
    rich = build_rich_feedback(report)
    lines = [f"Score: {rich['score_0_to_1_higher_is_better']:.4f}"]
    metrics = rich.get("metrics") or {}
    metric_parts = [
        f"{name}={value:.4f}"
        for name, value in (
            ("mean_rms", metrics.get("mean_rms", 0.0)),
            ("mean_slew", metrics.get("mean_slew", 0.0)),
            ("mean_strehl", metrics.get("mean_strehl", 0.0)),
        )
    ]
    lines.append(f"Metrics: {', '.join(metric_parts)}")
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
                "Invalid controller; fix runtime errors before tuning control logic. "
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
            "score_0_to_1_higher_is_better": rich["score_0_to_1_higher_is_better"],
            "metrics": rich["metrics"],
        },
        "analysis": {
            "reference_comparison": rich["reference_comparison"],
            "diagnosis": rich["diagnosis"],
        },
    }
