# Cross-Target Robust Optimization for QAOA

Write a Qiskit circuit optimizer that works well for the same QAOA family on both `ibm_falcon_27` and `ionq_aria_25` targets.

Your program must define this function:

```python
def optimize_circuit(input_circuit, target, case):
    return optimized_circuit
```

Inputs:
- `input_circuit`: an algorithm-level QAOA `QuantumCircuit` built from the test case.
- `target`: the Qiskit `Target` for the current hardware backend.
- `case`: a dictionary from the test suite. The evaluator adds `case["target_name"]` before calling your function.

Output:
- Return a Qiskit `QuantumCircuit` compatible with the supplied target after evaluator canonicalization.

The evaluator uses three deterministic QAOA cases and expands each across both targets, for six total case-target pairs:
- `cross_target_case_01`: 10 qubits, repetitions 2, seed 11
- `cross_target_case_02`: 12 qubits, repetitions 2, seed 17
- `cross_target_case_03`: 14 qubits, repetitions 3, seed 31

For each pair, the evaluator:
1. Builds an algorithm-level QAOA circuit.
2. Calls your `optimize_circuit(input_circuit, target, case)`.
3. Canonicalizes your output with target-aware `transpile(..., optimization_level=0)`.
4. Generates reference mapped circuits at optimization levels 0, 1, 2, and 3.
5. Computes cost and normalized score.

Cost:

```text
cost = two_qubit_count + 0.2 * depth
```

Normalized pair score:

```text
score_0_to_3 = 3 * (opt0_cost - candidate_cost) / (opt0_cost - opt3_cost)
```

The final score is the average `score_0_to_3` across all six case-target pairs. Higher is better. A score of 0 matches the opt0 reference; a score of 3 matches the opt3 reference on average. Scores can be below 0 or above 3 if the candidate is worse than opt0 or better than opt3.

Focus on robust cross-target behavior rather than overfitting to one backend. Raw artifacts include per-case and per-target metrics, QASM files, generated circuit images or rendering notes, stdout/stderr, and reference comparisons.
