# Diagnostic Rule Discovery — PIDTuning

## 1. Task

Discover a **fixed-size set of diagnostic rules** that predict optimizer scores from per-attempt scenario-level traces in `raw-artifact.json`.

Rules use **public evaluation fields**: tuned `gains`, per-scenario `itae` / `inv_itae` / `feasible`, and aggregate `combined_score`. They must **not** rely on simulator-internal state beyond what the evaluator exports.

The evaluator fits linear regression against archive `score` and returns **`score = -MSE`** (`maximize: true`).

---

## 2. Reference dataset (`workspace/dataset/`)

Symlinked from `source_archive` in config (read-only).

```
dataset/attempt_NNNN/
  result.json           # label: "score"
  raw-artifact.json     # scenario-level trace
  code.py               # optimizer source (optional context)
```

### Scenario-level trace

Top-level fields:

| Field | Description |
|-------|-------------|
| `gains` | 12 submitted PID gains |
| `scenarios[]` | Per-scenario `name`, `itae`, `inv_itae`, `feasible`, `duration`, `wind` |
| `gain_bounds` | Allowed gain ranges from `pid_config.json` |
| `constraints` | Pitch / thrust limits |
| `combined_score` | Geometric mean of `1/ITAE` (optimization target) |
| `feasible` | True when score > 0 |

**Scale:** 4 scenarios per attempt.

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

Useful patterns:

- infeasible runs: `feasible == false` or `combined_score == 0`
- wind weakness: `combined_wind inv_itae` much lower than hover/lateral
- hardest scenario: `multi_waypoint` is the minimum `inv_itae`
- imbalance: large max/min ratio across scenario `inv_itae`
- gain shape: very low horizontal gains or very high altitude integral gain

---

## 5. Workflow

1. Read a few `dataset/attempt_*/result.json` files for score context.
2. Edit candidate inside `# EVOLVE-BLOCK`.
3. Submit: `python submit.py candidate.py`
