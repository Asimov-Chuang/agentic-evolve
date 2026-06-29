"""Private SustainDC ablation evaluator and feedback builders."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_PROGRAM_TIMEOUT_SECONDS = 300
SCENARIO_ORDER = ("az_july", "ca_april", "ny_january", "tx_august")


def _default_frontier_root() -> Path:
    env_root = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    evaluate_rel = (
        Path("benchmarks")
        / "SustainableDataCenterControl"
        / "hand_written_control"
        / "verification"
        / "evaluate.py"
    )
    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering"):
            if (candidate / evaluate_rel).is_file():
                return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _resolve_paths() -> tuple[Path, Path, Path, Path]:
    frontier_root = _default_frontier_root()
    benchmark_dir = (
        frontier_root / "benchmarks" / "SustainableDataCenterControl" / "hand_written_control"
    )
    evaluate_py = benchmark_dir / "verification" / "evaluate.py"
    sustaindc_root = Path(
        os.environ.get("SUSTAINDC_ROOT", str(benchmark_dir / "sustaindc"))
    ).expanduser().resolve()
    env_python = os.environ.get("SUSTAINDC_PYTHON", "").strip()
    if env_python:
        python_bin = Path(env_python).expanduser()
    else:
        linux_bin = frontier_root / ".venvs" / "frontier-v1-sustaindc" / "bin" / "python"
        windows_bin = (
            frontier_root
            / ".venvs"
            / "frontier-v1-sustaindc"
            / "Scripts"
            / "python.exe"
        )
        python_bin = windows_bin if windows_bin.exists() else linux_bin
    return frontier_root, evaluate_py, sustaindc_root, python_bin


def _program_timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))
    return DEFAULT_PROGRAM_TIMEOUT_SECONDS


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Expected JSON file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _failure_result(message: str, *, metrics: dict[str, Any] | None = None) -> dict:
    return {
        "score": 0.0,
        "is_valid": False,
        "feedback": message,
        "metrics": metrics or {},
    }


def evaluate(program_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    program_path_p = Path(program_path).expanduser().resolve()
    output_dir_p = Path(output_dir).resolve()

    if not program_path_p.is_file():
        return _failure_result(f"Candidate program not found: {program_path_p}")

    try:
        _, evaluate_py, sustaindc_root, python_bin = _resolve_paths()
    except FileNotFoundError as exc:
        return _failure_result(str(exc))

    if not evaluate_py.is_file():
        return _failure_result(
            f"Frontier evaluator not found: {evaluate_py}. "
            "Set FRONTIER_ENGINEERING_ROOT to your Frontier-Engineering checkout."
        )
    if not python_bin.exists():
        return _failure_result(
            f"SustainDC python not found: {python_bin}. "
            "Run Frontier-Engineering setup_v1_task_envs.sh or set SUSTAINDC_PYTHON."
        )
    if not (sustaindc_root / "sustaindc_env.py").is_file():
        return _failure_result(
            f"SustainDC root missing sustaindc_env.py: {sustaindc_root}. "
            "Run fetch_task_assets.py --target sustaindc in Frontier-Engineering."
        )

    last_eval_path = output_dir_p / "last_eval.json"
    metrics_path = output_dir_p / "metrics.json"
    artifacts_path = output_dir_p / "artifacts.json"
    raw_artifacts_path = output_dir_p / "raw-artifact.json"

    cmd = [
        str(python_bin),
        str(evaluate_py),
        "--solution",
        str(program_path_p),
        "--sustaindc-root",
        str(sustaindc_root),
        "--save-json",
        str(last_eval_path),
        "--metrics-out",
        str(metrics_path),
        "--artifacts-out",
        str(artifacts_path),
        "--raw-artifacts-out",
        str(raw_artifacts_path),
    ]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_program_timeout_seconds(),
            cwd=str(evaluate_py.parent.parent),
        )
    except subprocess.TimeoutExpired:
        return _failure_result(f"Evaluation timed out after {_program_timeout_seconds()} seconds.")
    except Exception as exc:
        return _failure_result(f"Failed to run evaluation: {exc}")

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"return code {completed.returncode}"
        return _failure_result(f"Evaluation failed: {detail[-2000:]}")

    try:
        report = _load_json(last_eval_path)
        metrics_payload = _load_json(metrics_path)
    except Exception as exc:
        return _failure_result(f"Evaluation output missing or invalid: {exc}")

    score = float(report.get("average_score", metrics_payload.get("average_score", 0.0)))
    return {
        "score": score,
        "is_valid": True,
        "feedback": f"Score: {score:.4f}",
        "metrics": {"average_score": score},
    }


def _report_from_output(output_dir: str | Path) -> dict[str, Any]:
    return _load_json(Path(output_dir) / "last_eval.json")


def _raw_from_output(output_dir: str | Path) -> dict[str, Any] | None:
    path = Path(output_dir) / "raw-artifact.json"
    if not path.is_file():
        return None
    return _load_json(path)


def build_scenario_scores(report: dict[str, Any]) -> dict[str, float]:
    return {
        item["scenario"]["name"]: float(item["score_breakdown"]["score"])
        for item in report.get("scenario_reports", [])
    }


def build_scenario_breakdowns(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    breakdowns: dict[str, dict[str, Any]] = {}
    for item in report.get("scenario_reports", []):
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


def _coarse_diagnosis(report: dict[str, Any], limit: int = 2) -> list[str]:
    diagnosis: list[str] = []
    candidate = report.get("candidate_aggregate", {})
    noop = report.get("noop_aggregate", {})

    dropped = float(candidate.get("dropped_tasks", 0.0))
    overdue = float(candidate.get("overdue_tasks", 0.0))
    if dropped > 0:
        diagnosis.append(f"Dropped tasks={dropped:.0f}; load shifting may be too aggressive.")
    elif overdue > 0:
        diagnosis.append(f"Overdue tasks={overdue:.0f}; queue draining may be too late.")

    candidate_carbon = float(candidate.get("carbon_kg", 0.0))
    noop_carbon = float(noop.get("carbon_kg", 0.0))
    if noop_carbon > 0 and candidate_carbon >= noop_carbon:
        diagnosis.append("Candidate carbon is not below noop carbon.")

    candidate_water = float(candidate.get("water_l", 0.0))
    noop_water = float(noop.get("water_l", 0.0))
    if noop_water > 0 and candidate_water >= noop_water:
        diagnosis.append("Candidate water usage is not below noop.")

    if not diagnosis:
        diagnosis.append("No dropped tasks observed; limited aggregate feedback looks feasible.")
    return diagnosis[:limit]


def _iter_steps(raw: dict[str, Any]):
    for scenario in raw.get("scenarios") or []:
        for step in scenario.get("steps") or []:
            yield step


def _iter_scenarios(raw: dict[str, Any]):
    for scenario in raw.get("scenarios") or []:
        name = "unknown"
        sc_meta = scenario.get("scenario") or {}
        if isinstance(sc_meta, dict):
            name = str(sc_meta.get("name", "unknown"))
        yield name, list(scenario.get("steps") or [])


def _agent_key(agent: str) -> str:
    return f"agent_{agent}"


def _obs(step: dict[str, Any], agent: str) -> list[float]:
    return list((step.get("observations") or {}).get(_agent_key(agent)) or [])


def _action(step: dict[str, Any], agent: str) -> int:
    return int((step.get("actions") or {}).get(_agent_key(agent), 1))


def _action_fraction(steps: list[dict[str, Any]], agent: str, action_id: int) -> float:
    if not steps:
        return 0.0
    return sum(1 for step in steps if _action(step, agent) == action_id) / len(steps)


def _binned_fraction(
    steps: list[dict[str, Any]],
    agent_action: str,
    action_id: int,
    obs_agent: str,
    obs_idx: int,
    lo: float,
    hi: float,
) -> float:
    filtered = [
        step
        for step in steps
        if len(_obs(step, obs_agent)) > obs_idx and lo <= _obs(step, obs_agent)[obs_idx] <= hi
    ]
    if not filtered:
        return 0.0
    return sum(1 for step in filtered if _action(step, agent_action) == action_id) / len(filtered)


def _avg_obs(steps: list[dict[str, Any]], agent: str, idx: int) -> float:
    vals = [_obs(step, agent)[idx] for step in steps if len(_obs(step, agent)) > idx]
    return sum(vals) / len(vals) if vals else 0.0


def _common_val(step: dict[str, Any], key: str, default: float = 0.0) -> float:
    return float((step.get("common") or {}).get(key, default))


def _avg_common(steps: list[dict[str, Any]], key: str) -> float:
    vals = [_common_val(step, key) for step in steps]
    return sum(vals) / len(vals) if vals else 0.0


def _min_common(steps: list[dict[str, Any]], key: str) -> float:
    vals = [_common_val(step, key) for step in steps]
    return min(vals) if vals else 0.0


def _max_common(steps: list[dict[str, Any]], key: str) -> float:
    vals = [_common_val(step, key) for step in steps]
    return max(vals) if vals else 0.0


def _pct_common_above(steps: list[dict[str, Any]], key: str, threshold: float) -> float:
    if not steps:
        return 0.0
    return sum(1 for step in steps if _common_val(step, key) > threshold) / len(steps)


def _pct_common_below(steps: list[dict[str, Any]], key: str, threshold: float) -> float:
    if not steps:
        return 0.0
    return sum(1 for step in steps if _common_val(step, key) < threshold) / len(steps)


def extract_trajectory_metrics(raw: dict[str, Any] | None) -> dict[str, float]:
    if not raw:
        return {}
    steps = list(_iter_steps(raw))
    if not steps:
        return {}

    high_ci_steps = [step for step in steps if len(_obs(step, "ls")) > 2 and _obs(step, "ls")[2] > 0.7]
    low_ci_steps = [step for step in steps if len(_obs(step, "ls")) > 2 and _obs(step, "ls")[2] < 0.3]
    soc_steps_any = [step for step in steps if _common_val(step, "bat_SOC") > 0.05]
    soc_high_steps = [step for step in steps if _common_val(step, "bat_SOC") > 0.50]
    charge_allowed_steps = [step for step in steps if _common_val(step, "bat_SOC") < 0.80]

    metrics = {
        "trajectory_step_count": float(len(steps)),
        "ls_defer_fraction": _action_fraction(steps, "ls", 0),
        "ls_keep_fraction": _action_fraction(steps, "ls", 1),
        "ls_execute_fraction": _action_fraction(steps, "ls", 2),
        "dc_more_cooling_fraction": _action_fraction(steps, "dc", 0),
        "dc_keep_fraction": _action_fraction(steps, "dc", 1),
        "dc_less_cooling_fraction": _action_fraction(steps, "dc", 2),
        "bat_charge_fraction": _action_fraction(steps, "bat", 0),
        "bat_discharge_fraction": _action_fraction(steps, "bat", 1),
        "bat_idle_fraction": _action_fraction(steps, "bat", 2),
        "avg_ci": _avg_obs(steps, "ls", 2),
        "avg_queue_fill": _avg_obs(steps, "ls", 12),
        "avg_oldest_age": _avg_obs(steps, "ls", 10),
        "avg_overdue_frac": _avg_obs(steps, "ls", 25),
        "avg_workload": _avg_obs(steps, "ls", 13),
        "avg_temp": _avg_obs(steps, "ls", 14),
        "avg_soc": _avg_common(steps, "bat_SOC"),
        "min_soc": _min_common(steps, "bat_SOC"),
        "max_soc": _max_common(steps, "bat_SOC"),
        "soc_above_20_pct": _pct_common_above(steps, "bat_SOC", 0.20),
        "soc_above_50_pct": _pct_common_above(steps, "bat_SOC", 0.50),
        "avg_norm_ci": _avg_common(steps, "norm_CI"),
        "bat_discharge_when_soc_avail": _action_fraction(soc_steps_any, "bat", 1),
        "bat_discharge_when_soc_high": _action_fraction(soc_high_steps, "bat", 1),
        "bat_charge_when_soc_low": _action_fraction(charge_allowed_steps, "bat", 0),
        "ls_defer_fraction_high_ci": _binned_fraction(steps, "ls", 0, "ls", 2, 0.6, 1.0),
        "ls_defer_fraction_low_ci": _binned_fraction(steps, "ls", 0, "ls", 2, 0.0, 0.3),
        "ls_execute_fraction_high_ci": _binned_fraction(steps, "ls", 2, "ls", 2, 0.6, 1.0),
        "ls_execute_fraction_low_ci": _binned_fraction(steps, "ls", 2, "ls", 2, 0.0, 0.3),
        "dc_less_fraction_high_ci": _binned_fraction(steps, "dc", 2, "dc", 2, 0.6, 1.0),
        "dc_more_fraction_high_temp": _binned_fraction(steps, "dc", 0, "dc", 12, 0.6, 1.0),
        "dc_less_fraction_high_temp": _binned_fraction(steps, "dc", 2, "dc", 12, 0.6, 1.0),
        "bat_charge_fraction_low_ci": _binned_fraction(steps, "bat", 0, "bat", 2, 0.0, 0.3),
        "bat_discharge_fraction_high_ci": _binned_fraction(steps, "bat", 1, "bat", 2, 0.6, 1.0),
    }
    if high_ci_steps:
        metrics["bat_discharge_fraction_under_high_ci"] = _action_fraction(high_ci_steps, "bat", 1)
    if low_ci_steps:
        metrics["bat_charge_fraction_under_low_ci"] = _action_fraction(low_ci_steps, "bat", 0)
    return metrics


def extract_scenario_metrics(raw: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    if not raw:
        return {}
    result: dict[str, dict[str, float]] = {}
    for name, steps in _iter_scenarios(raw):
        if not steps:
            continue
        ci_vals = [_obs(step, "ls")[2] for step in steps if len(_obs(step, "ls")) > 2]
        result[name] = {
            "ls_defer": _action_fraction(steps, "ls", 0),
            "ls_execute": _action_fraction(steps, "ls", 2),
            "dc_more": _action_fraction(steps, "dc", 0),
            "dc_less": _action_fraction(steps, "dc", 2),
            "bat_charge": _action_fraction(steps, "bat", 0),
            "bat_discharge": _action_fraction(steps, "bat", 1),
            "avg_ci": _avg_obs(steps, "ls", 2),
            "min_ci": min(ci_vals) if ci_vals else 0.0,
            "max_ci": max(ci_vals) if ci_vals else 0.0,
            "avg_queue": _avg_obs(steps, "ls", 12),
            "avg_temp": _avg_obs(steps, "ls", 14),
            "avg_soc": _avg_common(steps, "bat_SOC"),
            "max_soc": _max_common(steps, "bat_SOC"),
            "norm_ci_above_half": _pct_common_above(steps, "norm_CI", 0.50),
            "norm_ci_below_quarter": _pct_common_below(steps, "norm_CI", 0.25),
        }
    return result


def _trajectory_diagnosis(metrics: dict[str, float]) -> list[str]:
    diagnosis: list[str] = []
    if not metrics:
        return diagnosis

    ls_defer = metrics.get("ls_defer_fraction", 0.0)
    ls_execute = metrics.get("ls_execute_fraction", 0.0)
    if ls_defer > 0.35 and ls_execute < 0.15:
        diagnosis.append(
            f"Load shifting defers often ({ls_defer:.0%}) but executes rarely "
            f"({ls_execute:.0%}); queue may not be draining."
        )

    ls_defer_hi = metrics.get("ls_defer_fraction_high_ci", -1.0)
    ls_defer_lo = metrics.get("ls_defer_fraction_low_ci", -1.0)
    if ls_defer_hi >= 0 and ls_defer_lo >= 0 and ls_defer_hi <= ls_defer_lo + 0.05:
        diagnosis.append(
            f"LS defers similarly under high CI ({ls_defer_hi:.0%}) and low CI "
            f"({ls_defer_lo:.0%}); defer logic may not be CI-aware."
        )

    ls_exec_hi = metrics.get("ls_execute_fraction_high_ci", -1.0)
    ls_exec_lo = metrics.get("ls_execute_fraction_low_ci", -1.0)
    if ls_exec_hi >= 0 and ls_exec_lo >= 0 and ls_exec_hi > ls_exec_lo + 0.05:
        diagnosis.append(
            f"LS executes more under high CI ({ls_exec_hi:.0%}) than low CI "
            f"({ls_exec_lo:.0%}); executing during dirty grid hurts carbon."
        )

    dc_more = metrics.get("dc_more_cooling_fraction", 0.0)
    dc_less = metrics.get("dc_less_cooling_fraction", 0.0)
    if dc_more > 0.40:
        diagnosis.append(
            f"Cooling agent chooses MORE_COOL on {dc_more:.0%} of steps; "
            "check hot-scenario water/carbon tradeoffs."
        )
    if dc_less > 0.40:
        diagnosis.append(
            f"Cooling agent chooses LESS_COOL on {dc_less:.0%} of steps; "
            "cooling may be insufficient under high outdoor temp."
        )

    dc_less_hi_ci = metrics.get("dc_less_fraction_high_ci", -1.0)
    if dc_less_hi_ci >= 0 and dc_less_hi_ci < 0.05 and dc_less > 0.10:
        diagnosis.append("Cooling rarely reduces cooling under high CI; missed carbon savings.")

    dc_more_hi_temp = metrics.get("dc_more_fraction_high_temp", -1.0)
    if dc_more_hi_temp >= 0 and dc_more_hi_temp < 0.05 and dc_less > 0.30:
        diagnosis.append("Cooling rarely increases cooling under high outdoor temp; may under-cool hot periods.")

    bat_charge = metrics.get("bat_charge_fraction", 0.0)
    bat_discharge = metrics.get("bat_discharge_fraction", 0.0)
    discharge_hi_ci = metrics.get("bat_discharge_fraction_under_high_ci")
    charge_lo_ci = metrics.get("bat_charge_fraction_under_low_ci")
    if discharge_hi_ci is not None and discharge_hi_ci < 0.05 and bat_discharge < 0.05:
        diagnosis.append("Battery rarely discharges, even under high carbon intensity.")
    if charge_lo_ci is not None and charge_lo_ci < 0.05 and bat_charge < 0.05:
        diagnosis.append("Battery rarely charges, even under low carbon intensity.")

    bat_charge_lo_ci = metrics.get("bat_charge_fraction_low_ci", -1.0)
    bat_disch_hi_ci = metrics.get("bat_discharge_fraction_high_ci", -1.0)
    if bat_charge > 0 and bat_charge_lo_ci < bat_charge * 0.5:
        diagnosis.append("Battery charging is not concentrated during low-CI periods.")
    if bat_discharge > 0 and bat_disch_hi_ci < bat_discharge * 0.5:
        diagnosis.append("Battery discharging is not concentrated during high-CI periods.")

    avg_soc = metrics.get("avg_soc", 0.0)
    max_soc = metrics.get("max_soc", 0.0)
    soc_above_50 = metrics.get("soc_above_50_pct", 0.0)
    if avg_soc < 0.10 and max_soc < 0.20:
        diagnosis.append(
            f"Battery SOC stays near zero (avg={avg_soc:.3f}, max={max_soc:.3f}); "
            "charging conditions may never be met or SOC drains early."
        )
    elif max_soc > 0.50 and soc_above_50 < 0.10:
        diagnosis.append(
            f"Battery occasionally charges (max_soc={max_soc:.3f}) but rarely stays above 50%."
        )

    bat_disch_when_soc = metrics.get("bat_discharge_when_soc_avail", -1.0)
    if bat_disch_when_soc >= 0 and bat_disch_when_soc > 0.50:
        diagnosis.append(
            f"Battery discharges on {bat_disch_when_soc:.0%} of steps where SOC > 5%; "
            "discharge may be too aggressive."
        )
    if bat_charge > 2.0 * bat_discharge + 0.10:
        diagnosis.append(
            f"Battery net charging rate is high ({bat_charge:.0%} charge vs {bat_discharge:.0%} discharge)."
        )
    return diagnosis


def _fmt(value: float) -> str:
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _format_score_limited(report: dict[str, Any]) -> str:
    score = float(report.get("average_score", 0.0))
    lines = [f"Score: {score:.4f}"]
    scenario_scores = build_scenario_scores(report)
    if scenario_scores:
        parts = [
            f"{name}={scenario_scores[name]:.2f}"
            for name in SCENARIO_ORDER
            if name in scenario_scores
        ]
        lines.append(f"Scenario scores: {', '.join(parts)}")
    for item in _coarse_diagnosis(report, limit=2):
        lines.append(f"- {item}")
    return "\n".join(lines)


def _format_feedback_with_meaning(
    report: dict[str, Any],
    trajectory_metrics: dict[str, float],
    scenario_metrics: dict[str, dict[str, float]],
) -> str:
    score = float(report.get("average_score", 0.0))
    scenario_scores = build_scenario_scores(report)
    breakdowns = build_scenario_breakdowns(report)
    lines = [f"Score: {score:.4f}"]
    if scenario_scores:
        parts = [
            f"{name}={scenario_scores[name]:.2f}"
            for name in SCENARIO_ORDER
            if name in scenario_scores
        ]
        lines.append(f"Scenario scores: {', '.join(parts)}")

    if breakdowns:
        parts = []
        for name in SCENARIO_ORDER:
            if name not in breakdowns:
                continue
            item = breakdowns[name]
            parts.append(
                f"{name}: carbon_gain={item['carbon_gain']:.3f}, "
                f"water_gain={item['water_gain']:.3f}, safety_penalty={item['safety_penalty']:.3f}"
            )
        if parts:
            lines.append("Scenario breakdowns: " + " | ".join(parts))

    metric_groups = {
        "Action fractions": [
            "ls_defer_fraction",
            "ls_keep_fraction",
            "ls_execute_fraction",
            "dc_more_cooling_fraction",
            "dc_keep_fraction",
            "dc_less_cooling_fraction",
            "bat_charge_fraction",
            "bat_discharge_fraction",
            "bat_idle_fraction",
        ],
        "State summaries": [
            "avg_ci",
            "avg_norm_ci",
            "avg_queue_fill",
            "avg_oldest_age",
            "avg_overdue_frac",
            "avg_workload",
            "avg_temp",
            "avg_soc",
            "min_soc",
            "max_soc",
            "soc_above_20_pct",
            "soc_above_50_pct",
        ],
        "CI-conditioned behavior": [
            "ls_defer_fraction_high_ci",
            "ls_defer_fraction_low_ci",
            "ls_execute_fraction_high_ci",
            "ls_execute_fraction_low_ci",
            "bat_charge_fraction_under_low_ci",
            "bat_discharge_fraction_under_high_ci",
            "bat_charge_fraction_low_ci",
            "bat_discharge_fraction_high_ci",
        ],
        "Cooling and SOC conditioned behavior": [
            "dc_less_fraction_high_ci",
            "dc_more_fraction_high_temp",
            "dc_less_fraction_high_temp",
            "bat_discharge_when_soc_avail",
            "bat_discharge_when_soc_high",
            "bat_charge_when_soc_low",
        ],
    }
    for title, keys in metric_groups.items():
        parts = [f"{key}={_fmt(trajectory_metrics[key])}" for key in keys if key in trajectory_metrics]
        if parts:
            lines.append(f"{title}: {', '.join(parts)}")

    for item in _coarse_diagnosis(report, limit=4) + _trajectory_diagnosis(trajectory_metrics):
        lines.append(f"- {item}")

    if scenario_metrics:
        for sc_name in sorted(scenario_metrics):
            sc_metrics = scenario_metrics[sc_name]
            parts = [f"{key}={_fmt(value)}" for key, value in sorted(sc_metrics.items())]
            lines.append(f"[{sc_name}] {', '.join(parts)}")
    return "\n".join(lines)


def analyze(program_path: str, output_dir: str, result: dict, feedback_mode: str) -> dict:
    del program_path
    if not result.get("is_valid"):
        return {
            "processed_feedback": (
                "Invalid policy; fix runtime errors before tuning control logic. "
                f"{result.get('feedback', '')}"
            ),
        }

    report = _report_from_output(output_dir)
    scenario_scores = build_scenario_scores(report)
    if feedback_mode == "score_limited":
        return {
            "processed_feedback": _format_score_limited(report),
            "analysis_metrics": {
                "average_score": float(report.get("average_score", 0.0)),
                "scenario_scores": scenario_scores,
            },
        }

    if feedback_mode != "feedback_with_meaning":
        raise ValueError(f"unknown feedback mode: {feedback_mode}")

    raw = _raw_from_output(output_dir)
    trajectory_metrics = extract_trajectory_metrics(raw)
    scenario_metrics = extract_scenario_metrics(raw)
    breakdowns = build_scenario_breakdowns(report)
    return {
        "processed_feedback": _format_feedback_with_meaning(
            report, trajectory_metrics, scenario_metrics
        ),
        "analysis_metrics": {
            "average_score": float(report.get("average_score", 0.0)),
            "scenario_scores": scenario_scores,
            "scenario_breakdowns": {
                name: {
                    "score": item["score"],
                    "carbon_gain": item["carbon_gain"],
                    "water_gain": item["water_gain"],
                    "safety_penalty": item["safety_penalty"],
                }
                for name, item in breakdowns.items()
            },
            "trajectory": trajectory_metrics,
            "scenario_trajectory": scenario_metrics,
        },
        "analysis": {
            "diagnosis": _coarse_diagnosis(report, limit=4) + _trajectory_diagnosis(trajectory_metrics),
            "raw_artifact_present": raw is not None,
        },
    }


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print(json.dumps(evaluate(candidate, out), indent=2, default=str))