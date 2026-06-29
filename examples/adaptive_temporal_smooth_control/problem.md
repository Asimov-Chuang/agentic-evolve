# Adaptive A2 Specification: Temporal Smooth Control

## Background

This task is a **sequential decision/control** problem.

In each frame you map sensor slopes `s_t` to DM commands `u_t`. Optimizing each frame independently can reduce instantaneous error, but may create high-frequency command jitter. In real hardware this causes:

- actuator wear,
- vibration risk,
- reduced closed-loop stability margin.

So the goal is not only accuracy, but also smooth temporal behavior.

## What You Need to Do

Edit one function in your candidate program:

```python
def compute_dm_commands(slopes, reconstructor, control_model, prev_commands, max_voltage=0.25):
    ...
```

Goal:
- Maximize `score_0_to_1_higher_is_better`.
- Keep output always valid under the interface contract.

### Inputs

- `slopes: np.ndarray`, shape `(2 * n_subap,)`
  - Current delayed/noisy WFS slopes.
- `reconstructor: np.ndarray`, shape `(n_act, 2 * n_subap)`
  - Baseline linear mapping.
- `control_model: dict`
  - Precomputed control matrices and gains:
    - `smooth_reconstructor`
    - `prev_blend`
    - `reconstructor`
    - `delay_prediction_gain`
    - `command_lowpass`
- `prev_commands: np.ndarray`, shape `(n_act,)`
  - Previous applied command (required for temporal strategies).
- `max_voltage: float`
  - Command bound.

### Output

- `dm_commands: np.ndarray`, shape `(n_act,)`
  - Must be finite and bounded in `[-max_voltage, max_voltage]`.

## Verification Scenario

The evaluator simulates a realistic temporal AO process:

1. Modal turbulence evolves stochastically over time.
2. Sensor slopes are delayed and noisy.
3. Actuator has first-order lag.
4. Actuator rate limit is enforced (`ACTUATOR_RATE_LIMIT`).
5. True plant has gain mismatch versus nominal model.

A good controller should avoid overreacting to delayed data and should reduce command slew.

## Metrics and Score (0 to 1, Higher is Better)

Leaderboard target:
- `score_0_to_1_higher_is_better` in `[0, 1]`
- `score_percent = 100 * score_0_to_1_higher_is_better`

Raw metrics:
- `mean_rms` (lower better)
- `mean_slew = mean(|u_t - u_{t-1}|)` (lower better)
- `mean_strehl` (higher better)

Weighted utility score:
- `0.20 * U(mean_rms)`
- `0.65 * U(mean_slew)`
- `0.15 * U(mean_strehl)`

Anchors:
- lower-better:
  - `mean_rms`: good `1.45`, bad `2.10`
  - `mean_slew`: good `0.045`, bad `0.19`
- higher-better:
  - `mean_strehl`: good `0.24`, bad `0.10`

`raw_cost_lower_is_better` is diagnostic only.

## Baseline Implementation

Current baseline:
1. Compute `u = reconstructor @ slopes`
2. Clip to `[-Vmax, Vmax]`

Weakness:
- Ignores `prev_commands`
- Ignores smoothness objective
- Does not compensate delayed sensing

## Oracle / Reference Implementation

The reference controller uses an analytical smooth controller:

- core smooth term from precomputed matrices:
  - `u = smooth_reconstructor @ slopes + prev_blend @ prev_commands`
- delay-aware feed-forward correction using `delay_prediction_gain`
- optional low-pass blending with previous command using `command_lowpass`
- final box projection by clipping

## Practical coding advice

- Use `prev_commands` and the matrices in `control_model` for temporal smoothing.
- Slew rate is 65% of the score weight — reducing command jitter is the main lever.
- Delayed slopes mean aggressive frame-wise correction often hurts both slew and RMS.
- Keep outputs finite and clipped; the simulator also applies actuator lag and rate limits.

## Minimal example

```python
def compute_dm_commands(slopes, reconstructor, control_model, prev_commands, max_voltage=0.25):
    u = reconstructor @ slopes
    return np.clip(u, -max_voltage, max_voltage)
```

This is valid but scores poorly because it ignores temporal smoothness.

## What success looks like

A good submission:

- reduces `mean_slew` toward the reference oracle
- maintains acceptable `mean_rms` and `mean_strehl`
- reaches `score_0_to_1_higher_is_better` well above the frame-wise baseline

## How to submit candidates

Write your code to **`candidate.py`** in the workspace root (overwrite the same file each iteration), then:

```bash
python submit.py candidate.py
```

Do **not** create `candidate_001.py`, `candidate_002.py`, or other numbered scratch files — archived copies live under `archive/attempt_NNNN/code.py`.

This evaluates the program and archives it under `archive/attempt_NNNN/` with:

- `code.py` — your source
- `result.json` — score, validity, feedback, metrics
- `raw-artifact.json` — simulation trajectories for diagnostic analysis

Read previous attempts in `archive/` before proposing improvements.
