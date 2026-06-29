# JobShop SWV Agentic-Evolve Example

This example ports Frontier-Engineering's `benchmarks/JobShop/swv` task into agentic-evolve.

The candidate evolves a pure-Python `solve_instance(instance)` scheduler for SWV job-shop scheduling. The evaluator reuses Frontier's schedule validation/reference solver layout and expands the native output with agentic-evolve raw artifacts.

| Config | Workspace | Feedback |
|--------|-----------|----------|
| [`config.yaml`](config.yaml) | `outputs/jobshop_swv/` | Score plus compact schedule diagnostics |
| [`config_pro.yaml`](config_pro.yaml) | `outputs/jobshop_swv_pro/` | PRO analyzer with per-instance raw-artifact bottleneck feedback |

## Prerequisites

From the repository layout used by this workspace:

```bash
cd ../Frontier-Engineering
bash init.sh

cd ../agentic-evolve
pip install -e .
pip install -e ".[example]"
python -m pip install "ortools>=9.9"
```

The candidate itself must stay pure Python and standard-library only. The evaluator computes optional reference makespans directly with OR-Tools CP-SAT, so `job-shop-lib` is not required. This avoids the `job-shop-lib -> pyarrow` dependency path, which may try to compile `pyarrow` from source on newer Python versions such as 3.14. Do not use Frontier's `benchmarks/JobShop/requirements.txt` on Python 3.14 for this example: it pins `ortools<9.13`, while PyPI currently provides newer Python-3.14 wheels such as `ortools 9.15`. If `ortools` is unavailable, the evaluator still validates candidate schedules and emits raw artifacts; reference makespan fields are simply marked unavailable.

## Smoke Test

Evaluate the seed program on one SWV instance and inspect the generated sidecars:

```bash
cd agentic-evolve
export JOBSHOP_EVAL_MAX_INSTANCES=1
python examples/jobshop_swv/evaluator.py \
	examples/jobshop_swv/initial_program.py \
	/tmp/jobshop_swv_eval

python - <<'PY'
from examples.jobshop_swv.analyzer import analyze
print(analyze('/tmp/jobshop_swv_eval'))
PY
```

On Windows PowerShell, use:

```powershell
cd C:\Users\v-shuhazhang\projects\Evaluator-Discovery\agentic-evolve
$env:JOBSHOP_EVAL_MAX_INSTANCES = '1'
python examples\jobshop_swv\evaluator.py `
	examples\jobshop_swv\initial_program.py `
	examples\jobshop_swv\_smoke_output

python -c "from examples.jobshop_swv.analyzer import analyze; print(analyze('examples/jobshop_swv/_smoke_output'))"
```

Expect `is_valid: true` for the baseline and `raw-artifact.json` containing one per-instance record with `diagnostics.machine_utilization`, `diagnostics.machine_idle_time`, `diagnostics.latest_jobs`, and timeline previews.

## Run Evolution

Standard mode:

```bash
cd agentic-evolve
agentic-evolve run examples/jobshop_swv/config.yaml
agentic-evolve run --resume examples/jobshop_swv/config.yaml
```

PRO mode, where the agent also evolves `analyzer.py` after reading raw artifacts:

```bash
cd agentic-evolve
agentic-evolve run examples/jobshop_swv/config_pro.yaml
agentic-evolve run --resume examples/jobshop_swv/config_pro.yaml
```

For quick development runs, cap the benchmark first:

```bash
export JOBSHOP_EVAL_MAX_INSTANCES=3
export JOBSHOP_REFERENCE_TIME_LIMIT=2
agentic-evolve run examples/jobshop_swv/config.yaml
```

For a full run, unset `JOBSHOP_EVAL_MAX_INSTANCES` so all `swv01` through `swv20` instances are evaluated.

During or after a run, useful files are:

```text
examples/jobshop_swv/outputs/jobshop_swv/score_trajectory.jsonl
examples/jobshop_swv/outputs/jobshop_swv/archive/attempt_0000/raw-artifact.json
examples/jobshop_swv/outputs/jobshop_swv/best_program.py
```

In PRO workspaces you can rerun analyzer feedback for an existing attempt without consuming an improvement:

```bash
cd examples/jobshop_swv/outputs/jobshop_swv_pro
python rerun_analyzer.py attempt_0001
```

## Files

- `initial_program.py`: Frontier SWV greedy EST+SPT baseline.
- `evaluator.py`: agentic-evolve bridge with per-instance raw artifacts.
- `analyzer.py`: standard analyzer.
- `analyzer_pro.py`: richer PRO analyzer seed.
- `config.yaml`: standard mode config.
- `config_pro.yaml`: PRO mode config.
- `problem.md`: task statement and candidate contract.

## Raw Artifacts

`evaluator.py` writes and returns `raw_artifacts`, and also writes `raw-artifact.json` for local inspection. The artifact contains:

- aggregate metrics and selected instance names;
- per-instance validity, makespan, best-known score, lower-bound score, runtime, reference comparison, and gap to target;
- schedule diagnostics: job/machine counts, operation counts, machine busy/idle/utilization arrays, bottleneck machine ids, job completion times, timeline preview, and tail operations;
- worst/best instance summaries;
- validation and reference errors.

This is intentionally richer than Frontier's native `metrics.json`/`artifacts.json`, which do not include low-level scheduling diagnostics.

## Useful Environment Variables

- `FRONTIER_ENGINEERING_ROOT`: path to Frontier-Engineering if auto-discovery fails.
- `JOBSHOP_BENCHMARK_JSON`: override benchmark data path.
- `JOBSHOP_EVAL_INSTANCES`: comma/space-separated instance filter, such as `swv01 swv02`.
- `JOBSHOP_EVAL_MAX_INSTANCES`: cap evaluated instances.
- `JOBSHOP_REFERENCE_TIME_LIMIT`: OR-Tools reference time limit per instance in seconds.

The evaluator only needs `ortools` for optional reference makespans. Candidate validation and raw-artifact generation still work without it.
