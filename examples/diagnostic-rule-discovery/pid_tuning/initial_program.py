# EVOLVE-BLOCK-START
"""Diagnostic rules for PIDTuning using scenario-level evaluation traces."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

RawArtifact = Dict
RuleFn = Callable[[RawArtifact], Tuple[int, str]]


def _gains(raw: RawArtifact) -> Dict[str, float]:
    return {key: float(value) for key, value in dict(raw.get("gains") or {}).items()}


def _scenarios(raw: RawArtifact) -> Dict[str, Dict]:
    return {str(item["name"]): dict(item) for item in raw.get("scenarios") or []}


def _inv_itae(scenarios: Dict[str, Dict], name: str) -> float:
    return float(scenarios.get(name, {}).get("inv_itae", 0.0))


def rule_infeasible(raw: RawArtifact) -> Tuple[int, str]:
    feasible = bool(raw.get("feasible", False)) and float(raw.get("combined_score", 0.0)) > 0.0
    if not feasible:
        return 1, "combined_score=0 or feasible=false (invalid PID submission)"
    return 0, "Submission is feasible with positive combined_score"


def rule_wind_scenario_weak(raw: RawArtifact) -> Tuple[int, str]:
    scenarios = _scenarios(raw)
    wind = _inv_itae(scenarios, "combined_wind")
    others = [
        _inv_itae(scenarios, name)
        for name in ("vertical_hover", "lateral_move", "multi_waypoint")
        if _inv_itae(scenarios, name) > 0.0
    ]
    if not others or wind <= 0.0:
        return 0, "Skipped wind-weakness rule (missing feasible scenario data)"
    median_other = sorted(others)[len(others) // 2]
    if wind < 0.5 * median_other:
        return (
            1,
            f"combined_wind inv_itae={wind:.4f} < 0.5 * median_other={median_other:.4f}",
        )
    return 0, f"combined_wind inv_itae={wind:.4f} is not much weaker than other scenarios"


def rule_multi_waypoint_worst(raw: RawArtifact) -> Tuple[int, str]:
    scenarios = _scenarios(raw)
    positive = {
        name: _inv_itae(scenarios, name)
        for name in scenarios
        if _inv_itae(scenarios, name) > 0.0
    }
    if len(positive) < 2:
        return 0, "Skipped multi-waypoint rule (insufficient feasible scenarios)"
    worst_name = min(positive, key=positive.get)
    if worst_name == "multi_waypoint":
        return 1, f"multi_waypoint is weakest scenario (inv_itae={positive[worst_name]:.4f})"
    return 0, f"Worst scenario is {worst_name}, not multi_waypoint"


def rule_large_scenario_spread(raw: RawArtifact) -> Tuple[int, str]:
    scenarios = _scenarios(raw)
    values = [
        _inv_itae(scenarios, name)
        for name in scenarios
        if _inv_itae(scenarios, name) > 0.0
    ]
    if len(values) < 2:
        return 0, "Skipped spread rule (insufficient feasible scenarios)"
    ratio = max(values) / max(min(values), 1e-12)
    if ratio > 3.0:
        return 1, f"Scenario inv_itae spread ratio={ratio:.2f} > 3.0"
    return 0, f"Scenario inv_itae spread ratio={ratio:.2f} <= 3.0"


def rule_low_horizontal_gains(raw: RawArtifact) -> Tuple[int, str]:
    gains = _gains(raw)
    kp_x = gains.get("Kp_x", 0.0)
    kd_x = gains.get("Kd_x", 0.0)
    if kp_x < 0.3 or kd_x < 0.2:
        return 1, f"Horizontal gains are low (Kp_x={kp_x:.3f}, Kd_x={kd_x:.3f})"
    return 0, f"Horizontal gains are moderate (Kp_x={kp_x:.3f}, Kd_x={kd_x:.3f})"


def rule_high_altitude_integral(raw: RawArtifact) -> Tuple[int, str]:
    ki_z = _gains(raw).get("Ki_z", 0.0)
    if ki_z > 5.0:
        return 1, f"Altitude Ki_z={ki_z:.3f} > 5.0 (windup/overshoot risk)"
    return 0, f"Altitude Ki_z={ki_z:.3f} <= 5.0"


RULE_CATALOG = [
    ("rule_infeasible", "Submission is infeasible or scores zero."),
    ("rule_wind_scenario_weak", "combined_wind inv_itae is much weaker than other scenarios."),
    ("rule_multi_waypoint_worst", "multi_waypoint is the weakest scenario."),
    ("rule_large_scenario_spread", "Large ratio between best and worst scenario inv_itae."),
    ("rule_low_horizontal_gains", "Horizontal Kp_x or Kd_x is very low."),
    ("rule_high_altitude_integral", "Altitude Ki_z is very high."),
]


def get_rule_functions() -> List[RuleFn]:
    return [
        rule_infeasible,
        rule_wind_scenario_weak,
        rule_multi_waypoint_worst,
        rule_large_scenario_spread,
        rule_low_horizontal_gains,
        rule_high_altitude_integral,
    ]


def get_rule_descriptions() -> List[str]:
    return [entry[1] for entry in RULE_CATALOG]
# EVOLVE-BLOCK-END
