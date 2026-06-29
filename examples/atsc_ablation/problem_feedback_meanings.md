# Adaptive Temporal Smooth Control

You are optimizing a controller for a sequential adaptive-optics task.

In every frame, map delayed/noisy wavefront sensor slopes to deformable-mirror commands. A controller that optimizes each frame independently may reduce instantaneous error but create high-frequency command jitter, which hurts actuator health and closed-loop stability.

## Task

Edit exactly this function in `candidate.py`:

```python
def compute_dm_commands(slopes, reconstructor, control_model, prev_commands, max_voltage=0.25):
    ...
```

Return a finite NumPy array with shape `(n_act,)`, clipped to `[-max_voltage, max_voltage]`.

## Inputs

- `slopes`: current delayed/noisy WFS slopes, shape `(2 * n_subap,)`.
- `reconstructor`: baseline linear mapping, shape `(n_act, 2 * n_subap)`.
- `control_model`: dictionary with precomputed control matrices and gains.
- `prev_commands`: previous applied DM command, shape `(n_act,)`.
- `max_voltage`: scalar command limit.

Useful `control_model` entries include:

- `smooth_reconstructor`: matrix with shape `(n_act, 2 * n_subap)`. Use it like `smooth_reconstructor @ slopes`.
- `prev_blend`: matrix with shape `(n_act, n_act)`. Use matrix multiplication: `prev_blend @ prev_commands`. Do not use elementwise `prev_blend * prev_commands`, because that broadcasts to `(n_act, n_act)`.
- `reconstructor`: optional feed-forward matrix with shape `(n_act, 2 * n_subap)`.
- `delay_prediction_gain`: scalar gain.
- `command_lowpass`: scalar blend coefficient.

## Objective

Maximize the reported score. The verifier simulates stochastic temporal turbulence, delayed/noisy sensing, actuator lag, actuator rate limits, and plant mismatch.

A strong controller usually uses `prev_commands` and the smooth matrices instead of only doing a frame-wise `reconstructor @ slopes` projection.

Shape-safe smooth-control pattern:

```python
smooth = control_model.get("smooth_reconstructor", reconstructor)
prev_blend = control_model.get("prev_blend")
u = smooth @ slopes
if prev_blend is not None:
    u = u + prev_blend @ prev_commands
u = np.asarray(u, dtype=float).reshape(-1)
return np.clip(u, -max_voltage, max_voltage)
```

Never return a matrix. The returned value must have exactly the same one-dimensional shape as `prev_commands`.

## Feedback Meaning Guide

The analyzer may report raw trajectory diagnostics in addition to score. These metrics are computed from hidden simulation trajectories.

- `mean_rms`: average residual wavefront RMS. Lower is better.
- `mean_slew`: average command change magnitude. Lower is better and is the dominant score component.
- `mean_strehl`: average Strehl-like optical quality. Higher is better.
- `u_mean_rms`, `u_mean_slew`, `u_strehl`: normalized utility terms used by the weighted score.
- `trajectory_mean_cmd_norm`, `trajectory_p95_cmd_norm`, `trajectory_std_cmd_norm`: command amplitude level and spikes.
- `trajectory_mean_step_slew`, `trajectory_p95_step_slew`: raw frame-to-frame command changes.
- `trajectory_cmd_norm_oscillation`, `cmd_norm_autocorr_lag1`: whether command magnitudes jitter or change too slowly.
- `actuator_mean_slew_*`, `actuator_p95_slew_max`, `actuator_frac_high_slew`: per-actuator jitter distribution.
- `actuator_sign_flip_rate`: how often actuators flip polarity between frames.
- `clipping_fraction`, `clipping_mean_per_step`, `voltage_utilization`, `peak_voltage_utilization`: saturation and voltage budget usage.
- `slew_rms_correlation`, `slew_rms_ratio`: whether reducing slew is likely to also improve or hurt RMS.
- `rms_start`, `rms_end`, `rms_mean`, `rms_std`, `rms_settling_improvement`: residual error evolution and stability.
- `strehl_start`, `strehl_end`, `strehl_mean`: optical quality evolution.

Use these signals to distinguish over-aggressive, under-actuated, over-smoothed, oscillatory, or saturated controllers.

## Starting Baseline

The initial implementation computes:

```python
u = reconstructor @ slopes
return np.clip(u, -max_voltage, max_voltage)
```

This is valid but ignores temporal smoothness.

## Submission

Write your candidate to `candidate.py`, then run:

```bash
python submit.py candidate.py
```

Read previous attempts in `archive/` before changing the controller. Do not create numbered candidate files.