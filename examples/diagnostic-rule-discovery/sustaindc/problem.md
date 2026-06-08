# Diagnostic Rule Discovery

## 1. Task

Discover a **fixed-size set of diagnostic rules** that predict SustainDC policy scores from per-attempt trajectories recorded in `raw-artifact.json`.

Rules must use **only what the SustainDC policy could see at decision time**: per-step **`observations`** and **`actions`**. They must follow the standard **observation-filter + action-fraction** pattern (see §4) so discovered rules can later guide policy evolution.

The evaluator strips simulator-internal fields before calling your rules, builds a binary feature matrix, fits linear regression against `score`, and returns **`score = -MSE`** (`maximize: true`).

---

## 2. Reference dataset (`workspace/dataset/`)

Symlinked from `source_archive` in config (read-only). If `source_archive_top_n` is set, only the top-N scored attempts (with `raw-artifact.json`) appear under `dataset/`; the rest of the source archive is not in the workspace.

```
dataset/attempt_NNNN/
  result.json           # label: "score"
  raw-artifact.json     # step traces (evaluator passes policy-visible subset to rules)
  code.py               # SustainDC policy source (optional context)
```

- Regression uses attempts with both `raw-artifact.json` and `result.json`.
- `attempt_0000` often lacks `raw-artifact.json` → skipped.
- **Do not** bulk-read `raw-artifact.json` in the agent loop (~100k lines each). Use `result.json` for score context only.

### Policy-visible step trace (what rules receive)

Each step in the evaluator has **only**:

| Field | Description |
|-------|-------------|
| `step` | int, 0..191 per scenario |
| `observations` | `{ "agent_ls": float[26], "agent_dc": float[14], "agent_bat": float[13] }` |
| `actions` | `{ "agent_ls": 0\|1\|2, "agent_dc": 0\|1\|2, "agent_bat": 0\|1\|2 }` |

**Forbidden for rules:** `common`, `rewards`, and any other simulator-internal fields. They may exist on disk in the archive but are **removed before** your code runs. Referencing `common` or `rewards` in source code is rejected.

Scenario metadata (`scenarios[i].scenario.name`, etc.) is kept for your convenience but policies do **not** receive scenario IDs at runtime—prefer obs/action patterns that generalize across climates.

**Scale:** 4 scenarios × 192 steps ≈ **768** steps per attempt (rules may scan all or filter per scenario).

---

## 3. SustainDC actions (discrete)

Same as the hand-written SustainDC benchmark (`examples/sustaindc/problem.md`).

### `agent_ls`

| Value | Meaning |
|-------|---------|
| `0` | defer flexible jobs into the queue |
| `1` | keep queue unchanged |
| `2` | execute jobs from the queue |

### `agent_dc`

| Value | Meaning |
|-------|---------|
| `0` | decrease cooling setpoint (more cooling) |
| `1` | keep cooling setpoint unchanged |
| `2` | increase cooling setpoint (less cooling) |

### `agent_bat`

| Value | Meaning |
|-------|---------|
| `0` | charge the battery |
| `1` | discharge the battery |
| `2` | keep the battery idle |

---

## 4. SustainDC observation indices

Normalized floats in `[0, 1]` (unless noted). These are the **same** features passed to `decide_actions(observations)` during simulation.

### `agent_ls` — shape `(26,)`

| Index | Meaning |
|-------|---------|
| 0 | cosine of hour-of-day |
| 1 | sine of hour-of-day |
| 2 | current normalized carbon intensity |
| 3 | slope of near-future carbon intensity |
| 4 | slope of recent past carbon intensity |
| 5 | mean of near-future carbon intensity |
| 6 | std of near-future carbon intensity |
| 7 | current carbon percentile-like feature |
| 8 | normalized time to next carbon peak |
| 9 | normalized time to next carbon valley |
| 10 | oldest queued task age, normalized by 24 hours |
| 11 | average queued task age, normalized by 24 hours |
| 12 | queue fill ratio |
| 13 | current workload level |
| 14 | current normalized outdoor temperature |
| 15 | slope of near-future temperature |
| 16 | mean of near-future temperature |
| 17 | std of near-future temperature |
| 18 | current temperature percentile-like feature |
| 19 | normalized time to next temperature peak |
| 20 | normalized time to next temperature valley |
| 21 | fraction of queued tasks aged 0–6 hours |
| 22 | fraction aged 6–12 hours |
| 23 | fraction aged 12–18 hours |
| 24 | fraction aged 18–24 hours |
| 25 | fraction older than 24 hours |

