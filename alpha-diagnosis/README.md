# alpha-diagnosis

Automated **diagnostic rule discovery → rule-guided evolution → resume** loop for [agentic-evolve](../README.md).

## Install

```bash
cd agentic-evolve
pip install -e .
pip install -e alpha-diagnosis/
pip install -e ".[example]"
pip install -r examples/diagnostic-rule-discovery/requirements.txt
```

Requires OpenCode CLI configured (`opencode auth login`).

## Run

```bash
alpha-diagnosis run alpha-diagnosis/workflows/sustaindc_rich_feedback.yaml --resume
```

## Plot

```bash
alpha-diagnosis plot --workspace examples/sustaindc/outputs/sustaindc_rich_feedback_5
```

## Layout

- `workflows/` — end-to-end workflow YAML (primary task + stuck + discovery + injection)
- `adapters/` — per-task metadata (trajectory format, prompt template)
- `templates/` — Jinja prompt sections for rule injection

State is persisted under `<primary_workspace>/alpha-diagnosis/state.json`.

Score progress is logged to `<primary_workspace>/score_trajectory.jsonl` (see [agentic-evolve README](../README.md#score-trajectory-score_trajectoryjsonl)). During stuck monitoring, new attempts are synced on each poll so you can `tail -f` the file while OpenCode runs.

When the agent exits early but improvement budget remains, `loop.auto_resume_on_early_exit` (default `true`) re-opens OpenCode for **primary evolution** and **rule injection** until stuck, inject quota, or budget is exhausted. With `loop.shared_opencode_session: true` (default), primary evolution, rule injection, and post-injection primary resume all use **`opencode run --continue`** on the same session so agent memory is preserved across phase switches. Look for `auto_resume` events in `score_trajectory.jsonl` (`resume_mode: continue` when sharing a session).

To force a fresh OpenCode session on each phase (legacy behavior), set `loop.shared_opencode_session: false`.

**Stuck detection applies only to primary evolution.** Rule injection is quota-driven: the framework hard-stops after `rule_count + quota_tolerance` submissions (default tolerance `2`). Configure via `injection.quota_tolerance` (alias `tol`). Trajectory logs an `injection_quota` event when the limit is hit.

## Discovery modes

`discovery.mode` selects how directions are produced when evolution is stuck:

| Mode | Description |
|------|-------------|
| `regression` (default) | Run diagnostic-rule-discovery sub-evolution; OLS regression scores binary trajectory rules. Requires `discovery.task_dir` and `raw-artifact.json` per attempt. |
| `algorithm_based_rule` | Run algorithm-rule-discovery sub-evolution; OLS regression scores binary **code structure** rules from `code.py`. Requires `discovery.task_dir` pointing at `examples/algorithm-rule-discovery/<task>/`. No `raw-artifact.json` needed. |
| `agent_review` | Single OpenCode session reviews top-N archive attempts and writes `directions.json` with N improvement directions. No `task_dir` needed. |

Both modes feed the same `per_rule_variants` injection pipeline.

Set `discovery.early_injection_r2_threshold` (e.g. `0.99`) to stop the discovery OpenCode session as soon as any valid attempt’s `metrics.r2` reaches the threshold (polled every `stuck.poll_interval_seconds`). The workspace logs a `discovery_r2_threshold` event and proceeds to injection without using the remaining discovery budget.

### `injection.mode: counterfactual` (mode detection upgrade)

For **regression / trajectory mode detection** (`discovery.mode: regression` on tasks with `raw-artifact.json` per attempt). Instead of only listing abstract mode names, injection builds **counterfactual pairs**:

- **Baseline** trajectory site (episode/step, `response_ratio`, `||cmd||`, etc.) where the mode fires or is absent.
- **Exemplar** — a higher-scoring archive attempt with contrasting mode behavior at the same site.
- **Exemplar code excerpt** for structural borrowing.

Requires `store_raw_artifacts: true` on the primary task (workflow-level or `primary.store_raw_artifacts`).

Example workflow: `workflows/optics_temporal_smooth_counterfactual.yaml`

```yaml
injection:
  mode: counterfactual
  include_rule_weights: true
  cf_top_k_attempts: 15
  cf_max_code_lines: 40
```

Preview prompt on an existing run:

```bash
python alpha-diagnosis/scripts/_test_counterfactual_prompt.py
```

### `injection.include_rule_weights`

When `true` (regression discovery only), each injected factor includes a **positive** or **negative** score-association label derived from the discovery regression coefficient sign — no numeric coef values are shown. `agent_review` directions have no regression coefs, so weight labels are omitted even when this flag is `true`.

Example agent-review workflow: `workflows/sustaindc_rich_feedback_agent_review.yaml`.

Artifacts:
- Regression: `alpha-diagnosis/discovery_cycle_XX.json`
- Agent review: `alpha-diagnosis/history_review_cycle_XX.json`

## Sanity check (regression vs agent_review)

Compare whether regression-based rule discovery beats direct agent history review:

1. **Baseline** — existing regression workflow (e.g. `sustaindc_rich_feedback.yaml` → `sustaindc_X`).
2. **Ablation** — agent-review workflow with a different `project_name` (e.g. `sustaindc_rich_feedback_agent_review.yaml` → `sustaindc_X_ar`).
3. **Fork from stuck checkpoint** (recommended for fair comparison):

```bash
alpha-diagnosis run alpha-diagnosis/workflows/sustaindc_rich_feedback_agent_review.yaml \
  --fork-from examples/sustaindc/outputs/sustaindc_X \
  --fork-at-stuck 1
```

CLI flags override workflow `fork:` config. You can also set fork in YAML:

```yaml
fork:
  source_workspace: ../examples/sustaindc/outputs/sustaindc_X
  at_stuck_cycle: 1
```

`--fork-at-attempt 21` truncates through `attempt_0021` inclusive.

When forking with `--fork-at-stuck` (or YAML `at_stuck_cycle`), diagnosis runs **immediately** after fork — no second evolution-to-stuck phase. Use `start_at_diagnosis: false` in YAML to disable this. `--fork-at-attempt` defaults to re-evolving until stuck.

Plot both runs:

```bash
alpha-diagnosis plot --workspace examples/sustaindc/outputs/sustaindc_X
alpha-diagnosis plot --workspace examples/sustaindc/outputs/sustaindc_X_ar
```

## Adding a new task

**Trajectory rules** (`discovery.mode: regression`):

1. Add `examples/diagnostic-rule-discovery/<task_id>/` (see `_shared/README.md`).
2. Add `alpha-diagnosis/adapters/<task_id>.yaml`.
3. Add `alpha-diagnosis/workflows/<name>.yaml` pointing at primary + discovery task dirs.

Upstream archive must include `raw-artifact.json` per attempt.

**Algorithm rules** (`discovery.mode: algorithm_based_rule`):

1. Add `examples/algorithm-rule-discovery/<task_id>/` (see `algorithm-rule-discovery/_shared/README.md`).
2. Reuse or add `alpha-diagnosis/adapters/<task_id>.yaml`.
3. Set `discovery.mode: algorithm_based_rule` and `discovery.task_dir` in workflow YAML.

Upstream archive needs only `code.py` and `result.json` per attempt.
