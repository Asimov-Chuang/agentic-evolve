# Diagnostic Rule Discovery — general_meio

## 1. Task

Discover a **fixed-size set of diagnostic rules** that predict MEIO policy scores from per-attempt trajectories recorded in `raw-artifact.json`.

Rules use **policy-visible information**:

- `solution_base_stock` — the base-stock levels returned by `solve()`
- `network` — fixed node IDs and demand statistics
- `scenarios[].aggregate` — cost and fill-rate outcomes per scenario
- `scenarios[].steps[].observations` — per-period inventory, sink demand, and stockout flags

MEIO has no per-step policy actions; `actions` is always `{}`.

The evaluator strips simulator-internal fields, builds a binary feature matrix, fits linear regression against `score`, and returns **`score = -MSE`** (`maximize: true`).

---

## 2. Reference dataset (`workspace/dataset/`)

Symlinked from `source_archive` in config (read-only).

```
dataset/attempt_NNNN/
  result.json           # label: "score"
  raw-artifact.json     # MEIO trace (evaluator passes policy-visible subset to rules)
  code.py               # MEIO policy source (optional context)
```

- Regression uses attempts with both `raw-artifact.json` and `result.json`.
- `attempt_0000` often lacks `raw-artifact.json` → skipped.
- **Do not** bulk-read full `raw-artifact.json` in the agent loop. Use `result.json` for score context only.

### Policy-visible trace

| Field | Description |
|-------|-------------|
| `solution_base_stock` | `{ "10": int, "20": int, "30": int, "40": int, "50": int }` |
| `network.nodes` | `[10, 20, 30, 40, 50]` |
| `network.demand_mean` | `{ "40": 8.0, "50": 7.0 }` |
| `scenarios[i].scenario` | `"nominal"` or `"stress"` |
| `scenarios[i].aggregate` | `cost_per_period`, `fill_rate`, `fill_by_sink`, etc. |
| `steps[j].observations.inventory` | on-hand inventory per node |
| `steps[j].observations.demand` | realized demand at sinks 40/50 |
| `steps[j].observations.stockout` | `1` if sink stockout occurred that period |

**Scale:** 2 scenarios × 160 steps = **320** steps per attempt.

---

## 3. Network context

| Node | Role | Demand mean (nominal) |
|------|------|-----------------------|
| 10 | upstream | — |
| 20 | mid-tier | — |
| 30 | mid-tier | — |
| 40 | sink | 8.0 |
| 50 | sink | 7.0 |

Stress scenario scales demand by `1.2`.

---

## 4. Required rule shape

Each rule is a function:

```python
def rule_example(raw: RawArtifact) -> tuple[int, str]:
    ...
    return binary, explanation
```

- `binary` must be `0` or `1`
- Rules may read `solution_base_stock`, `network`, scenario aggregates, and step observations
- Prefer interpretable thresholds tied to base-stock ratios, fill-rates, and stockout fractions

### Example patterns

**Solution-ratio rule:**

```python
ratio = solution["50"] / network["demand_mean"]["50"]
if ratio < 2.0:
    return 1, "Sink 50 understocked relative to demand"
```

**Scenario-outcome rule:**

```python
if aggregate["nominal"]["fill_rate"] < 0.98:
    return 1, "Nominal service below target"
```

**Step-fraction rule:**

```python
frac = stockout_steps / total_steps  # in stress scenario at sink 50
if frac > 0.10:
    return 1, "Frequent stress stockouts at sink 50"
```

---

## 5. Program contract

Your program must define:

```python
def get_rule_functions() -> list[RuleFn]: ...
def get_rule_descriptions() -> list[str]: ...  # same length as rules
```

Optional: `RULE_CATALOG = [(name, description), ...]`

`rule_set_size` in config must equal `len(get_rule_functions())`.

---

## 6. How to submit

1. Edit your rule program (e.g. `candidate.py`).
2. Ensure exactly `rule_set_size` rules.
3. `python submit.py candidate.py`

Do not modify files under `dataset/`.
