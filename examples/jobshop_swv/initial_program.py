# EVOLVE-BLOCK-START
"""Simple greedy baseline for SWV job-shop scheduling."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

FAMILY_PREFIX = "swv"


def _natural_key(name: str) -> list[object]:
    parts = re.split(r"(\d+)", name)
    return [int(part) if part.isdigit() else part for part in parts]


def _benchmark_json_path() -> Path:
    env_path = str(os.environ.get("JOBSHOP_BENCHMARK_JSON", "")).strip()
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"JOBSHOP_BENCHMARK_JSON points to a missing file: {candidate}")

    candidates = [
        Path(__file__).resolve().parents[2] / "data" / "benchmark_instances.json",
        Path(__file__).resolve().parents[1] / "data" / "benchmark_instances.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("benchmark_instances.json not found under JobShop/data")


def load_benchmark_json() -> dict[str, dict[str, Any]]:
    with _benchmark_json_path().open("r", encoding="utf-8") as f:
        return json.load(f)


def load_family_instances() -> list[dict[str, Any]]:
    data = load_benchmark_json()
    selected = [value for name, value in data.items() if name.startswith(FAMILY_PREFIX)]
    return sorted(selected, key=lambda item: _natural_key(item["name"]))


def load_instance_by_name(name: str) -> dict[str, Any]:
    data = load_benchmark_json()
    if name not in data:
        raise KeyError(f"Unknown instance: {name}")
    return data[name]


def solve_instance(instance: dict[str, Any]) -> dict[str, Any]:
    """Greedy EST+SPT scheduler on raw benchmark matrices."""
    durations: list[list[int]] = instance["duration_matrix"]
    machines: list[list[int]] = instance["machines_matrix"]

    num_jobs = len(durations)
    total_operations = sum(len(job) for job in durations)
    num_machines = max(max(row) for row in machines) + 1

    next_op = [0] * num_jobs
    job_ready = [0] * num_jobs
    machine_ready = [0] * num_machines
    machine_schedules: list[list[dict[str, int]]] = [[] for _ in range(num_machines)]

    scheduled = 0
    while scheduled < total_operations:
        candidates: list[tuple[int, int, int, int, int]] = []
        for job_id in range(num_jobs):
            op_idx = next_op[job_id]
            if op_idx >= len(durations[job_id]):
                continue
            machine_id = machines[job_id][op_idx]
            duration = durations[job_id][op_idx]
            est = max(job_ready[job_id], machine_ready[machine_id])
            candidates.append((est, duration, job_id, op_idx, machine_id))

        if not candidates:
            raise RuntimeError("No schedulable operation found.")

        est, duration, job_id, op_idx, machine_id = min(candidates, key=lambda item: (item[0], item[1], item[2]))
        end = est + duration
        machine_schedules[machine_id].append(
            {
                "job_id": job_id,
                "operation_index": op_idx,
                "start_time": est,
                "end_time": end,
                "duration": duration,
            }
        )
        next_op[job_id] += 1
        job_ready[job_id] = end
        machine_ready[machine_id] = end
        scheduled += 1

    makespan = max(job_ready) if job_ready else 0
    return {
        "name": instance["name"],
        "makespan": makespan,
        "machine_schedules": machine_schedules,
        "solved_by": "GreedyESTSPTBaseline",
        "family": FAMILY_PREFIX,
    }
# EVOLVE-BLOCK-END
