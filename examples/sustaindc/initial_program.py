from __future__ import annotations

from typing import Dict, Mapping, Sequence


# Observation indices for the three agents (see problem.md §6).
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
