# EVOLVE-BLOCK-START
"""Diagnostic rules using only policy-visible observations + actions (no common)."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Sequence, Tuple

RawArtifact = Dict
Step = Dict
RuleFn = Callable[[RawArtifact], Tuple[int, str]]

# SustainDC observation indices (same as examples/sustaindc/problem.md §4).
LS = {
    "time_cos_hour": 0,
    "time_sin_hour": 1,
    "ci_current": 2,
    "ci_future_slope": 3,
    "ci_past_slope": 4,
    "ci_future_mean": 5,
    "ci_future_std": 6,
    "ci_percentile": 7,
    "ci_time_to_next_peak_norm": 8,
    "ci_time_to_next_valley_norm": 9,
    "queue_oldest_age": 10,
    "queue_average_age": 11,
    "queue_fill_ratio": 12,
    "workload_current": 13,
    "outdoor_temp_current_norm": 14,
    "temp_future_slope": 15,
    "temp_future_mean": 16,
    "temp_future_std": 17,
    "temp_percentile": 18,
    "temp_time_to_next_peak_norm": 19,
    "temp_time_to_next_valley_norm": 20,
    "queue_hist_0_6h": 21,
    "queue_hist_6_12h": 22,
    "queue_hist_12_18h": 23,
    "queue_hist_18_24h": 24,
    "queue_hist_over_24h": 25,
}

DC = {
    "time_cos_hour": 0,
    "time_sin_hour": 1,
    "ci_current": 2,
    "ci_future_slope": 3,
    "ci_past_slope": 4,
    "ci_future_mean": 5,
    "ci_future_std": 6,
    "ci_percentile": 7,
    "ci_time_to_next_peak_norm": 8,
    "ci_time_to_next_valley_norm": 9,
    "workload_current": 10,
    "workload_next": 11,
    "outdoor_temp_current_norm": 12,
    "outdoor_temp_next_norm": 13,
}

BAT = {
    "time_cos_hour": 0,
    "time_sin_hour": 1,
    "ci_current": 2,
    "ci_future_slope": 3,
    "ci_past_slope": 4,
    "ci_future_mean": 5,
    "ci_future_std": 6,
    "ci_percentile": 7,
    "ci_time_to_next_peak_norm": 8,
    "ci_time_to_next_valley_norm": 9,
    "workload_current": 10,
    "outdoor_temp_current_norm": 11,
    "battery_soc": 12,
}

# SustainDC discrete actions (same as sustaindc/problem.md).
LS_DEFER, LS_HOLD, LS_EXECUTE = 0, 1, 2
DC_MORE_COOL, DC_HOLD, DC_LESS_COOL = 0, 1, 2
BAT_CHARGE, BAT_DISCHARGE, BAT_IDLE = 0, 1, 2


def _iter_steps(raw: RawArtifact) -> Iterable[Step]:
    for scenario in raw.get("scenarios", []):
        for step in scenario.get("steps", []):
            yield step


def _obs(step: Step, agent: str) -> Sequence[float]:
    return (step.get("observations") or {}).get(agent, [])


def _action(step: Step, agent: str) -> int:
    return int((step.get("actions") or {}).get(agent, 1))


def _steps_where(raw: RawArtifact, agent: str, predicate) -> List[Step]:
    matched: List[Step] = []
    for step in _iter_steps(raw):
        obs = _obs(step, agent)
        if predicate(obs, step):
            matched.append(step)
    return matched


def _action_fraction(steps: List[Step], agent: str, action_id: int) -> float:
    if not steps:
        return 0.0
    hits = sum(1 for s in steps if _action(s, agent) == action_id)
    return hits / len(steps)


def _rule_obs_action_fraction(
    raw: RawArtifact,
    *,
    agent: str,
    obs_predicate,
    target_action: int,
    min_fraction: float,
    obs_label: str,
    action_label: str,
) -> Tuple[int, str]:
    """Standard rule shape: on steps matching obs condition, action share must exceed threshold."""
    matched = _steps_where(raw, agent, obs_predicate)
    if not matched:
        return 0, f"No steps matched obs filter ({obs_label})"
    frac = _action_fraction(matched, agent, target_action)
    if frac > min_fraction:
        return (
            1,
            f"On {len(matched)} steps with {obs_label}, {action_label} fraction "
            f"{frac:.2%} > {min_fraction:.0%}",
        )
    return (
        0,
        f"On {len(matched)} steps with {obs_label}, {action_label} fraction "
        f"{frac:.2%} <= {min_fraction:.0%}",
    )


def rule_defer_under_high_ci(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        agent="agent_ls",
        obs_predicate=lambda o, _s: len(o) > LS["ci_current"] and o[LS["ci_current"]] > 0.60,
        target_action=LS_DEFER,
        min_fraction=0.25,
        obs_label="agent_ls ci_current > 0.60",
        action_label="defer (0)",
    )


def rule_execute_under_queue_pressure(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        agent="agent_ls",
        obs_predicate=lambda o, _s: len(o) > LS["queue_fill_ratio"] and o[LS["queue_fill_ratio"]] > 0.40,
        target_action=LS_EXECUTE,
        min_fraction=0.30,
        obs_label="agent_ls queue_fill > 0.40",
        action_label="execute (2)",
    )


def rule_more_cooling_when_hot(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        agent="agent_dc",
        obs_predicate=lambda o, _s: len(o) > DC["outdoor_temp_current_norm"] and o[DC["outdoor_temp_current_norm"]] > 0.65,
        target_action=DC_MORE_COOL,
        min_fraction=0.20,
        obs_label="agent_dc outdoor_temp > 0.65",
        action_label="more cooling (0)",
    )


def rule_less_cooling_under_high_workload(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        agent="agent_dc",
        obs_predicate=lambda o, _s: len(o) > DC["workload_current"] and o[DC["workload_current"]] > 0.55,
        target_action=DC_LESS_COOL,
        min_fraction=0.25,
        obs_label="agent_dc workload > 0.55",
        action_label="less cooling (2)",
    )


def rule_charge_when_soc_low(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        agent="agent_bat",
        obs_predicate=lambda o, _s: len(o) > BAT["battery_soc"] and o[BAT["battery_soc"]] < 0.12,
        target_action=BAT_CHARGE,
        min_fraction=0.35,
        obs_label="agent_bat soc < 0.12",
        action_label="charge (0)",
    )


def rule_discharge_when_ci_high_and_soc_ok(raw: RawArtifact) -> Tuple[int, str]:
    def pred(o: Sequence[float], _s: Step) -> bool:
        return (
            len(o) > BAT["battery_soc"]
            and len(o) > BAT["ci_current"]
            and o[BAT["ci_current"]] > 0.55
            and o[BAT["battery_soc"]] > 0.08
        )

    return _rule_obs_action_fraction(
        raw,
        agent="agent_bat",
        obs_predicate=pred,
        target_action=BAT_DISCHARGE,
        min_fraction=0.15,
        obs_label="agent_bat ci_current > 0.55 and soc > 0.08",
        action_label="discharge (1)",
    )


def rule_idle_when_future_ci_high(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        agent="agent_bat",
        obs_predicate=lambda o, _s: len(o) > BAT["ci_future_mean"] and o[BAT["ci_future_mean"]] > 0.62,
        target_action=BAT_IDLE,
        min_fraction=0.40,
        obs_label="agent_bat ci_future_mean > 0.62",
        action_label="idle (2)",
    )


def rule_hold_ls_when_old_queue_share_high(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        agent="agent_ls",
        obs_predicate=lambda o, _s: len(o) > LS["queue_hist_over_24h"] and o[LS["queue_hist_over_24h"]] > 0.05,
        target_action=LS_HOLD,
        min_fraction=0.50,
        obs_label="agent_ls queue_hist_over_24h > 0.05",
        action_label="hold (1)",
    )


RULE_CATALOG: List[Tuple[str, str, RuleFn]] = [
    (
        "defer_under_high_ci",
        "On high carbon-intensity steps (agent_ls obs ci_current > 0.60), defer action (0) "
        "accounts for more than 25% of actions.",
        rule_defer_under_high_ci,
    ),
    (
        "execute_under_queue_pressure",
        "On high queue-fill steps (agent_ls queue_fill > 0.40), execute-from-queue (2) "
        "accounts for more than 30% of actions.",
        rule_execute_under_queue_pressure,
    ),
    (
        "more_cooling_when_hot",
        "On hot outdoor-temp steps (agent_dc outdoor_temp > 0.65), more-cooling (0) "
        "accounts for more than 20% of actions.",
        rule_more_cooling_when_hot,
    ),
    (
        "less_cooling_high_workload",
        "On high-workload steps (agent_dc workload > 0.55), less-cooling (2) "
        "accounts for more than 25% of actions.",
        rule_less_cooling_under_high_workload,
    ),
    (
        "charge_when_soc_low",
        "On low-SOC steps (agent_bat soc < 0.12), charge (0) accounts for more than 35% of actions.",
        rule_charge_when_soc_low,
    ),
    (
        "discharge_high_ci_soc_ok",
        "On high-CI steps with SOC > 0.08, discharge (1) accounts for more than 15% of actions.",
        rule_discharge_when_ci_high_and_soc_ok,
    ),
    (
        "idle_when_future_ci_high",
        "On high future-CI steps (agent_bat ci_future_mean > 0.62), idle (2) "
        "accounts for more than 40% of actions.",
        rule_idle_when_future_ci_high,
    ),
    (
        "hold_ls_old_queue_share",
        "On steps with old-queue share > 0.05, load-shifting hold (1) accounts for more than 50% of actions.",
        rule_hold_ls_when_old_queue_share_high,
    ),
]


def get_rule_descriptions() -> List[str]:
    return [desc for _name, desc, _fn in RULE_CATALOG]


def get_rule_functions() -> List[RuleFn]:
    return [fn for _name, _desc, fn in RULE_CATALOG]
# EVOLVE-BLOCK-END
