# Task: EV2Gym Smart Charging

Design a charging policy for a fixed set of upstream-aligned `EV2Gym` workplace simulations.
At each step, output one normalized charging/discharging action per charging port.

## Objective

Maximize the upstream `EV2Gym` `total_reward` across three deterministic cases based on official `V2GProfitPlusLoads.yaml` data and logic.

The benchmark score is the **mean baseline-normalized reward** across cases:

- Official `ChargeAsFastAsPossibleToDesiredCapacity` baseline scores **100**
- Cases with `energy_user_satisfaction <= 1e-3` receive score **0**
- Higher is better (`maximize: true`)

## What You Need to Do

Edit one function in your candidate program:

```python
def solve(case, max_sim_calls=0, simulate_fn=None) -> {"actions": [...]}
```

Goal:

- Maximize the combined benchmark score (target ≥ 100).
- Keep output always valid under the interface contract.

## Inputs exposed to the policy

The policy receives a stepwise `case` dictionary containing:

| Field | Description |
|-------|-------------|
| `case_id` | Fixed evaluation case identifier |
| `current_step` | Current simulation step index |
| `simulation_length` | Total steps in the rollout |
| `remaining_steps` | Steps left including current |
| `timescale_minutes` | Minutes per step |
| `number_of_ports` | Total charging ports |
| `number_of_charging_stations` | Charging station count |
| `number_of_transformers` | Transformer count |
| `scenario` | Upstream scenario name |
| `v2g_enabled` | Whether V2G discharge is allowed |
| `current_power_usage_kw` | Aggregate power usage at this step |
| `power_setpoint_kw` | Aggregate power setpoint at this step |
| `future_charge_prices` | Remaining charge prices (from current step) |
| `future_discharge_prices` | Remaining discharge prices (from current step) |
| `transformers` | List of transformer snapshots (load, overload, solar, etc.) |
| `ports` | List of per-port snapshots (EV state, prices, limits) |

### Per-port fields (when `connected` is true)

- `remaining_steps`, `current_capacity_kwh`, `desired_capacity_kwh`
- `required_energy_kwh`, charge/discharge power limits and efficiencies
- `current_charge_price`, `current_discharge_price`

## Output format

Return either:

```python
{"actions": [...]}
```

or a raw action list with one value per port.
All actions must stay within `[-1, 1]` (negative = discharge when V2G enabled).

## Fixed evaluation cases

| case_id | Stations | Transformers | Seed |
|---------|----------|--------------|------|
| `workplace_winter_48cs_3tr` | 48 | 3 | 17 |
| `workplace_spring_64cs_4tr` | 64 | 4 | 29 |
| `workplace_autumn_96cs_5tr` | 96 | 5 | 43 |

Each case runs 112 steps (15-minute resolution).

## Reference source

- https://github.com/StavrosOrf/EV2Gym

## What success looks like

A good submission:

- delivers sufficient energy before EV departure (avoid zero satisfaction cases)
- exploits low charge prices and high discharge prices when V2G is enabled
- respects transformer overload signals
- beats or matches the official baseline score of 100

## How to submit candidates

Write your code to **`candidate.py`** in the workspace root (overwrite the same file each iteration), then:

```bash
python submit.py candidate.py
```

Do **not** create `candidate_001.py`, `candidate_002.py`, or other numbered scratch files — archived copies live under `archive/attempt_NNNN/code.py`.

This evaluates the program and archives it under `archive/attempt_NNNN/` with:

- `code.py` — your source
- `result.json` — score, validity, feedback, metrics
- `raw-artifact.json` — per-step case snapshots and actions for diagnostic analysis

Read previous attempts in `archive/` before proposing improvements.
