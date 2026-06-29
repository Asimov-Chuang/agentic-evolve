from __future__ import annotations

from typing import Dict, Mapping, Sequence


LS = {
    "ci_current": 2,
    "ci_future_mean": 5,
    "queue_oldest_age": 10,
    "queue_fill_ratio": 12,
    "workload_current": 13,
    "queue_hist_over_24h": 25,
}

DC = {
    "ci_current": 2,
    "workload_current": 10,
    "workload_next": 11,
    "outdoor_temp_current_norm": 12,
    "outdoor_temp_next_norm": 13,
}

BAT = {
    "ci_current": 2,
    "ci_future_mean": 5,
    "battery_soc": 12,
}


# EVOLVE-BLOCK-START
def reset_policy() -> None:
    """Reset any internal state between episodes."""


def _act_load_shifting(obs: Sequence[float]) -> int:
    current_ci = obs[LS["ci_current"]]
    future_ci = obs[LS["ci_future_mean"]]
    queue_fill = obs[LS["queue_fill_ratio"]]
    oldest_age = obs[LS["queue_oldest_age"]]
    workload = obs[LS["workload_current"]]
    overdue_share = obs[LS["queue_hist_over_24h"]]

    if overdue_share > 0.0 or oldest_age > 0.75 or queue_fill > 0.80:
        return 2
    if current_ci > future_ci and queue_fill < 0.95 and workload < 0.90:
        return 0
    if current_ci < future_ci - 0.02 and queue_fill > 0.05:
        return 2
    return 1


def decide_actions(observations: Mapping[str, Sequence[float]]) -> Dict[str, int]:
    """Map raw SustainDC observations to discrete actions."""

    return {
        "agent_ls": _act_load_shifting(observations["agent_ls"]),
        "agent_dc": 1,
        "agent_bat": 2,
    }
# EVOLVE-BLOCK-END