# HighReliableSimulation Task

## Objective

Estimate BER for Hamming(127,120) over AWGN in a rare-event regime.
You must implement `MySampler` and support variance-controlled simulation.

## Submission Contract

Submit one Python file that defines:

1. `class MySampler(SamplerBase)`
2. `MySampler.simulate_variance_controlled(...)` for local compatibility

Official scoring uses the benchmark-owned canonical simulation loop:

```python
sampler = MySampler(code=code, seed=seed)
result = code.simulate_variance_controlled(
    noise_std=DEV_SIGMA,
    target_std=TARGET_STD,
    max_samples=MAX_SAMPLES,
    sampler=sampler,
    batch_size=BATCH_SIZE,
    fix_tx=True,
    min_errors=MIN_ERRORS,
)
```

`code` is fixed by evaluator as `HammingCode(r=7, decoder="binary")` with `ChaseDecoder(t=3)`.
Official scoring does **not** trust self-reported aggregate statistics from candidate wrappers.

## Return Format

`MySampler.simulate_variance_controlled(...)` may still return:

- Tuple/list with at least 6 fields:
  `(errors_log, weights_log, err_ratio, total_samples, actual_std, converged)`
- Dict with equivalent keys.

However, official scoring recomputes aggregates through the canonical benchmark loop above.

## Frozen Evaluation Constants

- `sigma = 0.268`
- `target_std = 0.05`
- `max_samples = 100000`
- `batch_size = 10000`
- `min_errors = 20`
- `r0 = 7.261287772505011e-07`
- `t0 = 10.4001037335396`
- `epsilon = 0.8`
- `repeats = 3`

## Scoring

- `e = |log(r / r0)|`, where `r = exp(err_rate_log)`.
- Let `s` be the median `actual_std` across repeats.
- If `e >= epsilon` or `s > target_std`, the run is invalid and receives `-1e18`.
- Otherwise: `score = t0 / (t * e + 1e-6)`, where `t` is median runtime.

Higher `combined_score` is better.

## Practical coding advice

- Implement `sample(...)` efficiently; runtime directly affects score when valid.
- Keep variance under `target_std=0.05` across all repeats.
- Keep `err_rate_log` close to `log(r0)`; large BER drift invalidates the run.
- Reuse cached designs where possible; antithetic / mixture samplers are common baselines.
- Import runtime types from Frontier via `FRONTIER_ENGINEERING_ROOT` on `sys.path`.

## Minimal skeleton

```python
class MySampler(SamplerBase):
    def __init__(self, code, *, seed=0):
        super().__init__(code, seed=seed)
        ...

    def sample(self, noise_std, tx_bin, batch_size, **kwargs):
        ...

    def simulate_variance_controlled(self, *, code, sigma=0.3, target_std=0.08, ...):
        return code.simulate_variance_controlled(...)
```

## What success looks like

A good submission:

- passes validity (`valid=1`)
- keeps median `actual_std <= 0.05`
- keeps `error_log_ratio < 0.8`
- achieves high `combined_score` via accurate BER estimation and low runtime

## How to submit candidates

Write your code to **`candidate.py`** in the workspace root (overwrite the same file each iteration), then:

```bash
python submit.py candidate.py
```

Do **not** create numbered scratch files — archived copies live under `archive/attempt_NNNN/code.py`.

This evaluates the program and archives it under `archive/attempt_NNNN/` with:

- `code.py` — your source
- `result.json` — score, validity, feedback, metrics
- `raw-artifact.json` — repeat-level evaluation traces for diagnostic analysis

Read previous attempts in `archive/` before proposing improvements.
