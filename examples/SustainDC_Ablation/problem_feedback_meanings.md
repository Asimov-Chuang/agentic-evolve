# Task: Hand-Written SustainDC Control With Meaningful Trajectory Feedback

Write a deterministic hand-written controller for the original SustainDC environment. Your policy controls three coupled agents every 15 minutes:

- `agent_ls`: load shifting
- `agent_dc`: data center cooling
- `agent_bat`: battery charging/discharging

Edit `candidate.py`. The required entry point is:

```python
def decide_actions(observations) -> dict:
    ...
```

Optional:

```python
def reset_policy() -> None:
    ...
```

If you keep memory across timesteps, store it in module-level variables and reset it in `reset_policy()`.

## Objective

Maximize the benchmark score by reducing carbon emissions and water usage relative to the fixed noop controller while avoiding dropped or overdue tasks. The noop reference uses:

- `agent_ls = 1`
- `agent_dc = 1`
- `agent_bat = 2`

The evaluation uses fixed hidden SustainDC scenarios including Arizona summer, California spring, New York winter, and Texas late summer.

## Actions

`agent_ls`:

- `0`: defer flexible jobs into the queue
- `1`: keep the queue unchanged
- `2`: execute jobs from the queue

`agent_dc`:

- `0`: decrease cooling setpoint, meaning more cooling
- `1`: keep cooling unchanged
- `2`: increase cooling setpoint, meaning less cooling

`agent_bat`:

- `0`: charge the battery
- `1`: discharge the battery
- `2`: keep the battery idle

## Observations

`observations` is a dictionary with three vectors:

```python
{
    "agent_ls": vector of length 26,
    "agent_dc": vector of length 14,
    "agent_bat": vector of length 13,
}
```

`agent_ls` indices:

| Index | Meaning |
|---|---|
| 0 | cosine of hour-of-day |
| 1 | sine of hour-of-day |
| 2 | current normalized carbon intensity |
| 3 | slope of near-future carbon intensity |
| 4 | slope of recent past carbon intensity |
| 5 | mean of near-future carbon intensity |
| 6 | std of near-future carbon intensity |
| 7 | current carbon percentile-like feature |
| 8 | normalized time to next carbon peak |
| 9 | normalized time to next carbon valley |
| 10 | oldest queued task age, normalized by 24 hours |
| 11 | average queued task age, normalized by 24 hours |
| 12 | queue fill ratio |
| 13 | current workload level |
| 14 | current normalized outdoor temperature |
| 15 | slope of near-future temperature |
| 16 | mean of near-future temperature |
| 17 | std of near-future temperature |
| 18 | current temperature percentile-like feature |
| 19 | normalized time to next temperature peak |
| 20 | normalized time to next temperature valley |
| 21 | fraction of queued tasks aged 0-6 hours |
| 22 | fraction of queued tasks aged 6-12 hours |
| 23 | fraction of queued tasks aged 12-18 hours |
| 24 | fraction of queued tasks aged 18-24 hours |
| 25 | fraction of queued tasks older than 24 hours |

`agent_dc` indices:

| Index | Meaning |
|---|---|
| 0 | cosine of hour-of-day |
| 1 | sine of hour-of-day |
| 2 | current normalized carbon intensity |
| 3 | slope of near-future carbon intensity |
| 4 | slope of recent past carbon intensity |
| 5 | mean of near-future carbon intensity |
| 6 | std of near-future carbon intensity |
| 7 | current carbon percentile-like feature |
| 8 | normalized time to next carbon peak |
| 9 | normalized time to next carbon valley |
| 10 | current workload level |
| 11 | next-step workload level |
| 12 | current normalized outdoor temperature |
| 13 | next-step normalized outdoor temperature |

`agent_bat` indices:

