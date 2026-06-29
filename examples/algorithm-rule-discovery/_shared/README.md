# Algorithm-Based Rule Discovery — shared evaluator

Evolve binary **algorithm classification rules** that linearly predict attempt scores from optimizer `code.py` sources.

## New task checklist

1. Upstream primary archive must provide `attempt_*/code.py` and `result.json` with `score` (no `raw-artifact.json` required).
2. Add a task subfolder under `examples/algorithm-rule-discovery/<task_id>/` with:
   - `problem.md` — algorithm design space and rule shape
   - `initial_program.py` — `get_rule_functions()` + `get_rule_descriptions()`; each rule is `rule(code: str) -> (0|1, explanation)`
   - `evaluator.py` — thin wrapper importing `_shared/evaluator_base.py`
   - `config.template.yaml` — `source_archive`, `discovery_sample_type: code`
3. `rule_set_size` in config must match `get_rule_functions()` length; samples need `rule_set_size + 1` eligible attempts.
4. Use `code_rule_utils.py` helpers (`has_call`, `parse_assignments`, etc.) inside rules when useful.

## Alpha-diagnosis

Set workflow `discovery.mode: algorithm_based_rule` and `discovery.task_dir` to this task folder.
