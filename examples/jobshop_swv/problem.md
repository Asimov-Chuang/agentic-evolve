# JobShop SWV Scheduling

Evolve the pure-Python `solve_instance(instance)` implementation in `initial_program.py` for the SWV Job Shop Scheduling benchmark family.

A job-shop instance has jobs, machines, and processing times. Each job is a fixed sequence of operations. Operation `k + 1` in a job cannot start before operation `k` finishes, and each machine can process at most one operation at a time. The objective is to minimize makespan: the completion time of the final operation.

## Function to Edit

```python
def solve_instance(instance: dict) -> dict:
    ...
```

Keep the public interface compatible with the baseline. The evaluator also expects `load_family_instances()` and `load_instance_by_name()` to remain available.

## Input

Each `instance` contains:

- `name`: instance name such as `swv01`.
- `duration_matrix[j][k]`: duration of operation `k` in job `j`.
- `machines_matrix[j][k]`: required machine id for operation `k` in job `j`.
- `metadata`: includes `optimum`, `lower_bound`, `upper_bound`, and reference notes.

## Output Contract

Return a dictionary with at least:

```python
{
    "name": instance["name"],
    "makespan": int,
    "machine_schedules": [
        [
            {
                "job_id": int,
                "operation_index": int,
                "start_time": int,
                "end_time": int,
                "duration": int,
            },
            ...
        ],
        ...
    ],
}
```

The schedule must include every operation exactly once, use the correct machine for each operation, respect job precedence, avoid machine overlaps, report exact operation durations, and have `makespan` equal to the recomputed final completion time.

## Benchmark

- Family: SWV, Storer, Wu, and Vaccari 1992.
- Instances: `swv01` through `swv20`.
- Sizes: `20x10`, `20x15`, and `50x10`.
- Some instances have unknown optimum; the evaluator uses upper bound as best-known target for those.

## Scoring

For each instance, the best-known score is:

```text
score_best = min(100, 100 * target / makespan)
```

where `target` is `optimum` when known, otherwise `upper_bound`.

The main score is the average best-known score over selected SWV instances. Higher is better; `100` means matching every best-known target. Invalid schedules receive score `0`.

## Constraints

Use pure Python and the standard library in candidate code. Do not import `job_shop_lib`, OR-Tools, external solvers, multiprocessing pools, or benchmark verification modules. Focus on deterministic constructive scheduling, dispatching rules, local improvement, critical path/machine bottleneck repair, and lightweight search that fits the evaluator timeout.
