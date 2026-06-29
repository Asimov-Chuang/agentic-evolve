# EVOLVE-BLOCK-START
"""Diagnostic rules using only policy-visible case observations + port actions."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Tuple

RawArtifact = Dict
Step = Dict
RuleFn = Callable[[RawArtifact], Tuple[int, str]]


def _iter_steps(raw: RawArtifact) -> Iterable[Step]:
    for scenario in raw.get("scenarios", []):
        for step in scenario.get("steps", []):
            yield step


def _obs(step: Step) -> Dict[str, Any]:
    return dict(step.get("observations") or {})


def _actions(step: Step) -> List[float]:
    raw = step.get("actions") or {}
    if isinstance(raw, dict):
        values = raw.get("actions") or []
    else:
        values = raw
    return [float(value) for value in values]


def _mean_future_charge_price(obs: Dict[str, Any]) -> float:
    prices = list(obs.get("future_charge_prices") or [])
    if not prices:
        return 0.0
    return sum(float(value) for value in prices) / len(prices)


def _mean_future_discharge_price(obs: Dict[str, Any]) -> float:
    prices = list(obs.get("future_discharge_prices") or [])
    if not prices:
        return 0.0
    return sum(float(value) for value in prices) / len(prices)


def _connected_ports(obs: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [port for port in list(obs.get("ports") or []) if bool(port.get("connected", False))]


def _any_transformer_overloaded(obs: Dict[str, Any]) -> bool:
    return any(bool(item.get("is_overloaded", False)) for item in list(obs.get("transformers") or []))


def _urgent_departure_port(obs: Dict[str, Any], *, max_remaining_steps: int = 8) -> bool:
    for port in _connected_ports(obs):
        remaining = int(port.get("remaining_steps", 999))
        required = float(port.get("required_energy_kwh", 0.0))
        current = float(port.get("current_capacity_kwh", 0.0))
        if remaining <= max_remaining_steps and required > current + 1e-6:
            return True
    return False


def _steps_where(raw: RawArtifact, predicate: Callable[[Step], bool]) -> List[Step]:
    return [step for step in _iter_steps(raw) if predicate(step)]


def _action_fraction(steps: List[Step], action_predicate: Callable[[Step], bool]) -> float:
    if not steps:
        return 0.0
    hits = sum(1 for step in steps if action_predicate(step))
    return hits / len(steps)


def _mean_action(steps: List[Step]) -> float:
    values: List[float] = []
    for step in steps:
        values.extend(_actions(step))
    if not values:
        return 0.0
    return sum(values) / len(values)


def _rule_obs_action_fraction(
    raw: RawArtifact,
    *,
    obs_predicate: Callable[[Step], bool],
    action_predicate: Callable[[Step], bool],
    min_fraction: float,
    obs_label: str,
    action_label: str,
) -> Tuple[int, str]:
    matched = _steps_where(raw, obs_predicate)
    if not matched:
        return 0, f"No steps matched obs filter ({obs_label})"
    frac = _action_fraction(matched, action_predicate)
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


def rule_charge_on_low_prices(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        obs_predicate=lambda s: _mean_future_charge_price(_obs(s)) < 0.35,
        action_predicate=lambda s: _mean_action([s]) > 0.25,
        min_fraction=0.40,
        obs_label="mean future charge price < 0.35",
        action_label="mean action > 0.25 (charging)",
    )


def rule_fast_charge_before_departure(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        obs_predicate=lambda s: _urgent_departure_port(_obs(s)),
        action_predicate=lambda s: _mean_action([s]) > 0.50,
        min_fraction=0.50,
        obs_label="connected EV near departure with unmet energy",
        action_label="mean action > 0.50 (strong charging)",
    )


def rule_reduce_power_on_overload(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        obs_predicate=lambda s: _any_transformer_overloaded(_obs(s)),
        action_predicate=lambda s: _mean_action([s]) < 0.20,
        min_fraction=0.35,
        obs_label="any transformer overloaded",
        action_label="mean action < 0.20 (reduced charging)",
    )


def rule_discharge_on_high_prices(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        obs_predicate=lambda s: bool(_obs(s).get("v2g_enabled", False))
        and _mean_future_discharge_price(_obs(s)) > 0.45,
        action_predicate=lambda s: _mean_action([s]) < -0.10,
        min_fraction=0.20,
        obs_label="V2G enabled and mean future discharge price > 0.45",
        action_label="mean action < -0.10 (discharging)",
    )


def rule_idle_without_connected_evs(raw: RawArtifact) -> Tuple[int, str]:
    return _rule_obs_action_fraction(
        raw,
        obs_predicate=lambda s: len(_connected_ports(_obs(s))) == 0,
        action_predicate=lambda s: abs(_mean_action([s])) < 0.05,
        min_fraction=0.80,
        obs_label="no connected EVs",
        action_label="|mean action| < 0.05 (idle)",
    )


def rule_track_power_setpoint(raw: RawArtifact) -> Tuple[int, str]:
    def _setpoint_gap(step: Step) -> float:
        obs = _obs(step)
        usage = float(obs.get("current_power_usage_kw", 0.0))
        setpoint = float(obs.get("power_setpoint_kw", 0.0))
        return abs(usage - setpoint)

    return _rule_obs_action_fraction(
        raw,
        obs_predicate=lambda s: _setpoint_gap(s) > 50.0,
        action_predicate=lambda s: abs(_mean_action([s])) > 0.15,
        min_fraction=0.30,
        obs_label="|power usage - setpoint| > 50 kW",
        action_label="|mean action| > 0.15 (active response)",
    )


RULE_CATALOG = [
    (
        "rule_charge_on_low_prices",
        "On low-price steps (mean future charge price < 0.35), mean charging action > 0.25 "
        "on more than 40% of filtered steps.",
        rule_charge_on_low_prices,
    ),
    (
        "rule_fast_charge_before_departure",
        "On urgent-departure steps, mean charging action > 0.50 on more than 50% of filtered steps.",
        rule_fast_charge_before_departure,
    ),
    (
        "rule_reduce_power_on_overload",
        "On transformer-overload steps, mean action < 0.20 on more than 35% of filtered steps.",
        rule_reduce_power_on_overload,
    ),
    (
        "rule_discharge_on_high_prices",
        "On high discharge-price steps with V2G enabled, mean action < -0.10 on more than "
        "20% of filtered steps.",
        rule_discharge_on_high_prices,
    ),
    (
        "rule_idle_without_connected_evs",
        "On steps with no connected EVs, idle actions (|mean action| < 0.05) on more than "
        "80% of filtered steps.",
        rule_idle_without_connected_evs,
    ),
    (
        "rule_track_power_setpoint",
        "On large setpoint-gap steps (|usage - setpoint| > 50 kW), active actions "
        "(|mean action| > 0.15) on more than 30% of filtered steps.",
        rule_track_power_setpoint,
    ),
]


def get_rule_functions() -> List[RuleFn]:
    return [fn for _name, _desc, fn in RULE_CATALOG]


def get_rule_descriptions() -> List[str]:
    return [desc for _name, desc, _fn in RULE_CATALOG]
# EVOLVE-BLOCK-END
