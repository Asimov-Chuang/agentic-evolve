# Real-Time Adaptive Signal Processing

Design a causal, real-time filter for noisy, non-stationary one-dimensional time series. The goal is to remove noise while preserving real signal dynamics and keeping endpoint lag low.

## Required API

Your program must define:

```python
def run_signal_processing(signal_length=1000, noise_level=0.3, window_size=20):
    """
    Returns:
        dict with at least:
            filtered_signal: 1D array, length = signal_length - window_size + 1
    """
```

Do not change this function name or return format. The evaluator calls it on multiple synthetic test signals.

## Causality Constraint

The output must be causal with fixed latency:

- `filtered_signal[i]` may only depend on recent input samples within the sliding window
- output length must be exactly `signal_length - window_size + 1`
- no future samples outside the current window may be used

## Scoring

Higher is better. The evaluator reports the same metrics as the OpenEvolve example:

- `overall_score` — primary selection metric (also exposed as `score`)
- `composite_score`
- `slope_changes`, `lag_error`, `avg_error`, `false_reversals`
- `correlation`, `noise_reduction`
- `smoothness_score`, `responsiveness_score`, `accuracy_score`, `efficiency_score`
- `execution_time`, `success_rate`

`feedback` uses the same metric list formatting as OpenEvolve prompts:

```text
- composite_score: 0.4308
- overall_score: 0.5016
...
```

## How to Submit Candidates

Write your code to a file such as `candidate.py`, then run:

```bash
python submit.py candidate.py
```

Each submission is archived under `archive/attempt_NNNN/` with `code.py` and `result.json`.

Read previous attempts before proposing improvements.

## Useful Directions

Try adaptive moving averages, robust outlier handling, low-lag smoothing, trend detection, local polynomial fits, Kalman-style state estimates, multi-scale filters, or hybrid approaches.
