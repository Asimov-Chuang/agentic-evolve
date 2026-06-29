# Diagnostic Rule Discovery — EV2Gym Smart Charging

## 1. Task

Discover a **fixed-size set of diagnostic rules** that predict EV charging policy scores from per-attempt trajectories recorded in `raw-artifact.json`.

Rules must use **only what the policy could see at decision time**: per-step **`observations`** (the `case` dictionary) and **`actions`**. They must follow the standard **observation-filter + action-behavior fraction** pattern (see §5) so discovered rules can later guide policy evolution.

The evaluator strips simulator-internal and post-hoc aggregate fields before calling your rules, builds a binary feature matrix, fits linear regression against `score`, and returns **`score = -MSE`** (`maximize: true`).

---

## 2. Reference dataset (`workspace/dataset/`)

Symlinked from `source_archive` in config (read-only). If `source_top_n` is set, only the top-N scored attempts (with `raw-artifact.json`) appear under `dataset/`.

```
dataset/attempt_NNNN/
  result.json           # label: "score"
  raw-artifact.json     # case/step traces (evaluator passes policy-visible subset to rules)
  code.py               # policy source (optional context)
```

- Regression uses attempts with both `raw-artifact.json` and `result.json`.
- **Do not** bulk-read full `raw-artifact.json` in the agent loop (each can be very large). Use `result.json` for score context only.

### Policy-visible step trace (what rules receive)

Each step in the evaluator has **only**:

| Field | Description |
|-------|-------------|
| `step` | int, simulation step index within case |
| `observations` | Full `case` dict passed to `solve()` at that step |
| `actions` | `{"actions": [float, ...]}` — one normalized action per port in `[-1, 1]` |

Case metadata (`scenarios[i].case_id`, `seed`) is kept for convenience but policies do **not** receive case IDs at runtime—prefer obs/action patterns that generalize across cases.

**Forbidden for rules:** `score`, `mean_energy_user_satisfaction`, post-hoc `stats`, and any other simulator-internal fields. They may exist on disk in the archive but are **removed before** your code runs.

**Scale:** 3 cases × 112 steps ≈ **336** steps per attempt (rules may scan all or filter per case).

---

## 3. Policy-visible observations and actions

The policy receives the `case` dict each step and outputs per-port actions. Rules read the same fields from `observations` and `actions`.

### Key `observations` fields

| Field | Use in rules |
|-------|--------------|
| `future_charge_prices` | Price arbitrage — charge when low |
| `future_discharge_prices` | V2G discharge when high |
| `v2g_enabled` | Whether negative actions are meaningful |
| `power_setpoint_kw`, `current_power_usage_kw` | Aggregate load tracking |
| `transformers[].is_overloaded` | Grid constraint signals |
| `ports[].connected` | Whether a port has an EV |
| `ports[].remaining_steps` | Departure urgency |
| `ports[].required_energy_kwh`, `current_capacity_kwh` | Service gap |

### `actions.actions`

- Normalized per-port charging/discharging commands in `[-1, 1]`.
- Useful derived features: `mean(actions)`, fraction with `action > 0.5`, fraction with `action < -0.1`.

---

## 4. Required rule shape (obs + action behavior)

Every rule must be expressible as:

1. **Observation filter:** select steps where `obs_predicate(observations, step)` is true.
2. **Action-behavior fraction:** on filtered steps, compute the fraction where `action_predicate(actions, step)` is true.

Return `(1, explanation)` if fraction > threshold, else `(0, explanation)`.

**Do not** use trivial filters matching every step. Each rule must condition on price, departure urgency, overload, setpoint gap, or connection state.

---

## 5. Implementation contract

Edit `initial_program.py` inside the `EVOLVE-BLOCK`:

- `get_rule_functions()` — list of callables `rule(raw_artifact) -> (int, str)`
- `get_rule_descriptions()` — human-readable descriptions (same order)

`rule_set_size` in config **must equal** `len(get_rule_functions())` (currently **6**).

Seed rules cover: low-price charging, departure urgency, overload reduction, high-price V2G discharge, idle without EVs, setpoint tracking.

---

## 6. Scoring

- Label: `result.json` → `"score"` (mean baseline-normalized EV2Gym score, higher is better).
- Feature matrix: binary outputs of each rule on each attempt's policy-visible trace.
- Evaluator score: **negative MSE** of linear regression (`maximize: true`).

Improve rules to better predict which attempts score high vs low.
