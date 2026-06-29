# Diagnostic Rule Discovery — HighReliableSimulation

## 1. Task

Discover a **fixed-size set of diagnostic rules** that predict sampler scores from per-attempt repeat-level traces in `raw-artifact.json`.

Rules use **public evaluation traces**: `dev_constants`, per-repeat statistics, and aggregate metrics. They must **not** rely on simulator-internal failure blobs such as `traceback`.

The evaluator fits linear regression against archive `score` and returns **`score = -MSE`** (`maximize: true`).

---

## 2. Reference dataset (`workspace/dataset/`)

Symlinked from `source_archive` in config (read-only).

```
dataset/attempt_NNNN/
  result.json           # label: "score"
  raw-artifact.json     # repeat-level traces
  code.py               # sampler source (optional context)
```

- Regression uses attempts with both `raw-artifact.json` and `result.json`.
- **Do not** bulk-read full archives in the agent loop; use `result.json` for score context only.

### Repeat-level trace

Top-level fields:

| Field | Description |
|-------|-------------|
| `dev_constants` | Frozen evaluation constants (`sigma`, `target_std`, `epsilon`, `r0_dev`, `t0_dev`, `repeats`) |
| `repeats[]` | One block per evaluation repeat |
| `aggregate` | Median/aggregate metrics (`combined_score`, `valid`, `runtime_s`, `error_log_ratio`, ...) |
| `combined_score` | Optimization target label mirror |

Each repeat block:

| Field | Description |
|-------|-------------|
| `repeat`, `seed` | Repeat index / seed |
| `runtime_s` | Wall-clock runtime for canonical simulation |
| `err_rate_log` | Log BER estimate from trusted loop |
| `err_ratio` | Error-event fraction |
| `actual_samples` | Samples consumed |
| `actual_std` | Achieved variance |
| `converged` | 1 if converged, else 0 |

**Scale:** 3 repeats per attempt.

---

## 3. Required program interface

```python
def get_rule_functions() -> list[RuleFn]:
    ...

def get_rule_descriptions() -> list[str]:
    ...
```

- `len(get_rule_functions())` must equal `rule_set_size` in config (6).
- Return `(1, explanation)` when the negative pattern is present, `(0, explanation)` otherwise.

---

## 4. Rule design patterns

Useful patterns for this task:

- invalid runs: `aggregate.valid == 0`
- variance failure: any repeat with `actual_std > dev_constants.target_std`
- accuracy failure: `aggregate.error_log_ratio >= dev_constants.epsilon`
- runtime issues: repeat `runtime_s` much larger than aggregate median
- convergence issues: low `aggregate.converged_rate`

---

## 5. How to submit

Write rules to **`candidate.py`**, then:

```bash
python submit.py candidate.py
```
