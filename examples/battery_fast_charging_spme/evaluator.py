"""BatteryFastChargingSPMe evaluator bridge for agentic-evolve."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import traceback
from pathlib import Path
from typing import Any

BENCHMARK_REL = Path("benchmarks") / "EnergyStorage" / "BatteryFastChargingSPMe"
FRONTIER_EVALUATOR_REL = BENCHMARK_REL / "verification" / "evaluator.py"
FRONTIER_CONFIG_REL = BENCHMARK_REL / "references" / "battery_config.json"
LOCAL_CONFIG_PATH = Path(__file__).resolve().parent / "references" / "battery_config.json"
DEFAULT_SCORE = 0.0


def _frontier_root_from_env() -> Path | None:
    raw = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _is_frontier_root(path: Path) -> bool:
    return (path / "frontier_eval").is_dir() and (path / FRONTIER_EVALUATOR_REL).is_file()


def _default_frontier_root() -> Path:
    env_root = _frontier_root_from_env()
    if env_root is not None:
        return env_root

    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering"):
            if _is_frontier_root(candidate):
                return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _load_frontier_evaluator(frontier_root: Path) -> Any:
    evaluator_path = (frontier_root / FRONTIER_EVALUATOR_REL).resolve()
    if not evaluator_path.is_file():
        raise FileNotFoundError(f"Frontier evaluator not found: {evaluator_path}")

    spec = importlib.util.spec_from_file_location(
        "_battery_fast_charging_spme_frontier_evaluator",
        evaluator_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load Frontier evaluator from {evaluator_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config_path(frontier_root: Path) -> Path:
    frontier_config = frontier_root / FRONTIER_CONFIG_REL
    if frontier_config.is_file():
        return frontier_config.resolve()
    return LOCAL_CONFIG_PATH.resolve()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_bool_metric(value: Any) -> bool:
    return _as_float(value, 0.0) > 0.0


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _numeric_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    return {key: float(value) for key, value in metrics.items() if isinstance(value, (int, float))}


def _artifact_summary(metrics: dict[str, Any], trace: dict[str, Any] | None) -> dict[str, Any]:
    trajectory = (trace or {}).get("trajectory") or {}
    derived = (trace or {}).get("derived") or {}
    return {
        "failure_reason": metrics.get("failure_reason", ""),
        "currents_c": metrics.get("currents_c", []),
        "switch_soc": metrics.get("switch_soc", []),
        "step_count": len(trajectory.get("steps") or []),
        "event_count": len(trajectory.get("events") or []),
        "first_limit_crossings": derived.get("first_limit_crossings", {}),
    }


def _format_feedback(score: float, valid: bool, metrics: dict[str, Any], trace: dict[str, Any] | None) -> str:
    lines = [
        f"Score: {score:.4f}",
        f"Valid: {valid}",
        f"Failure reason: {metrics.get('failure_reason', '') or 'none'}",
        f"Charge time seconds: {_as_float(metrics.get('charge_time_s')):.1f}",
        f"Max voltage V: {_as_float(metrics.get('max_voltage_v')):.4f}",
        f"Max temp C: {_as_float(metrics.get('max_temp_c')):.3f}",
        f"Min plating margin V: {_as_float(metrics.get('min_plating_margin_v')):.5f}",
        f"Plating loss Ah: {_as_float(metrics.get('plating_loss_ah')):.8g}",
        f"Aging loss Ah: {_as_float(metrics.get('aging_loss_ah')):.8g}",
    ]
    if metrics.get("currents_c"):
        lines.append(f"Currents C: {metrics.get('currents_c')}")
    if metrics.get("switch_soc"):
        lines.append(f"Switch SOC: {metrics.get('switch_soc')}")

    summary = _artifact_summary(metrics, trace)
    if summary["step_count"]:
        lines.append(f"Raw trajectory steps: {summary['step_count']}")
    crossings = summary.get("first_limit_crossings") or {}
    if crossings:
        parts = [f"{name}@{item.get('time_s', 0):.0f}s" for name, item in sorted(crossings.items())]
        lines.append(f"First limit crossings: {', '.join(parts)}")
    return "\n".join(lines)


def _persist_sidecars(
    output_dir: Path,
    metrics: dict[str, Any],
    artifacts: dict[str, Any],
    raw_artifacts: dict[str, Any],
) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(
            json.dumps(_json_safe(metrics), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "artifacts.json").write_text(
            json.dumps(_json_safe(artifacts), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "raw-artifact.json").write_text(
            json.dumps(_json_safe(raw_artifacts), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _failure_result(message: str, output_dir: Path, details: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = {
        "valid": 0.0,
        "combined_score": DEFAULT_SCORE,
        "failure_reason": message,
    }
    artifacts = {
        "error_message": message,
        "details": details or {},
    }
    raw_artifacts = {
        "benchmark": "EnergyStorage/BatteryFastChargingSPMe",
        "metrics": metrics,
        "artifacts": artifacts,
        "trajectory": {"steps": [], "events": []},
        "derived": {},
    }
    _persist_sidecars(output_dir, metrics, artifacts, raw_artifacts)
    return {
        "score": DEFAULT_SCORE,
        "is_valid": False,
        "feedback": message,
        "metrics": metrics,
        "construction": {"metrics": metrics, "summary": _artifact_summary(metrics, raw_artifacts)},
        "raw_artifacts": raw_artifacts,
    }


def _first_crossings(steps: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, dict[str, float]]:
    limits = cfg["limits"]
    crossing_specs = {
        "soft_voltage": ("voltage_v", float(limits["max_voltage_v"]), "above"),
        "hard_voltage": ("voltage_v", float(limits["hard_voltage_cutoff_v"]), "above"),
        "soft_temp": ("temp_c", float(limits["soft_temp_c"]), "above"),
        "hard_temp": ("temp_c", float(limits["hard_temp_c"]), "above"),
        "soft_plating": ("plating_margin_v", float(limits["soft_plating_margin_v"]), "below"),
        "hard_plating": ("plating_margin_v", float(limits["hard_plating_margin_v"]), "below"),
    }
    found: dict[str, dict[str, float]] = {}
    for step in steps:
        for name, (field, threshold, direction) in crossing_specs.items():
            if name in found:
                continue
            value = _as_float(step.get(field))
            crossed = value > threshold if direction == "above" else value < threshold
            if crossed:
                found[name] = {
                    "time_s": _as_float(step.get("time_s")),
                    "soc": _as_float(step.get("soc")),
                    "value": value,
                    "threshold": threshold,
                }
    return found


def _stage_stats(steps: list[dict[str, Any]], stage_count: int) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for stage_idx in range(stage_count):
        selected = [step for step in steps if int(step.get("stage_idx", -1)) == stage_idx]
        if not selected:
            stats.append({"stage_idx": stage_idx, "step_count": 0})
            continue
        stats.append(
            {
                "stage_idx": stage_idx,
                "step_count": len(selected),
                "start_soc": _as_float(selected[0].get("soc")),
                "end_soc": _as_float(selected[-1].get("soc_next", selected[-1].get("soc"))),
                "current_c": _as_float(selected[0].get("current_c")),
                "max_voltage_v": max(_as_float(step.get("voltage_v")) for step in selected),
                "max_temp_c": max(_as_float(step.get("temp_c")) for step in selected),
                "min_plating_margin_v": min(_as_float(step.get("plating_margin_v")) for step in selected),
                "plating_loss_ah": _as_float(selected[-1].get("plating_loss_ah")) - _as_float(selected[0].get("plating_loss_ah")),
                "aging_loss_ah": _as_float(selected[-1].get("aging_loss_ah")) - _as_float(selected[0].get("aging_loss_ah")),
            }
        )
    return stats


def _soc_band_stats(steps: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    bands = {
        "soc_0.10_0.30": (0.10, 0.30),
        "soc_0.30_0.50": (0.30, 0.50),
        "soc_0.50_0.70": (0.50, 0.70),
        "soc_0.70_0.90": (0.70, 0.91),
    }
    result: dict[str, dict[str, float]] = {}
    for name, (low, high) in bands.items():
        selected = [step for step in steps if low <= _as_float(step.get("soc")) < high]
        if not selected:
            continue
        result[name] = {
            "step_count": float(len(selected)),
            "max_voltage_v": max(_as_float(step.get("voltage_v")) for step in selected),
            "max_temp_c": max(_as_float(step.get("temp_c")) for step in selected),
            "min_plating_margin_v": min(_as_float(step.get("plating_margin_v")) for step in selected),
            "avg_current_c": sum(_as_float(step.get("current_c")) for step in selected) / len(selected),
        }
    return result


def _derive_trace(steps: list[dict[str, Any]], events: list[dict[str, Any]], cfg: dict[str, Any], stage_count: int) -> dict[str, Any]:
    high_soc_high_current = [
        step
        for step in steps
        if _as_float(step.get("soc")) >= 0.70 and _as_float(step.get("current_c")) >= 3.0
    ]
    return {
        "step_count": len(steps),
        "events": events,
        "first_limit_crossings": _first_crossings(steps, cfg),
        "stage_stats": _stage_stats(steps, stage_count),
        "soc_band_stats": _soc_band_stats(steps),
        "high_soc_high_current_steps": len(high_soc_high_current),
    }


def _simulate_with_trace(frontier: Any, currents_c: list[float], switch_soc: list[float], cfg: dict[str, Any]) -> dict[str, Any]:
    battery = cfg["battery"]
    limits = cfg["limits"]
    sim = cfg["simulation"]
    solid = cfg["solid_diffusion"]
    electrolyte = cfg["electrolyte"]
    kinetics = cfg["kinetics"]
    resistance = cfg["resistance"]
    thermal = cfg["thermal"]
    aging = cfg["aging"]
    scoring = cfg["scoring"]

    capacity_ah = float(battery["capacity_ah"])
    dt_s = float(sim["dt_s"])
    max_time_s = float(sim["max_time_s"])
    temp_ref_k = float(sim["temperature_ref_k"])
    ambient_temp_c = float(battery["ambient_temp_c"])
    cold_reference_c = temp_ref_k - 273.15

    soc = float(battery["initial_soc"])
    target_soc = float(battery["target_soc"])
    theta_n_avg = frontier._theta_n_from_soc(soc, cfg)
    theta_p_avg = frontier._theta_p_from_soc(soc, cfg)
    delta_theta_n = 0.0
    delta_theta_p = 0.0
    electrolyte_state = 0.0
    temp_c = ambient_temp_c
    plating_loss_ah = 0.0
    aging_loss_ah = 0.0
    max_temp_c = temp_c
    max_voltage_v = -1e9
    min_plating_margin_v = 1e9
    time_s = 0.0
    stage_idx = 0
    endpoints = list(switch_soc) + [target_soc]
    steps: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def append_event(kind: str, reason: str) -> None:
        events.append({"event": kind, "failure_reason": reason, "time_s": time_s, "soc": soc})

    def invalid_result(reason: str) -> dict[str, Any]:
        return {
            "valid": 0.0,
            "failure_reason": reason,
            "charge_time_s": time_s,
            "max_temp_c": max_temp_c,
            "max_voltage_v": max_voltage_v,
            "min_plating_margin_v": min_plating_margin_v,
            "plating_loss_ah": plating_loss_ah,
            "aging_loss_ah": aging_loss_ah,
            "combined_score": 0.0,
        }

    while time_s < max_time_s and soc < target_soc:
        while stage_idx < len(endpoints) - 1 and soc >= endpoints[stage_idx]:
            stage_idx += 1

        current_c = currents_c[stage_idx]
        current_a = current_c * capacity_ah
        temp_k = temp_c + 273.15

        scale_n = frontier._arrhenius_scale(temp_k, temp_ref_k, float(solid["activation_energy_n_j_per_mol"]))
        scale_p = frontier._arrhenius_scale(temp_k, temp_ref_k, float(solid["activation_energy_p_j_per_mol"]))
        scale_e = frontier._arrhenius_scale(temp_k, temp_ref_k, float(electrolyte["activation_energy_j_per_mol"]))
        scale_k = frontier._arrhenius_scale(temp_k, temp_ref_k, float(kinetics["activation_energy_j_per_mol"]))
        scale_r = 1.0 / frontier._arrhenius_scale(temp_k, temp_ref_k, float(resistance["activation_energy_j_per_mol"]))
        scale_sei = frontier._arrhenius_scale(temp_k, temp_ref_k, float(aging["sei_activation_energy_j_per_mol"]))

        tau_n = float(solid["tau_n_ref_s"]) / scale_n
        tau_p = float(solid["tau_p_ref_s"]) / scale_p
        tau_e = float(electrolyte["tau_ref_s"]) / scale_e

        delta_theta_n += dt_s * (
            float(solid["surface_gain_n_per_a"]) * current_a - delta_theta_n / max(tau_n, 1e-6)
        )
        delta_theta_p += dt_s * (
            -float(solid["surface_gain_p_per_a"]) * current_a - delta_theta_p / max(tau_p, 1e-6)
        )
        electrolyte_state += dt_s * (
            float(electrolyte["polarization_gain_per_a"]) * current_a - electrolyte_state / max(tau_e, 1e-6)
        )

        theta_n_surf = frontier._clamp(theta_n_avg + delta_theta_n, 1e-5, 1.0 - 1e-5)
        theta_p_surf = frontier._clamp(theta_p_avg + delta_theta_p, 1e-5, 1.0 - 1e-5)
        electrolyte_factor = max(
            0.2,
            1.0 - float(kinetics["electrolyte_factor"]) * abs(electrolyte_state),
        )
        i0_n = max(
            1e-6,
            float(kinetics["i0_n_ref_a"])
            * scale_k
            * math.sqrt(theta_n_surf * (1.0 - theta_n_surf))
            * electrolyte_factor,
        )
        i0_p = max(
            1e-6,
            float(kinetics["i0_p_ref_a"])
            * scale_k
            * math.sqrt(theta_p_surf * (1.0 - theta_p_surf))
            * electrolyte_factor,
        )

        eta_n = 2.0 * frontier.GAS_CONSTANT_J_PER_MOLK * temp_k / frontier.FARADAY_C_PER_MOL * math.asinh(current_a / (2.0 * i0_n))
        eta_p = 2.0 * frontier.GAS_CONSTANT_J_PER_MOLK * temp_k / frontier.FARADAY_C_PER_MOL * math.asinh(current_a / (2.0 * i0_p))

        avg_soc = frontier._clamp(frontier._soc_from_theta_n(theta_n_avg, cfg), 0.0, 1.0)
        high_soc_penalty = max(0.0, avg_soc - 0.7)
        low_soc_penalty = max(0.0, 0.2 - avg_soc)
        r_ohm = float(resistance["r_ohm_ref_ohm"]) * scale_r * (
            1.0
            + float(resistance["high_soc_coeff"]) * high_soc_penalty
            + float(resistance["low_soc_coeff"]) * low_soc_penalty
        )
        phi_e = float(electrolyte["phi_e_coeff_v"]) * electrolyte_state

        ocv_positive_v = frontier._ocv_positive(theta_p_surf, temp_k, cfg)
        ocv_negative_v = frontier._ocv_negative(theta_n_surf, temp_k, cfg)
        open_circuit_voltage_v = ocv_positive_v - ocv_negative_v
        voltage_v = open_circuit_voltage_v + eta_p + eta_n + current_a * r_ohm + phi_e
        max_voltage_v = max(max_voltage_v, voltage_v)
        plating_margin_v = (
            ocv_negative_v
            - eta_n
            - 0.5 * phi_e
            - float(aging["temperature_penalty_coeff"]) * max(0.0, cold_reference_c - temp_c)
        )
        min_plating_margin_v = min(min_plating_margin_v, plating_margin_v)

        step = {
            "time_s": time_s,
            "soc": soc,
            "stage_idx": stage_idx,
            "current_c": current_c,
            "current_a": current_a,
            "voltage_v": voltage_v,
            "open_circuit_voltage_v": open_circuit_voltage_v,
            "temp_c": temp_c,
            "plating_margin_v": plating_margin_v,
            "plating_loss_ah": plating_loss_ah,
            "aging_loss_ah": aging_loss_ah,
            "theta_n_avg": theta_n_avg,
            "theta_p_avg": theta_p_avg,
            "theta_n_surf": theta_n_surf,
            "theta_p_surf": theta_p_surf,
            "electrolyte_state": electrolyte_state,
            "eta_n_v": eta_n,
            "eta_p_v": eta_p,
        }

        if voltage_v > float(limits["hard_voltage_cutoff_v"]):
            step["event"] = "voltage_cutoff"
            steps.append(step)
            append_event("failure", "voltage_cutoff")
            trace_metrics = invalid_result("voltage_cutoff")
            return {"metrics": trace_metrics, "trajectory": {"steps": steps, "events": events}}

        if plating_margin_v < float(limits["hard_plating_margin_v"]):
            step["event"] = "plating_margin_cutoff"
            steps.append(step)
            append_event("failure", "plating_margin_cutoff")
            trace_metrics = invalid_result("plating_margin_cutoff")
            return {"metrics": trace_metrics, "trajectory": {"steps": steps, "events": events}}

        plating_stress = max(0.0, float(limits["soft_plating_margin_v"]) - plating_margin_v)
        plating_loss_ah += (
            float(aging["plating_loss_coeff"])
            * current_a
            * plating_stress ** float(aging["plating_power"])
            * dt_s
            / 3600.0
        )
        sei_rate_ah_per_s = (
            float(aging["sei_rate_ref_ah_per_s"])
            * scale_sei
            * math.exp(float(aging["sei_stress_coeff"]) * max(0.0, float(aging["sei_margin_v"]) - plating_margin_v))
        )
        aging_loss_ah += sei_rate_ah_per_s * dt_s

        entropy_term = frontier._entropy_term(theta_p_surf, theta_n_surf, cfg)
        heat_gen_w = abs(current_a * (voltage_v - open_circuit_voltage_v)) + abs(current_a * temp_k * entropy_term) * float(thermal["entropy_scale"])
        temp_c += dt_s * (
            heat_gen_w - float(thermal["h_a_w_per_k"]) * (temp_c - ambient_temp_c)
        ) / float(thermal["mass_cp_j_per_k"])
        max_temp_c = max(max_temp_c, temp_c)

        step["plating_loss_ah_next"] = plating_loss_ah
        step["aging_loss_ah_next"] = aging_loss_ah
        step["temp_c_next"] = temp_c

        if temp_c > float(limits["hard_temp_c"]):
            step["event"] = "thermal_cutoff"
            steps.append(step)
            append_event("failure", "thermal_cutoff")
            trace_metrics = invalid_result("thermal_cutoff")
            return {"metrics": trace_metrics, "trajectory": {"steps": steps, "events": events}}

        delta_soc = current_a * dt_s / (capacity_ah * 3600.0)
        soc_next = frontier._clamp(soc + delta_soc, 0.0, 1.0)
        step["soc_next"] = soc_next
        steps.append(step)
        soc = soc_next
        theta_n_avg = frontier._theta_n_from_soc(soc, cfg)
        theta_p_avg = frontier._theta_p_from_soc(soc, cfg)
        time_s += dt_s

    if soc < target_soc:
        append_event("failure", "timeout")
        trace_metrics = invalid_result("timeout")
        return {"metrics": trace_metrics, "trajectory": {"steps": steps, "events": events}}

    time_score = math.exp(-(time_s - float(scoring["time_reference_s"])) / float(scoring["time_scale_s"]))
    aging_score = math.exp(-float(scoring["aging_coeff"]) * aging_loss_ah)
    plating_score = math.exp(-float(scoring["plating_coeff"]) * plating_loss_ah)
    thermal_score = math.exp(
        -max(0.0, max_temp_c - float(scoring["thermal_reference_c"])) / float(scoring["thermal_scale_c"])
    )
    voltage_score = math.exp(
        -max(0.0, max_voltage_v - float(limits["max_voltage_v"])) / float(scoring["voltage_scale_v"])
    )
    combined_score = float(scoring["score_scale"]) * (
        float(scoring["weight_time"]) * time_score
        + float(scoring["weight_aging"]) * aging_score
        + float(scoring["weight_plating"]) * plating_score
        + float(scoring["weight_thermal"]) * thermal_score
        + float(scoring["weight_voltage"]) * voltage_score
    )
    append_event("success", "")
    trace_metrics = {
        "valid": 1.0,
        "failure_reason": "",
        "charge_time_s": time_s,
        "max_temp_c": max_temp_c,
        "max_voltage_v": max_voltage_v,
        "min_plating_margin_v": min_plating_margin_v,
        "plating_loss_ah": plating_loss_ah,
        "aging_loss_ah": aging_loss_ah,
        "time_score": time_score,
        "aging_score": aging_score,
        "plating_score": plating_score,
        "thermal_score": thermal_score,
        "voltage_score": voltage_score,
        "combined_score": combined_score,
        "soft_temp_violation": 1.0 if max_temp_c > float(limits["soft_temp_c"]) else 0.0,
        "soft_voltage_violation": 1.0 if max_voltage_v > float(limits["max_voltage_v"]) else 0.0,
        "soft_plating_violation": 1.0 if min_plating_margin_v < float(limits["soft_plating_margin_v"]) else 0.0,
        "final_soc": soc,
    }
    return {"metrics": trace_metrics, "trajectory": {"steps": steps, "events": events}}


def _build_trace(frontier: Any, program_path: Path, config_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cfg = frontier._load_config(config_path)
    policy = frontier._load_candidate(program_path)
    currents_c, switch_soc = frontier._validate_policy(policy, cfg)
    trace = _simulate_with_trace(frontier, currents_c, switch_soc, cfg)
    trace_metrics = dict(trace.get("metrics") or {})
    trace_metrics["currents_c"] = currents_c
    trace_metrics["switch_soc"] = switch_soc
    trace_metrics["config_path"] = str(config_path)
    trace_metrics["battery_name"] = str(cfg["battery"].get("name", "battery"))
    trajectory = trace.get("trajectory") or {"steps": [], "events": []}
    derived = _derive_trace(
        list(trajectory.get("steps") or []),
        list(trajectory.get("events") or []),
        cfg,
        len(currents_c),
    )
    trace["metrics"] = trace_metrics
    trace["derived"] = derived
    trace["policy"] = {"currents_c": currents_c, "switch_soc": switch_soc}
    return trace, {"currents_c": currents_c, "switch_soc": switch_soc}, cfg


def evaluate(program_path: str, output_dir: str) -> dict[str, Any]:
    output_dir_p = Path(output_dir).expanduser().resolve()
    output_dir_p.mkdir(parents=True, exist_ok=True)
    program_path_p = Path(program_path).expanduser().resolve()

    if not program_path_p.is_file():
        return _failure_result(f"Candidate program not found: {program_path_p}", output_dir_p)

    try:
        frontier_root = _default_frontier_root()
        frontier = _load_frontier_evaluator(frontier_root)
        config_path = _config_path(frontier_root)
    except Exception as exc:
        return _failure_result(str(exc), output_dir_p, {"traceback": traceback.format_exc()})

    trace: dict[str, Any] | None = None
    policy: dict[str, Any] = {"currents_c": [], "switch_soc": []}
    trace_error = ""
    try:
        trace, policy, _ = _build_trace(frontier, program_path_p, config_path)
    except Exception as exc:
        trace_error = f"Failed to build trajectory artifact: {exc}"
        trace = {
            "metrics": {},
            "policy": policy,
            "trajectory": {"steps": [], "events": []},
            "derived": {},
            "traceback": traceback.format_exc(),
        }

    try:
        official = frontier.evaluate(program_path_p, config_path=config_path)
        metrics = dict(official)
    except Exception as exc:
        return _failure_result(
            f"Failed to run Frontier evaluator: {exc}",
            output_dir_p,
            {"traceback": traceback.format_exc(), "trace_error": trace_error},
        )

    metrics["candidate_path"] = str(program_path_p)
    metrics.setdefault("config_path", str(config_path))
    metrics.setdefault("currents_c", policy.get("currents_c", []))
    metrics.setdefault("switch_soc", policy.get("switch_soc", []))
    if trace_error:
        metrics["trace_artifact_warning"] = trace_error

    valid = _as_bool_metric(metrics.get("valid"))
    score = _as_float(metrics.get("combined_score"), DEFAULT_SCORE)
    if not valid:
        score = DEFAULT_SCORE

    artifacts = {
        "candidate_path": str(program_path_p),
        "config_path": str(config_path),
        "frontier_root": str(frontier_root),
        "failure_reason": metrics.get("failure_reason", ""),
        "currents_c": metrics.get("currents_c", []),
        "switch_soc": metrics.get("switch_soc", []),
        "trace_artifact_warning": trace_error,
    }
    if "traceback" in metrics:
        artifacts["traceback"] = metrics["traceback"]

    raw_artifacts = {
        "benchmark": "EnergyStorage/BatteryFastChargingSPMe",
        "frontier_root": str(frontier_root),
        "candidate_program": str(program_path_p),
        "config_path": str(config_path),
        "policy": {
            "currents_c": metrics.get("currents_c", []),
            "switch_soc": metrics.get("switch_soc", []),
        },
        "metrics": metrics,
        "trace_metrics": (trace or {}).get("metrics", {}),
        "artifacts": artifacts,
        "trajectory": (trace or {}).get("trajectory", {"steps": [], "events": []}),
        "derived": (trace or {}).get("derived", {}),
    }
    construction = {
        "benchmark": "EnergyStorage/BatteryFastChargingSPMe",
        "metrics": metrics,
        "summary": _artifact_summary(metrics, raw_artifacts),
        "derived": raw_artifacts["derived"],
    }
    feedback = _format_feedback(score, valid, metrics, raw_artifacts)

    _persist_sidecars(output_dir_p, metrics, artifacts, raw_artifacts)

    return {
        "score": score,
        "is_valid": valid,
        "feedback": feedback,
        "metrics": _numeric_metrics(metrics),
        "construction": construction,
        "raw_artifacts": raw_artifacts,
    }


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    result = evaluate(candidate, out)
    printable = dict(result)
    raw = printable.pop("raw_artifacts", {})
    trajectory = raw.get("trajectory", {}) if isinstance(raw, dict) else {}
    printable["raw_artifacts_summary"] = {
        "present": bool(raw),
        "step_count": len(trajectory.get("steps") or []),
        "event_count": len(trajectory.get("events") or []),
        "derived_keys": sorted((raw.get("derived") or {}).keys()) if isinstance(raw, dict) else [],
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
