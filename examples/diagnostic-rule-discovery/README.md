# Diagnostic Rule Discovery

Evolve binary diagnostic rules that linearly predict attempt scores from trajectory archives.

## Layout

```
diagnostic-rule-discovery/
  _shared/           # Reusable evaluator logic
  sustaindc/         # SustainDC task adapter
  README.md
```

## Run (SustainDC)

```bash
agentic-evolve run --fresh examples/diagnostic-rule-discovery/sustaindc/config.yaml
```

Or use alpha-diagnosis for automated discovery during evolution:

```bash
alpha-diagnosis run alpha-diagnosis/workflows/sustaindc_rich_feedback.yaml --resume
```

See `_shared/README.md` for adding new tasks.
