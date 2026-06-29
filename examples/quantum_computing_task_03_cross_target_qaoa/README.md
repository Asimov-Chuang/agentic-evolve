# Quantum Computing Task 03: Cross-Target QAOA

This example ports `Frontier-Engineering/benchmarks/QuantumComputing/task_03_cross_target_qaoa` into agentic-evolve. It keeps the official Frontier scoring semantics and stores a rich raw artifact sidecar for each attempt.

The candidate program defines `optimize_circuit(input_circuit, target, case)` and returns an optimized Qiskit `QuantumCircuit`. The evaluator tests three deterministic QAOA circuits on both `ibm_falcon_27` and `ionq_aria_25`.

## Modes

- Standard: `config.yaml`
  - Evolves the QAOA circuit optimizer.
  - Uses `analyzer.py` for fixed feedback.
  - Stores raw artifacts under `outputs/quantum_computing_task_03_cross_target_qaoa/archive/attempt_*/raw-artifact.json`.

- Pro: `config_pro.yaml`
  - Evolves the candidate with richer analyzer feedback.
  - Uses `analyzer_pro.py` to inspect per-target bottlenecks, cost gaps, gate counts, and generated artifact coverage.
  - Stores the same raw artifacts and derives more diagnostics from them.

## Requirements

Install the Frontier task dependencies in the Python environment used for evaluation:

```bash
pip install mqt.bench qiskit qiskit-aer matplotlib
```

If pip fails in a Python 3.14 WSL environment with an internal `AssertionError` while installing wheels, rerun the install with bytecode compilation disabled:

```bash
pip install --no-compile mqt.bench qiskit qiskit-aer matplotlib
```

If an attempt fails with `ModuleNotFoundError: No module named 'qiskit'` even after installing dependencies, check the `python_bin` and `python_source` fields in `raw-artifact.json`. By default, the evaluator uses the same Python interpreter that is running agentic-evolve. Set `QUANTUM_QAOA_PYTHON` only when you intentionally want to run the official Frontier evaluator in a separate environment.

`matplotlib` is optional for scoring, but it enables PNG circuit artifacts when circuits are small enough to render.

The evaluator locates Frontier-Engineering by checking `FRONTIER_ENGINEERING_ROOT`, sibling directories, and the repository layout used by this workspace. Optional Python override variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FRONTIER_ENGINEERING_ROOT` | auto-detected checkout | Frontier repository root |
| `QUANTUM_QAOA_PYTHON` | `sys.executable` | Python used to run the official evaluator |
| `QUANTUM_QAOA_INLINE_PNG_BASE64` | unset | Inline PNG bytes in raw artifacts when set to `1`, `true`, or `yes` |

## Run

From the `agentic-evolve` root:

```bash
agentic-evolve run examples/quantum_computing_task_03_cross_target_qaoa/config.yaml
agentic-evolve run examples/quantum_computing_task_03_cross_target_qaoa/config_pro.yaml
```

Direct evaluator smoke test:

```bash
python examples/quantum_computing_task_03_cross_target_qaoa/evaluator.py examples/quantum_computing_task_03_cross_target_qaoa/initial_program.py examples/quantum_computing_task_03_cross_target_qaoa/_smoke
```

Expect `is_valid: true`, six case-target results, and a finite `combined_score` if all dependencies are installed.

## Scoring

For each case-target pair:

```text
cost = two_qubit_count + 0.2 * depth
score_0_to_3 = 3 * (opt0_cost - candidate_cost) / (opt0_cost - opt3_cost)
```

The final score is the average `score_0_to_3` over all six pairs. Higher is better. Scores may exceed 3 when the candidate beats the opt3 reference.

## Raw Artifacts

Each attempt stores `raw-artifact.json` with:

- full official `eval_report.json`
- parsed metrics and artifact summary
- stdout, stderr, return code, runtime, and Python command
- selected Python source, relevant environment variables, and dependency probe results for `qiskit`, `qiskit_aer`, `mqt.bench`, and `matplotlib`
- the submitted candidate source and copied Frontier task context (`TASK.md`, `README.md`, tests, verification scripts, and baseline helper)
- the three JSON test cases
- a manifest for every generated file under `runs/unified_eval`
- inline content for reasonably sized `.json`, `.qasm`, `.txt`, `.stdout`, and `.stderr` files
- PNG metadata and SHA-256 hashes by default, with optional base64 inlining via `QUANTUM_QAOA_INLINE_PNG_BASE64=1`

This keeps enough raw material for analyzer feedback and post-run debugging without mutating the Frontier checkout.

## Files

- `initial_program.py`: baseline target-aware QAOA optimizer.
- `structural_optimizer.py`: local rewrite helper used by the baseline.
- `evaluator.py`: isolated Frontier evaluator bridge and raw artifact collector.
- `analyzer.py`: concise standard feedback.
- `analyzer_pro.py`: richer per-target and per-case diagnostics.
- `problem.md`: task contract shown to the agent.
