# Mechanism Discovery

Evolve a **mechanism model** — code predicates, trace predicates, and typed links — that explains score/metrics from archive `(code, raw-artifact, result)`.

Unlike flat diagnostic rules, links must form interpretable paths such as:

```text
code:uses_prev_blend -> trace:mode_high_step_slew -> metric:mean_slew
```

## Run (optics example)

```bash
cd agentic-evolve
agentic-evolve run examples/mechanism-discovery/adaptive_temporal_smooth_control/config.yaml
```

Requires a rich-feedback optics archive with `raw-artifact.json` per attempt.

## Optional score prediction term

Set in config:

```yaml
mechanism:
  enable_predictive_r2: true
```

Default is `false` (link + path only).

See `_shared/README.md` for the candidate API and task checklist.