**Intuition:** high `2` → dirty grid now; high `5` → dirty near future; high `12` / `10` / `25` → queue pressure.

### `agent_dc` — shape `(14,)`

| Index | Meaning |
|-------|---------|
| 0 | cosine of hour-of-day |
| 1 | sine of hour-of-day |
| 2 | current normalized carbon intensity |
| 3 | slope of near-future carbon intensity |
| 4 | slope of recent past carbon intensity |
| 5 | mean of near-future carbon intensity |
| 6 | std of near-future carbon intensity |
| 7 | current carbon percentile-like feature |
| 8 | normalized time to next carbon peak |
| 9 | normalized time to next carbon valley |
| 10 | current workload level |
| 11 | next-step workload level |
| 12 | current normalized outdoor temperature |
| 13 | next-step normalized outdoor temperature |

**Intuition:** high workload + high outdoor temp → cooling pressure; high carbon → avoid unnecessary cooling when safe.

### `agent_bat` — shape `(13,)`

| Index | Meaning |
|-------|---------|
| 0 | cosine of hour-of-day |
| 1 | sine of hour-of-day |
| 2 | current normalized carbon intensity |
| 3 | slope of near-future carbon intensity |
| 4 | slope of recent past carbon intensity |
| 5 | mean of near-future carbon intensity |
| 6 | std of near-future carbon intensity |
| 7 | current carbon percentile-like feature |
| 8 | normalized time to next carbon peak |
| 9 | normalized time to next carbon valley |
| 10 | current workload level |
| 11 | current normalized outdoor temperature |
| 12 | battery state of charge in `[0, 1]` |

**Intuition:** low carbon now + high later → charging may help; high carbon now + sufficient SOC → discharging may help.

---

## 5. Required rule shape (obs + action)

Every rule must be expressible as:

1. **Observation filter:** select steps where `obs_predicate(observations[agent])` is true (optionally also use `step` index or scenario block).
2. **Action fraction:** on filtered steps, compute  
   `fraction = (# steps where actions[agent] == target_action) / (# filtered steps)`.
3. **Binary flag:** return `1` if `fraction > min_fraction` (or `>=`, but be consistent), else `0`.

Use named index constants (see `initial_program.py` `LS`, `DC`, `BAT` dicts)—do not magic-number without documentation.

**Template** (copy and adapt):

```python
def rule_example(raw: RawArtifact) -> tuple[int, str]:
    matched = []
    for step in _iter_steps(raw):
        obs = step["observations"]["agent_ls"]
        if obs[LS["ci_current"]] > 0.6:
            matched.append(step)
    if not matched:
        return 0, "No steps matched obs filter"
    frac = sum(1 for s in matched if s["actions"]["agent_ls"] == 0) / len(matched)
    if frac > 0.25:
        return 1, f"defer fraction {frac:.2%} > 25% on high-CI steps (n={len(matched)})"
    return 0, f"defer fraction {frac:.2%} <= 25% on high-CI steps (n={len(matched)})"
```

You may combine filters (AND/OR) or aggregate per scenario first, but each rule still outputs one bit per attempt.

---

## 6. Program API

```python
def get_rule_descriptions() -> list[str]: ...  # required, same order as functions
def get_rule_functions() -> list[RuleFn]: ...   # exactly rule_set_size entries
```

| Kind | Purpose |
|------|---------|
| **Static** (`get_rule_descriptions`) | Human-readable rule meaning (include obs index + action id + threshold) |
| **Per-attempt** (`return (binary, explanation)`) | Counts/fractions for this attempt |

**Requirements:**

- Exactly `rule_set_size` rules (from `workspace_meta.json`).
- **Obs + action only** — no `common`, no `rewards`, no filesystem reads inside rules.
- `binary` ∈ `{0, 1}`.
- Prefer `RULE_CATALOG = [(name, description, fn), ...]` to keep metadata aligned.

---

## 7. Scoring

OLS on binary features with intercept; **`score = -MSE`**. See `metrics`, `feedback` (includes rule legend), and `regression_summary.json`.

---

## 8. Workflow

1. Read this file (obs tables + rule template) and `archive/` history.
2. Edit candidate inside `# EVOLVE-BLOCK`.
3. `python submit.py candidate.py`
4. Iterate to improve score (lower MSE).

Discovered rules are meant to be read by humans/agents and translated into **policy hints** (e.g. “when CI high, avoid excessive defer”)—keep descriptions actionable.

---

## 9. Performance

Cached policy-visible traces: `archive/_dataset_cache/dataset_cache_policy_visible.pkl`. Keep rules single-pass over steps when possible. `evaluation_timeout_seconds` typically 600.
