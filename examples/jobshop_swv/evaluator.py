"""JobShop SWV evaluator bridge with expanded raw artifacts."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import statistics
import sys
import time
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

DEFAULT_REFERENCE_TIME_LIMIT_SECONDS = 10.0
BENCHMARK_REL = Path("benchmarks") / "JobShop" / "swv"
EVALUATOR_REL = BENCHMARK_REL / "verification" / "evaluate.py"
DATA_REL = Path("benchmarks") / "JobShop" / "data" / "benchmark_instances.json"


def _default_frontier_root() -> Path:
    env_root = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering"):
            if (candidate / EVALUATOR_REL).is_file():
                return candidate.resolve()
    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _load_module(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _score(target: int | None, makespan: int | None) -> float | None:
    if target is None or makespan is None or makespan <= 0:
        return None
    return min(100.0, 100.0 * float(target) / float(makespan))


def _mean(values: list[float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q / 100.0
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _parse_env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else None


def _parse_env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else None


def _parse_env_instances(name: str) -> list[str] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    items = [part.strip() for part in raw.replace(",", " ").split()]
    return [item for item in items if item] or None


def _load_paths() -> tuple[Path, Path, Path]:
    frontier_root = _default_frontier_root()
    benchmark_dir = frontier_root / BENCHMARK_REL
    evaluate_py = frontier_root / EVALUATOR_REL
    data_json = frontier_root / DATA_REL
    if not evaluate_py.is_file():
        raise FileNotFoundError(f"Frontier SWV evaluator not found: {evaluate_py}")
    if not data_json.is_file():
        raise FileNotFoundError(f"Frontier JobShop data not found: {data_json}")
    return frontier_root, benchmark_dir, evaluate_py


def _load_ortools_cp_model() -> Any:
    from ortools.sat.python import cp_model

    return cp_model


def _solve_reference_makespan(instance: dict[str, Any], cp_model: Any, time_limit_s: float) -> int:
    durations = instance["duration_matrix"]
    machines = instance["machines_matrix"]
    horizon = sum(sum(int(duration) for duration in job) for job in durations)

    model = cp_model.CpModel()
    machine_to_intervals: dict[int, list[Any]] = {}
    starts: dict[tuple[int, int], Any] = {}
    ends: dict[tuple[int, int], Any] = {}

    for job_id, job_durations in enumerate(durations):
        for op_idx, duration_raw in enumerate(job_durations):
            duration = int(duration_raw)
            machine_id = int(machines[job_id][op_idx])
            start = model.NewIntVar(0, horizon, f"s_{job_id}_{op_idx}")
            end = model.NewIntVar(0, horizon, f"e_{job_id}_{op_idx}")
            interval = model.NewIntervalVar(start, duration, end, f"i_{job_id}_{op_idx}")
            starts[(job_id, op_idx)] = start
            ends[(job_id, op_idx)] = end
            machine_to_intervals.setdefault(machine_id, []).append(interval)

    for job_id, job_durations in enumerate(durations):
        for op_idx in range(len(job_durations) - 1):
            model.Add(starts[(job_id, op_idx + 1)] >= ends[(job_id, op_idx)])

    for intervals in machine_to_intervals.values():
        model.AddNoOverlap(intervals)

    makespan = model.NewIntVar(0, horizon, "makespan")
    final_ends = [ends[(job_id, len(job_durations) - 1)] for job_id, job_durations in enumerate(durations) if job_durations]
    model.AddMaxEquality(makespan, final_ends)
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"OR-Tools CP-SAT returned no feasible schedule, status={solver.StatusName(status)}")
    return int(solver.Value(makespan))


def _capture_report(eval_mod: ModuleType, rows: list[Any]) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        eval_mod.print_report(rows)
    return buffer.getvalue()


def _select_instances(eval_mod: ModuleType, baseline_mod: ModuleType) -> list[dict[str, Any]]:
    all_instances = baseline_mod.load_family_instances()
    names = _parse_env_instances("JOBSHOP_EVAL_INSTANCES")
    max_instances = _parse_env_int("JOBSHOP_EVAL_MAX_INSTANCES")
    return eval_mod._select_instances(all_instances, names, max_instances)


def _operation_entries(machine_schedules: Any) -> list[dict[str, int]]:
    entries: list[dict[str, int]] = []
    if not isinstance(machine_schedules, list):
        return entries
    for machine_id, ops in enumerate(machine_schedules):
        if not isinstance(ops, list):
            continue
        for operation in ops:
            if not isinstance(operation, dict):
                continue
            try:
                start_time = int(operation["start_time"])
                end_time = int(operation["end_time"])
                entries.append(
                    {
                        "machine_id": int(machine_id),
                        "job_id": int(operation["job_id"]),
                        "operation_index": int(operation["operation_index"]),
                        "start_time": start_time,
                        "end_time": end_time,
                        "duration": int(operation.get("duration", end_time - start_time)),
                    }
                )
            except Exception:
                continue
    return entries


def _schedule_diagnostics(instance: dict[str, Any], result: dict[str, Any] | None, makespan: int | None) -> dict[str, Any]:
    durations = instance["duration_matrix"]
    machines = instance["machines_matrix"]
    num_jobs = len(durations)
    num_machines = max(max(row) for row in machines) + 1
    total_operations = sum(len(job) for job in durations)
    total_processing_time = sum(sum(job) for job in durations)
    machine_loads = [0] * num_machines
    for job_machines, job_durations in zip(machines, durations):
        for machine_id, duration in zip(job_machines, job_durations):
            machine_loads[int(machine_id)] += int(duration)

    base = {
        "num_jobs": num_jobs,
        "num_machines": num_machines,
        "total_operations": total_operations,
        "total_processing_time": total_processing_time,
        "machine_loads": machine_loads,
    }
    if result is None:
        return base

    entries = _operation_entries(result.get("machine_schedules"))
    machine_busy = [0] * num_machines
    machine_first_start = [None] * num_machines
    machine_last_end = [0] * num_machines
    machine_max_gap = [0] * num_machines
    job_completion = [0] * num_jobs
    by_machine: list[list[dict[str, int]]] = [[] for _ in range(num_machines)]
    for entry in entries:
        if 0 <= entry["machine_id"] < num_machines:
            by_machine[entry["machine_id"]].append(entry)
        if 0 <= entry["job_id"] < num_jobs:
            job_completion[entry["job_id"]] = max(job_completion[entry["job_id"]], entry["end_time"])

    for machine_id, machine_entries in enumerate(by_machine):
        previous_end = 0
        for entry in sorted(machine_entries, key=lambda item: (item["start_time"], item["end_time"])):
            machine_busy[machine_id] += entry["duration"]
            machine_last_end[machine_id] = max(machine_last_end[machine_id], entry["end_time"])
            if machine_first_start[machine_id] is None:
                machine_first_start[machine_id] = entry["start_time"]
            else:
                machine_first_start[machine_id] = min(machine_first_start[machine_id], entry["start_time"])
            machine_max_gap[machine_id] = max(machine_max_gap[machine_id], max(0, entry["start_time"] - previous_end))
            previous_end = max(previous_end, entry["end_time"])

    horizon = int(makespan or max(machine_last_end or [0]))
    idle_by_machine = [max(0, horizon - busy) for busy in machine_busy]
    utilization = [float(busy / horizon) if horizon > 0 else 0.0 for busy in machine_busy]
    bottleneck_load = max(range(num_machines), key=lambda idx: machine_busy[idx]) if num_machines else None
    bottleneck_completion = max(range(num_machines), key=lambda idx: machine_last_end[idx]) if num_machines else None
    latest_jobs = sorted(
        [{"job_id": idx, "completion": value} for idx, value in enumerate(job_completion)],
        key=lambda item: item["completion"],
        reverse=True,
    )[:10]
    timeline_preview = sorted(entries, key=lambda item: (item["start_time"], item["end_time"], item["machine_id"]))[:40]
    tail_operations = sorted(entries, key=lambda item: (item["end_time"], item["start_time"]), reverse=True)[:20]
    return {
        **base,
        "scheduled_operations": len(entries),
        "machine_busy_time": machine_busy,
        "machine_idle_time": idle_by_machine,
        "machine_max_idle_gap": machine_max_gap,
        "machine_utilization": utilization,
        "mean_machine_utilization": _mean(utilization),
        "min_machine_utilization": min(utilization) if utilization else 0.0,
        "max_machine_utilization": max(utilization) if utilization else 0.0,
        "bottleneck_machine_by_load": bottleneck_load,
        "bottleneck_machine_by_completion": bottleneck_completion,
        "job_completion_times": job_completion,
        "latest_jobs": latest_jobs,
        "timeline_preview": timeline_preview,
        "tail_operations": tail_operations,
    }


def _instance_payload(row: Any, instance: dict[str, Any], baseline_result: dict[str, Any] | None) -> dict[str, Any]:
    meta = instance.get("metadata") or {}
    target = row.optimum if row.optimum is not None else row.upper_bound
    best_score = _score(target, row.baseline_makespan)
    lb_score = _score(row.lower_bound, row.baseline_makespan)
    reference_best_score = _score(target, row.reference_makespan)
    gap_pct = None
    if target and row.baseline_makespan:
        gap_pct = 100.0 * (float(row.baseline_makespan) - float(target)) / float(target)
    return {
        "name": row.name,
        "optimum": row.optimum,
        "lower_bound": row.lower_bound,
        "upper_bound": row.upper_bound,
        "target": target,
        "metadata_reference": meta.get("reference"),
        "baseline_makespan": row.baseline_makespan,
        "baseline_valid": bool(row.baseline_valid),
        "baseline_note": row.baseline_note,
        "baseline_elapsed_s": float(row.baseline_elapsed_s),
        "reference_makespan": row.reference_makespan,
        "reference_elapsed_s": row.reference_elapsed_s,
        "reference_error": row.reference_error,
        "best_known_score": best_score,
        "lower_bound_score": lb_score,
        "reference_best_known_score": reference_best_score,
        "gap_to_target_pct": gap_pct,
        "diagnostics": _schedule_diagnostics(instance, baseline_result, row.baseline_makespan),
    }


def _aggregate_metrics(rows: list[Any], runtime_s: float, reference_time_limit: float) -> dict[str, float]:
    best_scores: list[float] = []
    ref_scores: list[float] = []
    lb_scores: list[float] = []
    opt_gaps: list[float] = []
    runtimes: list[float] = []
    failures = 0
    ref_failures = 0
    for row in rows:
        target = row.optimum if row.optimum is not None else row.upper_bound
        b_score = _score(target, row.baseline_makespan)
        r_score = _score(target, row.reference_makespan)
        lb_score = _score(row.lower_bound, row.baseline_makespan)
        if b_score is not None:
            best_scores.append(b_score)
        if r_score is not None:
            ref_scores.append(r_score)
        if lb_score is not None:
            lb_scores.append(lb_score)
        if row.optimum is not None and row.optimum > 0 and row.baseline_makespan is not None:
            opt_gaps.append(100.0 * (float(row.baseline_makespan) - float(row.optimum)) / float(row.optimum))
        runtimes.append(float(row.baseline_elapsed_s))
        if not bool(row.baseline_valid):
            failures += 1
        if row.reference_error is not None:
            ref_failures += 1

    instance_count = len(rows)
    valid = 1.0 if instance_count > 0 and failures == 0 else 0.0
    score = _mean(best_scores) if valid > 0.0 else 0.0
    return {
        "instances": float(instance_count),
        "baseline_failures": float(failures),
        "baseline_successes": float(max(instance_count - failures, 0)),
        "baseline_success_rate": float(max(instance_count - failures, 0) / instance_count) if instance_count else 0.0,
        "reference_failures": float(ref_failures),
        "reference_successes": float(max(instance_count - ref_failures, 0)),
        "reference_success_rate": float(max(instance_count - ref_failures, 0) / instance_count) if instance_count else 0.0,
        "score_best_avg_baseline": score,
        "score_best_avg_reference": _mean(ref_scores),
        "score_lb_avg_baseline": _mean(lb_scores),
        "optimality_gap_avg_baseline": _mean(opt_gaps),
        "baseline_runtime_avg_s": _mean(runtimes),
        "combined_score": score,
        "valid": valid,
        "evaluation_wall_time_s": float(runtime_s),
        "reference_time_limit_s": float(reference_time_limit),
        "score_p10": _percentile(best_scores, 10),
        "score_p50": _percentile(best_scores, 50),
        "score_p90": _percentile(best_scores, 90),
        "worst_instance_score": min(best_scores) if best_scores else 0.0,
        "best_instance_score": max(best_scores) if best_scores else 0.0,
    }


def _failure_result(message: str, output_dir: Path | None = None, raw_artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = {"valid": 0.0, "combined_score": 0.0, "failure_reason": message}
    raw = raw_artifacts or {"benchmark": "JobShop/swv", "is_valid": False, "error_message": message}
    if output_dir is not None:
        _write_json(output_dir / "metrics.json", metrics)
        _write_json(output_dir / "artifacts.json", {"error_message": message})
        _write_json(output_dir / "last_eval.json", {"metrics": metrics, "error_message": message})
        _write_json(output_dir / "raw-artifact.json", raw)
    return {
        "score": 0.0,
        "is_valid": False,
        "feedback": message,
        "metrics": metrics,
        "construction": {"metrics": metrics, "error_message": message},
        "raw_artifacts": raw,
    }


def evaluate(program_path: str, output_dir: str) -> dict[str, Any]:
    output_dir_p = Path(output_dir).expanduser().resolve()
    output_dir_p.mkdir(parents=True, exist_ok=True)
    program_path_p = Path(program_path).expanduser().resolve()
    if not program_path_p.is_file():
        return _failure_result(f"Candidate program not found: {program_path_p}", output_dir_p)

    start_time = time.perf_counter()
    try:
        frontier_root, benchmark_dir, evaluate_py = _load_paths()
        os.environ.setdefault("JOBSHOP_BENCHMARK_JSON", str(frontier_root / DATA_REL))
        eval_mod = _load_module("_jobshop_swv_eval", evaluate_py)
        baseline_mod = _load_module("_jobshop_swv_candidate", program_path_p)
        cp_model = None
        reference_import_error = None
        try:
            cp_model = _load_ortools_cp_model()
        except Exception as exc:
            reference_import_error = str(exc)
        selected = _select_instances(eval_mod, baseline_mod)
        reference_time_limit = _parse_env_float("JOBSHOP_REFERENCE_TIME_LIMIT") or DEFAULT_REFERENCE_TIME_LIMIT_SECONDS
    except Exception as exc:
        raw = {
            "benchmark": "JobShop/swv",
            "candidate_program": str(program_path_p),
            "is_valid": False,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "instances": [],
        }
        return _failure_result(f"Failed to initialize JobShop SWV evaluation: {exc}", output_dir_p, raw)

    rows: list[Any] = []
    instance_payloads: list[dict[str, Any]] = []
    baseline_errors: list[dict[str, str]] = []
    reference_errors: list[dict[str, str]] = []

    try:
        for instance in selected:
            meta = instance["metadata"]
            optimum = meta.get("optimum")
            lower_bound = meta.get("lower_bound")
            upper_bound = meta.get("upper_bound")

            baseline_result: dict[str, Any] | None = None
            baseline_makespan: int | None = None
            baseline_valid = False
            baseline_note: str | None = None
            start = time.perf_counter()
            try:
                raw_result = baseline_mod.solve_instance(instance)
                if isinstance(raw_result, dict):
                    baseline_result = raw_result
                validation = eval_mod._validate_baseline_schedule(instance, raw_result)
                baseline_makespan = int(validation.actual_makespan)
                baseline_valid = True
                baseline_note = validation.note
            except Exception as exc:
                baseline_note = str(exc)
            baseline_elapsed = time.perf_counter() - start

            reference_makespan: int | None = None
            reference_elapsed: float | None = None
            reference_error: str | None = None
            if cp_model is not None:
                try:
                    start = time.perf_counter()
                    reference_makespan = _solve_reference_makespan(instance, cp_model, float(reference_time_limit))
                    reference_elapsed = time.perf_counter() - start
                except Exception as exc:
                    reference_error = str(exc)

            row = eval_mod.InstanceResult(
                name=instance["name"],
                optimum=optimum,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                baseline_makespan=baseline_makespan,
                baseline_valid=baseline_valid,
                baseline_note=baseline_note,
                baseline_elapsed_s=baseline_elapsed,
                reference_makespan=reference_makespan,
                reference_elapsed_s=reference_elapsed,
                reference_error=reference_error,
            )
            rows.append(row)
            payload = _instance_payload(row, instance, baseline_result)
            instance_payloads.append(payload)
            if not baseline_valid:
                baseline_errors.append({"instance": instance["name"], "error": baseline_note or "invalid schedule"})
            if cp_model is not None and reference_error is not None:
                reference_errors.append({"instance": instance["name"], "error": reference_error})
    except Exception:
        raw = {
            "benchmark": "JobShop/swv",
            "frontier_root": str(frontier_root),
            "candidate_program": str(program_path_p),
            "traceback": traceback.format_exc(),
            "partial_instances": instance_payloads,
        }
        return _failure_result("JobShop SWV evaluation failed during instance loop.", output_dir_p, raw)

    runtime_s = time.perf_counter() - start_time
    metrics = _aggregate_metrics(rows, runtime_s, float(reference_time_limit))
    report_text = _capture_report(eval_mod, rows)
    reference_unavailable = cp_model is None
    if reference_unavailable:
        metrics["reference_available"] = 0.0
        metrics["reference_skipped"] = float(len(rows))
        metrics["reference_successes"] = 0.0
        metrics["reference_success_rate"] = 0.0
        metrics["reference_failures"] = 0.0
        report_text += (
            "\nReference solver unavailable; reference columns are skipped. "
            f"Import error: {reference_import_error or 'reference solver unavailable'}\n"
        )
    else:
        metrics["reference_available"] = 1.0
        metrics["reference_skipped"] = 0.0
    worst_instances = sorted(instance_payloads, key=lambda item: _as_float(item.get("best_known_score"), 0.0))[:8]
    best_instances = sorted(
        instance_payloads,
        key=lambda item: _as_float(item.get("best_known_score"), 0.0),
        reverse=True,
    )[:8]
    construction = {
        "family": "swv",
        "benchmark": "JobShop/swv",
        "candidate_program": str(program_path_p),
        "selected_instances": [item["name"] for item in instance_payloads],
        "metrics": metrics,
        "baseline_errors": baseline_errors,
        "reference_errors": reference_errors,
        "reference_unavailable": reference_unavailable,
        "reference_import_error": reference_import_error,
        "report": report_text,
    }
    raw_artifacts = {
        "benchmark": "JobShop/swv",
        "frontier_root": str(frontier_root),
        "benchmark_dir": str(benchmark_dir),
        "candidate_program": str(program_path_p),
        "reference_time_limit_s": float(reference_time_limit),
        "metrics": metrics,
        "instances": instance_payloads,
        "worst_instances": worst_instances,
        "best_instances": best_instances,
        "baseline_errors": baseline_errors,
        "reference_errors": reference_errors,
        "reference_unavailable": reference_unavailable,
        "reference_import_error": reference_import_error,
        "report": report_text,
    }
    artifacts = {
        "family": "swv",
        "benchmark_dir": str(benchmark_dir),
        "candidate_path": str(program_path_p),
        "selected_instances": [item["name"] for item in instance_payloads],
        "baseline_errors": baseline_errors,
        "reference_errors": reference_errors,
        "reference_unavailable": reference_unavailable,
        "reference_import_error": reference_import_error,
        "evaluation_wall_time_s": runtime_s,
        "raw_artifact_instance_count": len(instance_payloads),
    }

    _write_json(output_dir_p / "metrics.json", metrics)
    _write_json(output_dir_p / "artifacts.json", artifacts)
    _write_json(output_dir_p / "last_eval.json", construction)
    _write_json(output_dir_p / "raw-artifact.json", raw_artifacts)
    (output_dir_p / "eval.stdout.txt").write_text(report_text, encoding="utf-8")
    (output_dir_p / "eval.stderr.txt").write_text("\n".join(err["error"] for err in baseline_errors), encoding="utf-8")

    score = float(metrics["combined_score"])
    is_valid = bool(metrics.get("valid", 0.0) > 0.0)
    feedback = (
        f"Score: {score:.4f}\n"
        f"Valid: {is_valid}\n"
        f"Instances: {int(metrics['instances'])}\n"
        f"Success rate: {metrics['baseline_success_rate']:.3f}\n"
        f"Worst instance score: {metrics['worst_instance_score']:.2f}\n"
        f"Average gap to known optimum: {metrics['optimality_gap_avg_baseline']:.2f}%"
    )
    return {
        "score": score,
        "is_valid": is_valid,
        "feedback": feedback,
        "metrics": metrics,
        "construction": construction,
        "raw_artifacts": raw_artifacts,
    }


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    result = evaluate(candidate, out)
    printable = {key: value for key, value in result.items() if key != "raw_artifacts"}
    print(json.dumps(printable, indent=2, default=str))
