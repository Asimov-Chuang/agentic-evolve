# Diagnostic Rule Discovery — shared evaluator

## New task checklist

1. Upstream task archive must provide `attempt_*/raw-artifact.json` and `result.json` with `score`.
2. Add a task subfolder under `examples/diagnostic-rule-discovery/<task_id>/` with:
   - `problem.md` — observation/action indices and rule shape
   - `initial_program.py` — `get_rule_functions()` + `get_rule_descriptions()`
   - `evaluator.py` — thin wrapper importing `_shared/evaluator_base.py` with task-specific `strip_fn`
   - `config.template.yaml` — `source_archive: "{{PRIMARY_ARCHIVE}}"`
3. Optional: override `strip_policy_visible_*` in evaluator if trajectory layout differs from SustainDC.
4. `rule_set_size` in config must match `get_rule_functions()` length; samples need `rule_set_size + 1` eligible attempts.

## Phase 2 (not yet supported)

Tasks without step-level trajectories (e.g. circle_packing, signal_processing) need evaluator changes to emit `raw-artifact.json` before rule discovery applies.
