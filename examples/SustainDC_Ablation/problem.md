# Task: Hand-Written SustainDC Control

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

Useful intuition:

- High carbon intensity means the grid is dirty now.
- Load shifting can move flexible work away from dirty periods, but excessive deferral causes old queues, overdue tasks, or dropped tasks.
- Cooling less may save energy and water, but can be risky during high outdoor temperature and high workload.
- Charging during low-carbon periods and discharging during high-carbon periods can help, but excessive charging increases grid load and excessive discharge drains SOC.

## Feedback In This Setting

After each submission you receive limited feedback:

- scalar score;
- per-scenario scores when available;
- at most a couple of coarse warnings about dropped/overdue tasks or whether carbon/water failed to improve relative to noop.

You do not receive raw trajectory metrics, action fractions, CI-binned behavior, SOC diagnostics, or detailed per-scenario trajectory tables in this setting.

## Rules

- Only edit `candidate.py`.
- Do not read evaluator, analyzer, runner, registry, submit, checkpoint, workspace metadata, raw artifact, or parent-directory files.
- Use only information provided in this prompt and public submission feedback.
- Return valid integer actions for all three agents on every timestep.