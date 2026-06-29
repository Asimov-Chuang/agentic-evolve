from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_ROOT.parent
BASELINE_ROOT = PROJECT_ROOT / "Frontier-Engineering" / "baseline_archive"
EXAMPLES_ROOT = REPO_ROOT / "examples"

TASKS = {
    "Astrodynamics_MannedLunarLanding": "manned_lunar_landing",
    "EnergyStorage_BatteryFastChargingSPMe": "battery_fast_charging_spme",
    "InventoryOptimization_general_meio": "general_meio",
    "Optics_adaptive_temporal_smooth_control": "adaptive_temporal_smooth_control",
    "Robotics_PIDTuning": "pid_tuning",
    "Robotics_QuadrupedGaitOptimization": "quadruped_gait_optimization",
    "SustainableDataCenterControl_hand_written_control": "sustaindc",
    "WirelessChannelSimulation_HighReliableSimulation": "high_reliable_simulation",
}

CODE_SUFFIXES = {".py", ".c", ".cc", ".cpp", ".cu", ".m"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, default=BASELINE_ROOT)
    parser.add_argument("--cache", type=Path, default=EXAMPLES_ROOT / "baseline_archive_score_cache.json")
    parser.add_argument("--json-out", type=Path, default=EXAMPLES_ROOT / "baseline_archive_best_scores.json")
    parser.add_argument("--md-out", type=Path, default=EXAMPLES_ROOT / "baseline_archive_best_scores.md")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--task", choices=sorted(TASKS), action="append")
    return parser.parse_args()


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def iter_code_files(baseline_root: Path, selected_tasks: set[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for task_name in sorted(selected_tasks):
        for task_dir in sorted(baseline_root.glob(f"*/*/*/{task_name}")):
            code_files = sorted(path for path in task_dir.iterdir() if path.is_file() and path.suffix in CODE_SUFFIXES)
            if not code_files:
                continue
            relative_parts = task_dir.relative_to(baseline_root).parts
            if len(relative_parts) != 4:
                continue
            experiment, algorithm, model, _ = relative_parts
            rows.append(
                {
                    "experiment": experiment,
                    "algorithm": algorithm,
                    "model": model,
                    "task": task_name,
                    "example": TASKS[task_name],
                    "code_path": str(code_files[0]),
                }
            )
    return rows


def cache_key(row: dict[str, str]) -> str:
    path = Path(row["code_path"])
    stat = path.stat()
    return "|".join(
        [
            row["experiment"],
            row["algorithm"],
            row["model"],
            row["task"],
            str(path.resolve()),
            str(stat.st_mtime_ns),
            str(stat.st_size),
        ]
    )


def parse_json_from_stdout(stdout: str) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        return {}
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        return {"raw_stdout": stdout}
    try:
        return json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return {"raw_stdout": stdout}


def run_evaluation(row: dict[str, str], timeout: float) -> dict[str, Any]:
    evaluator = EXAMPLES_ROOT / row["example"] / "evaluator.py"
    env = dict(os.environ)
    env.setdefault("FRONTIER_ENGINEERING_ROOT", str(PROJECT_ROOT / "Frontier-Engineering"))
    with tempfile.TemporaryDirectory(prefix="baseline-score-") as output_dir:
        completed = subprocess.run(
            [sys.executable, str(evaluator), row["code_path"], output_dir],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
        )
    payload = parse_json_from_stdout(completed.stdout)
    payload.setdefault("returncode", completed.returncode)
    if completed.stderr.strip():
        payload["stderr_tail"] = completed.stderr.strip()[-4000:]
    if completed.returncode != 0:
        payload.setdefault("error", f"evaluator exited with {completed.returncode}")
    return normalize_result(row, payload)


def normalize_result(row: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    score = payload.get("score")
    try:
        score_value = float(score)
    except (TypeError, ValueError):
        score_value = None
    result = dict(row)
    result.update(
        {
            "score": score_value,
            "is_valid": bool(payload.get("is_valid", False)),
            "feedback": str(payload.get("feedback", ""))[:1000],
            "error": payload.get("error"),
            "returncode": payload.get("returncode"),
            "metrics": payload.get("metrics", {}),
        }
    )
    if "stderr_tail" in payload:
        result["stderr_tail"] = payload["stderr_tail"]
    return result


def evaluate_all(rows: list[dict[str, str]], cache_path: Path, refresh: bool, timeout: float) -> list[dict[str, Any]]:
    cache = {} if refresh else load_json(cache_path, {})
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        key = cache_key(row)
        cached = cache.get(key)
        label = f"[{index}/{len(rows)}] {row['experiment']}/{row['algorithm']}/{row['model']} {row['task']}"
        if cached is not None:
            print(f"cached {label}", flush=True)
            results.append(cached)
            continue
        print(f"running {label}", flush=True)
        try:
            result = run_evaluation(row, timeout)
        except subprocess.TimeoutExpired as exc:
            result = dict(row)
            result.update({"score": None, "is_valid": False, "error": f"timeout after {exc.timeout}s"})
        except Exception as exc:
            result = dict(row)
            result.update({"score": None, "is_valid": False, "error": repr(exc)})
        cache[key] = result
        results.append(result)
        write_json(cache_path, cache)
    return results


def finite_score(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_task.setdefault(result["task"], []).append(result)
    task_summaries = []
    for task_name, task_results in sorted(by_task.items()):
        scored = [result for result in task_results if finite_score(result.get("score"))]
        best_score = max((float(result["score"]) for result in scored), default=None)
        winners = [result for result in scored if best_score is not None and float(result["score"]) == best_score]
        task_summaries.append(
            {
                "task": task_name,
                "example": TASKS[task_name],
                "best_score": best_score,
                "winners": winners,
                "completed": len(scored),
                "total": len(task_results),
                "failures": len(task_results) - len(scored),
            }
        )
    return {"generated_on": date.today().isoformat(), "tasks": task_summaries, "results": results}


def fmt_score(value: Any) -> str:
    if not finite_score(value):
        return "NA"
    return f"{float(value):.12g}"


def rel(path: str) -> str:
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Baseline Archive Best Scores for Ported Examples",
        "",
        f"Generated on: {summary['generated_on']}",
        "",
        "Scope: baseline_archive entries whose Frontier task has a migrated agentic-evolve example evaluator.",
        "",
        "## Task Winners",
        "",
        "| Task | Example | Best score | Winner(s) | Completed | Failures |",
        "|---|---|---:|---|---:|---:|",
    ]
    for task_summary in summary["tasks"]:
        winners = ", ".join(
            f"{winner['experiment']}/{winner['algorithm']}/{winner['model']}" for winner in task_summary["winners"]
        )
        lines.append(
            "| {task} | {example} | {score} | {winners} | {completed}/{total} | {failures} |".format(
                task=task_summary["task"],
                example=task_summary["example"],
                score=fmt_score(task_summary["best_score"]),
                winners=winners or "NA",
                completed=task_summary["completed"],
                total=task_summary["total"],
                failures=task_summary["failures"],
            )
        )
    results_by_task: dict[str, list[dict[str, Any]]] = {}
    for result in summary["results"]:
        results_by_task.setdefault(result["task"], []).append(result)
    for task_name in sorted(results_by_task):
        lines.extend(["", f"## {task_name}", "", "| Experiment | Algorithm | Model | Score | Valid | Code | Note |", "|---|---|---|---:|---|---|---|"])
        sorted_results = sorted(
            results_by_task[task_name],
            key=lambda item: (float(item["score"]) if finite_score(item.get("score")) else float("-inf")),
            reverse=True,
        )
        for result in sorted_results:
            note = result.get("error") or result.get("feedback", "")
            note = str(note).replace("\n", " ").replace("|", "\\|")[:160]
            lines.append(
                "| {experiment} | {algorithm} | {model} | {score} | {valid} | {code} | {note} |".format(
                    experiment=result["experiment"],
                    algorithm=result["algorithm"],
                    model=result["model"],
                    score=fmt_score(result.get("score")),
                    valid="yes" if result.get("is_valid") else "no",
                    code=rel(result["code_path"]),
                    note=note,
                )
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    if args.task:
        suffix = "_" + "_".join(task.replace("/", "_") for task in args.task)
        default_json = EXAMPLES_ROOT / "baseline_archive_best_scores.json"
        default_md = EXAMPLES_ROOT / "baseline_archive_best_scores.md"
        if args.json_out == default_json:
            args.json_out = EXAMPLES_ROOT / f"baseline_archive_best_scores{suffix}.json"
        if args.md_out == default_md:
            args.md_out = EXAMPLES_ROOT / f"baseline_archive_best_scores{suffix}.md"
    selected_tasks = set(args.task or TASKS.keys())
    rows = iter_code_files(args.baseline_root, selected_tasks)
    results = evaluate_all(rows, args.cache, args.refresh, args.timeout)
    summary = summarize(results)
    write_json(args.json_out, summary)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(render_markdown(summary), encoding="utf-8")
    print(f"wrote {args.json_out}")
    print(f"wrote {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())