# Diagnostic Rule Discovery — Adaptive Temporal Smooth Control

## 1. Task

Discover a **fixed-size set of mode detectors** (`rule_set_size = 8`) that predict AO controller scores from per-attempt trajectories in `raw-artifact.json`.

Each **rule** is an attempt-level **mode detector**: scan the full trajectory (across episodes/steps) for a named **failure mode** or **success signature**. If the pattern is **present** → return `1`; if **absent** → return `0`.

Rules may use any deterministic logic over policy-visible trajectories — sliding windows, consecutive-step runs, episode aggregates, cross-episode consistency, regime transitions, etc. They are **not** required to follow obs-filter + action-fraction templates.

The evaluator strips simulator-internal fields, builds a binary feature matrix, fits linear regression against `score`, and returns **`score = -MSE`** (`maximize: true`).

**Goal:** Find **structural behavioral modes** that explain score variance and can be translated into controller design hints — not mere restatements of `mean_slew`, `mean_rms`, or `mean_strehl`.

---

## 2. Reference dataset (`workspace/dataset/`)

Symlinked from `source_archive` in config (read-only). If `source_top_n` is set, only the top-N scored attempts (with `raw-artifact.json`) appear under `dataset/`.

```
dataset/attempt_NNNN/
  result.json           # label: "score"
  raw-artifact.json     # episode/step traces (evaluator passes policy-visible subset to rules)
  code.py               # controller source (optional context)
```

- Regression uses attempts with both `raw-artifact.json` and `result.json`.
- **Do not** bulk-read full `raw-artifact.json` in the agent loop (~100k lines each). Use `result.json` for score context only.

### Policy-visible step trace (what rules receive)

Each step has **only**:

| Field | Description |
|-------|-------------|
| `step` | int, frame index within episode |
| `observations.slopes` | delayed/noisy WFS slopes, shape `(2 * n_subap,)` |
| `observations.prev_commands` | previous applied DM commands, shape `(n_act,)` |
| `actions.cmd` | controller output before simulator rate limiting, shape `(n_act,)` |

Episode metadata (`scenarios[i].episode`) is available. Prefer modes that **generalize across episodes**, not one-episode noise.

**Forbidden for rules:** `diagnostics`, `baseline`, `reference`, `score_0_to_1_higher_is_better`, episode `aggregate`, and any other simulator-internal fields. Referencing forbidden names in source code is rejected.

**Scale:** 36 episodes × 70 steps ≈ **2520** steps per attempt.

---

## 3. Trajectory inputs (policy-visible)

The controller sees `slopes`, `prev_commands`, and outputs `cmd`. Mode detectors may derive per-step features, e.g.:

- slope regime: `mean(abs(slopes))`, `max(abs(slopes))`, `l2_norm(slopes)`
- correction strength: `||cmd||`, `||cmd|| / mean(abs(slopes))`
- alignment: `cosine(cmd, slopes)`
- magnitude ratios: `||cmd|| / ||prev||` (allowed; not the same as `cmd - prev` slew)

Use these as **building blocks inside mode logic**, not as standalone “fraction > 30%” rules unless the **mode** is inherently sequential or structural.

---

## 4. Mode detection rule shape

Each rule implements **one named mode**:

```python
def rule_some_mode(raw: RawArtifact) -> tuple[int, str]:
    """Return (1, explanation) if mode PRESENT on this attempt, else (0, explanation)."""
    ...
```

### 4.1 What counts as a good mode

| Good mode type | Example |
|----------------|---------|
| **Failure mode** | Sustained under-correction burst (≥5 consecutive large-slope steps with low `‖cmd‖`) |
| **Failure mode** | Regime-transition lag (after calm→active, response stays weak for several steps) |
| **Failure mode** | Late-episode collapse (`‖cmd‖` drops in final segment vs opening segment) |
| **Failure mode** | Cross-episode inconsistency (active-step response varies widely across episodes) |
| **Success signature** | Stable response scaling across episodes in the same slope regime |

Modes should be **named**, **deterministic**, and **explainable** in one sentence.

### 4.2 Forbidden modes (utility proxies)

Do **not** define a mode whose entire definition is a thin proxy for the primary score components:

| Banned | Why |
|--------|-----|
| “High mean `‖cmd−prev‖`” or rate-limit-hit fraction as the whole mode | Restates `mean_slew` |
| “Low cmd–prev cosine” as the whole mode | Temporal smoothness proxy |
| Single-step fraction rules with no structural/sequential logic | Equivalent to old obs+action template; not mode detection |

Allowed: modes that **use** cmd/slope features inside richer logic (runs, transitions, episode comparisons).

### 4.3 Template

```python
def rule_sustained_under_correction_burst(raw: RawArtifact) -> tuple[int, str]:
  """Failure mode: >=5 consecutive large-slope steps with ||cmd|| below threshold."""
  min_run, slope_thr, cmd_thr = 5, 0.18, 0.04
  for block in raw.get("scenarios", []):
    run = 0
    for step in block.get("steps", []):
      slopes = np.asarray(step["observations"].get("slopes") or [], dtype=np.float64)
      cmd = np.asarray(step["actions"].get("cmd") or [], dtype=np.float64)
      active = slopes.size and float(np.mean(np.abs(slopes))) > slope_thr
      weak = cmd.size and float(np.linalg.norm(cmd)) < cmd_thr
      if active and weak:
        run += 1
        if run >= min_run:
          return 1, f"Under-correction burst (run>={min_run}) in episode {block.get('episode')}"
      else:
        run = 0
  return 0, "No sustained under-correction burst"
```

---

## 5. Program API

```python
def get_rule_descriptions() -> list[str]: ...  # required, same order as functions
def get_rule_functions() -> list[RuleFn]: ...   # exactly rule_set_size entries
```

| Kind | Purpose |
|------|---------|
| **Static** (`get_rule_descriptions`) | Mode name + when it fires (failure vs success signature) |
| **Per-attempt** (`return (binary, explanation)`) | `1` = mode present, `0` = absent |

**Requirements:**

- Exactly **`rule_set_size = 8`** rules.
- Policy-visible fields only (see §2).
- No forbidden utility-proxy modes (§4.2).
- `binary` ∈ `{0, 1}`.
- Prefer `RULE_CATALOG = [(name, description, fn), ...]`.

---

## 6. Scoring

OLS on binary features with intercept; **`score = -MSE`**. See `metrics`, `feedback`, and `regression_summary.json`.

---

## 7. Workflow

1. Read this file and `archive/` history.
2. Edit candidate inside `# EVOLVE-BLOCK`.
3. `python submit.py candidate.py`
4. Iterate to improve regression score (lower MSE).

Discovered modes are injected back into the primary evolution task as **actionable design hints** (avoid failure mode X / reinforce success signature Y).

---

## 8. Performance

Cached policy-visible traces: `archive/_dataset_cache/dataset_cache_policy_visible.pkl`. Prefer single-pass scans where possible. `evaluation_timeout_seconds` typically 600.
