# Signal Processing Example

This is an agentic-evolve port of the OpenEvolve real-time adaptive signal processing task.

## Run

From the `agentic-evolve` directory:

```bash
agentic-evolve run examples/signal_processing/config.yaml
```

Stream agent output live:

```bash
agentic-evolve run -v examples/signal_processing/config.yaml
```

## Task

Candidates implement `run_signal_processing(...)` and are scored with the same metrics OpenEvolve exposes to the LLM:

- Primary score: `overall_score` (also returned as `score`)
- `feedback` uses OpenEvolve-style metric lines (`- metric_name: 0.1234`)
- `metrics` contains the full OpenEvolve aggregate metric set
