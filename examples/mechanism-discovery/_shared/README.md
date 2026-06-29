# Mechanism Discovery — shared evaluator

Mechanism discovery evolves **code predicates**, **trace predicates**, and **typed mechanism links** that explain how optimizer code and policy-visible trajectories relate to metrics/score.

## Candidate API

```python
def get_code_predicates() -> list[CodePredFn]: ...
def get_code_predicate_descriptions() -> list[str]: ...
def get_trace_predicates() -> list[TracePredFn]: ...
def get_trace_predicate_descriptions() -> list[str]: ...
def get_mechanism_links() -> list[MechanismLink]: ...
```

Import `MechanismLink` from `_shared/mechanism_types.py` (copied into workspace `_shared/`).

## Allowed links (v1)

- `code -> trace`
- `trace -> metric` (metric ids from config `mechanism.metric_nodes`)

## Scoring (default)

- `link_consistency` (weight 0.625): directionally consistent conditional effects on archive
- `path_coherence` (weight 0.375): `code -> trace -> metric` chains with strong links
- `enable_predictive_r2: false` by default (optional joint score prediction)

## New task checklist

1. Primary archive must provide `code.py`, `raw-artifact.json`, and `result.json` per attempt.
2. Add `examples/mechanism-discovery/<task_id>/` with `problem.md`, `initial_program.py`, `evaluator.py`, `config.yaml`.
3. Set `source_archive`, `source_archive_top_n`, and `mechanism:` block in config.
4. Use `discovery_sample_type: trajectory` so dataset linking requires raw artifacts.
