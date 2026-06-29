"""Rich-feedback analyzer for the EV2Gym smart charging example."""

from __future__ import annotations

from typing import Any

BASELINE_SCORE = 100.0
MIN_SERVICE_SATISFACTION = 1e-3


def build_case_scores(report: dict[str, Any]) -> dict[str, float]:
    return {
        str(case["case_id"]): float(case.get("score_vs_official_baseline", 0.0))
        for case in report.get("cases", [])
    }


def build_case_breakdowns(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    breakdowns: dict[str, dict[str, Any]] = {}
    for case in report.get("cases", []):
        case_id = str(case["case_id"])
        stats = dict(case.get("stats") or {})
        breakdowns[case_id] = {
            "score_vs_official_baseline": float(case.get("score_vs_official_baseline", 0.0)),
            "total_reward": float(stats.get("total_reward", 0.0)),
            "total_profits": float(stats.get("total_profits", 0.0)),
            "energy_user_satisfaction": float(stats.get("energy_user_satisfaction", 0.0)),
            "num_spawned_evs": int(case.get("num_spawned_evs", 0)),
            "simulation_length": int(case.get("simulation_length", 0)),
        }
    return breakdowns


def build_diagnosis(report: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    score = float(report.get("score", 0.0))
    mean_satisfaction = float(report.get("mean_energy_user_satisfaction", 0.0))
    diagnosis.append(
        f"Combined score={score:.2f} (baseline reference={BASELINE_SCORE:.0f}); "
        f"gap={BASELINE_SCORE - score:.2f}."
    )

    case_breakdowns = build_case_breakdowns(report)
    if case_breakdowns:
        ranked = sorted(
            case_breakdowns.items(),
            key=lambda item: float(item[1]["score_vs_official_baseline"]),
        )
        worst = ranked[:2]
        parts = [
            f"{case_id}={float(info['score_vs_official_baseline']):.2f}"
            for case_id, info in worst
        ]
        diagnosis.append(f"Worst cases: {', '.join(parts)}.")

    zero_service_cases = [
        case_id
        for case_id, info in case_breakdowns.items()
        if float(info.get("energy_user_satisfaction", 0.0)) <= MIN_SERVICE_SATISFACTION
    ]
    if zero_service_cases:
        diagnosis.append(
            f"Cases with near-zero service satisfaction score 0: {', '.join(zero_service_cases)}. "
            "Ensure EVs receive energy before departure."
        )
    elif mean_satisfaction >= 99.0:
        diagnosis.append(
            f"Mean energy_user_satisfaction={mean_satisfaction:.1f}; service delivery looks healthy."
        )

    if score < BASELINE_SCORE * 0.95:
        diagnosis.append(
            "Score is below 95% of the official ChargeAsFastAsPossible baseline; "
            "consider price-aware V2G arbitrage and departure-aware charging."
        )
    elif score >= BASELINE_SCORE:
        diagnosis.append("Candidate meets or exceeds the official baseline score.")

    return diagnosis


def build_rich_feedback(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": float(report.get("score", 0.0)),
        "mean_total_reward": float(report.get("mean_total_reward", 0.0)),
        "mean_total_profits": float(report.get("mean_total_profits", 0.0)),
        "mean_energy_user_satisfaction": float(report.get("mean_energy_user_satisfaction", 0.0)),
        "case_scores": build_case_scores(report),
        "case_breakdowns": build_case_breakdowns(report),
        "diagnosis": build_diagnosis(report),
    }


def format_processed_feedback(report: dict[str, Any]) -> str:
    rich = build_rich_feedback(report)
    lines = [f"Score: {rich['score']:.4f}"]
    case_parts = [
        f"{case_id}={score:.2f}"
        for case_id, score in sorted(rich.get("case_scores", {}).items())
    ]
    if case_parts:
        lines.append(f"Case scores: {', '.join(case_parts)}")
    lines.append(
        f"Mean satisfaction={rich['mean_energy_user_satisfaction']:.1f}, "
        f"mean profits={rich['mean_total_profits']:.2f}"
    )
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

    rich = build_rich_feedback(report)
    return {
        "processed_feedback": format_processed_feedback(report),
        "analysis_metrics": {
            "score": rich["score"],
            "mean_energy_user_satisfaction": rich["mean_energy_user_satisfaction"],
            "case_scores": rich["case_scores"],
        },
        "analysis": {
            "case_breakdowns": rich["case_breakdowns"],
            "diagnosis": rich["diagnosis"],
        },
    }
