# Mechanism Discovery — Adaptive Temporal Smooth Control

## 1. Task

Discover a **mechanism model** that explains how optimizer **code patterns** and **policy-visible trajectories** relate to evaluation **metrics** and **score**.

You evolve three artifacts inside `# EVOLVE-BLOCK`:

1. **Code predicates** — binary detectors over `code.py` strings
2. **Trace predicates** — binary detectors over policy-visible `raw-artifact.json`
3. **Mechanism links** — typed edges connecting code → trace → metrics

The evaluator loads attempts from `workspace/dataset/` (symlinked archive). Each sample has:

```text
dataset/attempt_NNNN/
  code.py
  raw-artifact.json
  result.json
```

**Do not** bulk-read full `raw-artifact.json` files in the agent loop. Use `result.json` for score context; predicates run inside the evaluator on cached traces.

---

## 2. Program API

```python
from mechanism_types import MechanismLink

def get_code_predicates() -> list: ...
def get_code_predicate_descriptions() -> list[str]: ...
def get_trace_predicates() -> list: ...
def get_trace_predicate_descriptions() -> list[str]: ...
def get_mechanism_links() -> list[MechanismLink]: ...
```

Each predicate returns `(binary, explanation)` with `binary ∈ {0, 1}`.

### Link schema (v1)

| Field | Values |
|-------|--------|
| `source_kind` | `code`, `trace` |
| `target_kind` | `trace`, `metric` |
| `effect` | `increase`, `decrease` |

Allowed edges:

- `code -> trace` — implementation causes / suppresses a trajectory mode
- `trace -> metric` — trajectory mode pushes a metric up or down

Metric targets must be one of:

`mean_slew`, `mean_rms`, `mean_strehl`, `score`, `u_mean_slew`, `u_mean_rms`, `u_strehl`

---

## 3. Policy-visible trace (trace predicates)

Each step contains only:

| Field | Content |
|-------|---------|
| `step` | int |
| `observations.slopes` | slope vector |
| `actions.cmd` | DM command vector |

Forbidden: simulator-internal reward/diagnostic fields.

Helpers like `_mean_slope_mag`, `_cmd_norm`, `_response_ratio` are fine inside predicates.

---

## 4. Code predicates

Analyze only the candidate **code string** (EVOLVE block). Use helpers from `code_rule_utils.py`.

Examples: `prev_commands`, `smooth_reconstructor`, tanh delta limiting, blend weights.

---

## 5. Scoring

Default objective (**no score prediction term**):

```text
score = 0.625 * link_consistency + 0.375 * path_coherence - penalty
```

### Link consistency

For each link, compare groups with `source=1` vs `source=0`:

- `code -> trace`: Δ = P(trace=1|code=1) - P(trace=1|code=0)
- `trace -> metric`: normalized Δ in metric value

Link scores +1 when observed Δ matches declared `effect` (increase/decrease) with sufficient support (`min_support=3` per group).

### Path coherence

For each chain `code -> trace -> metric`, both links should score ≥ 0.5.

### Penalties

- Degenerate predicates (trigger rate < 5% or > 95%)
- Too many predicates/links (hard limits in config)
- Invalid references (unknown predicate / metric id)

Optional (off by default): set `enable_predictive_r2: true` in config to add a joint OLS R² term on score.

---

## 6. Workflow

1. Read this file and inspect `archive/` / `result.json` summaries.
2. Edit predicates and links in `# EVOLVE-BLOCK`.
3. `python submit.py candidate.py`
4. Read feedback link/path breakdown and iterate.

Goal: a **sparse, coherent mechanism model** — not just high correlation, but interpretable `code -> trace -> metric` paths supported by the archive.

---

## 7. Limits (from config)

- `max_code_predicates`: 6
- `max_trace_predicates`: 8
- `max_links`: 12

Keep models parsimonious; prefer a few strong paths over many weak links.
