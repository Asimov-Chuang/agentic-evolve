# Algorithm-Based Rule Discovery

Evolve binary **algorithm classification rules** that linearly predict attempt scores from optimizer `code.py` sources (no trajectory/raw-artifact required).

## Layout

```
algorithm-rule-discovery/
  _shared/           # Reusable code-based evaluator logic
  pid_tuning/
  adaptive_temporal_smooth_control/
  README.md
```

## Run (standalone)

```bash
agentic-evolve run --fresh examples/algorithm-rule-discovery/pid_tuning/config.yaml
```

Requires `source_archive` pointing at a primary evolution archive with `code.py` and `result.json` per attempt.

## Alpha-diagnosis

```bash
alpha-diagnosis run alpha-diagnosis/workflows/pid_tuning_algorithm_rule.yaml --resume
```

See `_shared/README.md` for adding new tasks.
