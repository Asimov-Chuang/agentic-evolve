# Adaptive Fault-Tolerant Sensor Fusion

Evolve the implementation of `fuse_and_compute_dm_commands` in `initial_program.py`.

The task is robust estimation plus adaptive-optics control. You receive measurements from five wavefront sensor channels, but three channels are severely corrupted on every case. A plain average lets outliers dominate the fused signal. Your goal is to robustly fuse the sensor slopes before computing deformable-mirror commands.

## Function to Edit

```python
def fuse_and_compute_dm_commands(
    slopes_multi,
    reconstructor,
    control_model,
    prev_commands=None,
    max_voltage=0.50,
):
    ...
```

Keep the function name and signature unchanged.

## Inputs

- `slopes_multi`: NumPy array with shape `(n_wfs, 2 * n_subap)`. Each row is one WFS slope vector.
- `reconstructor`: NumPy array with shape `(n_act, 2 * n_subap)`. This maps fused slopes to DM commands.
- `control_model`: dictionary with optional robust-fusion helpers. It may include an anomaly model, `inlier_fraction`, and `score_temperature`.
- `prev_commands`: optional NumPy array with shape `(n_act,)`.
- `max_voltage`: scalar command bound.

## Output Contract

Return a NumPy array with shape `(n_act,)`.

The output must be finite and every command must lie in `[-max_voltage, max_voltage]`. Invalid shape, NaN/Inf, or voltage-bound violations make the attempt invalid.

## Evaluation Scenario

The evaluator uses the Frontier-Engineering Optics benchmark `adaptive_fault_tolerant_fusion`.

For each case:

1. A true phase is generated from random Zernike coefficients.
2. Clean slopes are computed.
3. Five WFS channels are simulated.
4. Three channels are randomly corrupted with gain errors, additive noise, sparse spikes, and partial dropout.
5. Your controller receives only the corrupted multi-sensor slopes.
6. The fused command is converted to a DM surface, then residual RMS and Strehl ratio are measured.

The default evaluation has 320 deterministic cases with seed 53.

## Metrics

The optimization score is `score_0_to_1_higher_is_better` in `[0, 1]`.

Raw metrics:

- `mean_rms`: lower is better.
- `p95_rms`: lower is better.
- `worst_rms`: diagnostic.
- `mean_strehl`: higher is better.

Weighted utility score:

```text
0.45 * U(mean_rms) + 0.35 * U(p95_rms) + 0.20 * U(mean_strehl)
```

Score anchors:

- `mean_rms`: good `0.95`, bad `1.75`.
- `p95_rms`: good `1.20`, bad `2.05`.
- `mean_strehl`: good `0.35`, bad `0.18`.

## Guidance

The baseline averages all channels and is sensitive to outliers. Stronger strategies usually identify reliable channels, downweight extreme sensors, use robust statistics, or use the provided anomaly model when it is present.

Keep the solution deterministic and lightweight. The candidate path should rely on NumPy and provided objects; do not modify evaluator, analyzer, or benchmark files.