| Index | Meaning |
|---|---|
| 0 | cosine of hour-of-day |
| 1 | sine of hour-of-day |
| 2 | current normalized carbon intensity |
| 3 | slope of near-future carbon intensity |
| 4 | slope of recent past carbon intensity |
| 5 | mean of near-future carbon intensity |
| 6 | std of near-future carbon intensity |
| 7 | current carbon percentile-like feature |
| 8 | normalized time to next carbon peak |
| 9 | normalized time to next carbon valley |
| 10 | current workload level |
| 11 | current normalized outdoor temperature |
| 12 | battery state of charge in `[0, 1]` |

## Meaningful Feedback

After each valid submission you receive score, scenario scores, scenario carbon/water/safety breakdowns, and trajectory diagnostics extracted from hidden simulator artifacts. These metrics are descriptive feedback for improving your policy; they are not extra inputs available at runtime.

Scenario names:

- `az_july`: hot Arizona summer
- `ca_april`: milder California spring
- `ny_january`: cold New York winter
- `tx_august`: hot Texas late summer

Report-derived metrics:

- `scenario_scores`: score per scenario; low scenarios identify where policy fails.
- `carbon_gain`: improvement over noop carbon for that scenario; higher is better.
- `water_gain`: improvement over noop water for that scenario; higher is better.
- `safety_penalty`: penalty from dropped or overdue tasks; lower is better.

Global action fractions:

- `ls_defer_fraction`, `ls_keep_fraction`, `ls_execute_fraction`: how often load shifting defers, keeps, or executes queued work.
- `dc_more_cooling_fraction`, `dc_keep_fraction`, `dc_less_cooling_fraction`: how often cooling asks for more, same, or less cooling.
- `bat_charge_fraction`, `bat_discharge_fraction`, `bat_idle_fraction`: how often battery charges, discharges, or idles.

State summaries:

- `avg_ci` and `avg_norm_ci`: average carbon intensity exposure.
- `avg_queue_fill`, `avg_oldest_age`, `avg_overdue_frac`: queue pressure and task risk.
- `avg_workload`, `avg_temp`: workload and outdoor-temperature pressure.
- `avg_soc`, `min_soc`, `max_soc`, `soc_above_20_pct`, `soc_above_50_pct`: battery state-of-charge behavior.

Carbon-intensity conditioned behavior:

- `ls_defer_fraction_high_ci` vs `ls_defer_fraction_low_ci`: deferral should generally be more common when carbon intensity is high, unless the queue is risky.
- `ls_execute_fraction_high_ci` vs `ls_execute_fraction_low_ci`: executing flexible work during high carbon can hurt carbon unless queue pressure demands it.
- `bat_charge_fraction_under_low_ci` and `bat_charge_fraction_low_ci`: charging should be concentrated in cleaner low-CI periods.
- `bat_discharge_fraction_under_high_ci` and `bat_discharge_fraction_high_ci`: discharging should be concentrated in dirty high-CI periods when SOC is available.

Cooling and temperature conditioned behavior:

- `dc_less_fraction_high_ci`: relaxing cooling during high CI can save carbon if temperatures and workload allow it.
- `dc_more_fraction_high_temp`: more cooling during high outdoor temperature may avoid unsafe or inefficient thermal behavior.
- `dc_less_fraction_high_temp`: too much less-cooling during hot periods can be risky.

Battery/SOC conditioned behavior:

- `bat_discharge_when_soc_avail`: discharge frequency when SOC is available.
- `bat_discharge_when_soc_high`: discharge frequency when SOC is high.
- `bat_charge_when_soc_low`: charge frequency when there is room to charge.

Per-scenario trajectory tables repeat the most useful action, CI, queue, temperature, and SOC metrics for each hidden scenario. Use them to specialize rules for hot vs mild vs cold scenarios without overfitting to one case.

## Rules

- Only edit `candidate.py`.
- Do not read evaluator, analyzer, runner, registry, submit, checkpoint, workspace metadata, raw artifact, or parent-directory files.
- Use only information provided in this prompt and public submission feedback.
- Return valid integer actions for all three agents on every timestep.