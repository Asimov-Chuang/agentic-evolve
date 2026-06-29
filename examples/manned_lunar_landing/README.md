# Manned Lunar Landing Example

This example ports `Frontier-Engineering/benchmarks/Astrodynamics/MannedLunarLanding` into agentic-evolve. It follows the SustainDC pattern: one standard mode config, one pro mode config, a Frontier evaluator bridge, and raw artifact sidecars for every attempt.

## Modes

- Standard: `config.yaml`
  - Evolves the candidate trajectory generator.
  - Uses `analyzer.py` for fixed processed feedback.
  - Stores raw artifacts under `outputs/manned_lunar_landing/archive/attempt_*/raw-artifact.json`.

- Pro: `config_pro.yaml`
  - Evolves both the candidate and analyzer.
  - Uses `analyzer_pro.py` to extract richer signals from `raw-artifact.json`.
  - Enables `rerun_analyzer.py` in the generated workspace for analyzer-only iteration.

## Requirements

- Frontier-Engineering checkout available as a sibling of `agentic-evolve`, or set `FRONTIER_ENGINEERING_ROOT` to its root.
- Python environment with the candidate dependencies, including `numpy` and `scipy`.
- Octave available on PATH, or discoverable through `OCTAVE`, `OCTAVE_HOME`, or `CONDA_PREFIX`.
- CloudGPT proxy for OpenCode model routing.

## CloudGPT / DeepSeek V4 Pro

Both configs use the repo-level OpenCode config:

```yaml
opencode_config: ../../opencode.cloudgpt.json
```

Both configs pin OpenCode to DeepSeek V4 Pro:

```yaml
opencode:
  model: cloudgpt/DeepSeek-V4-Pro
  small_model: cloudgpt/DeepSeek-V4-Pro
```

Start the CloudGPT proxy before running the example:

```bash
bash scripts/start-cloudgpt-proxy.sh
```

The config values override `CLOUDGPT_MODEL` and `CLOUDGPT_SMALL_MODEL` only for the OpenCode process, then restore the previous environment after the run.

## Run

From the `agentic-evolve` root:

```bash
agentic-evolve run examples/manned_lunar_landing/config.yaml
agentic-evolve run examples/manned_lunar_landing/config_pro.yaml
```

For pro mode with the proxy startup and model logging wrapped together, use:

```bash
bash examples/manned_lunar_landing/scripts/run-pro-deepseekv4pro.sh -v
```

Both `model` and `small_model` are set because OpenCode may use `small_model` for build/planning phases; leaving it unset can make those phases fall back to a different model such as `gpt-5.4-nano-20260317`.

`config_pro.yaml` also sets `analyzer_max_feedback_lines: 40`, which hard-caps analyzer `processed_feedback` after each submit or `rerun_analyzer.py` refresh. This keeps evolved analyzer feedback compact even if the agent edits `analyzer.py` to emit verbose diagnostics.

For quick smoke tests, temporarily reduce `max_improvements` in a local copy of a config.

## Raw Artifacts

The evaluator returns `raw_artifacts`, so agentic-evolve persists `raw-artifact.json` sidecars for both modes. They contain Frontier metrics, candidate stdout/stderr, Octave stdout/stderr, `results.txt`, `outputlog.txt`, and derived summaries. In pro mode, evolve `analyzer.py` and use `python rerun_analyzer.py <attempt_id>` inside the workspace to refresh feedback without re-running the expensive validator.
