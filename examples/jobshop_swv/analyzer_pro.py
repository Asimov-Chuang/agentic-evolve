"""PRO analyzer seed for JobShop SWV."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def load_raw_artifact(
    output_dir: str | Path | None = None,
    result: dict[str, Any] | None = None,
    archive_dir: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> dict[str, Any]:
    if result and isinstance(result.get("raw_artifacts"), dict):
        return dict(result["raw_artifacts"])

    candidates: list[Path] = []
    for base in (output_dir, archive_dir, workspace_dir):
        if base is None:
            continue
        path = Path(base)
        candidates.extend([path / "raw-artifact.json", path / "raw_artifact.json"])
    for path in candidates:
        payload = _load_json(path)
        if payload:
            return payload
    return {}


def _metrics(output_dir: Path | None, result: dict[str, Any] | None, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    if result and isinstance(result.get("metrics"), dict):
        return dict(result["metrics"])
    if raw and isinstance(raw.get("metrics"), dict):
        return dict(raw["metrics"])
    return _load_json(output_dir / "metrics.json") if output_dir is not None else {}


def _instances(raw: dict[str, Any]) -> list[dict[str, Any]]:
    values = raw.get("instances")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, dict)]


def _mean(values: list[float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def _worst_by_score(instances: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    return sorted(instances, key=lambda item: float(item.get("best_known_score") or 0.0))[:limit]


def _bottleneck_stats(instances: list[dict[str, Any]]) -> dict[str, Any]:
    by_machine: dict[str, int] = {}
    util_values: list[float] = []
    idle_values: list[float] = []
    for item in instances:
        diagnostics = item.get("diagnostics")
        if not isinstance(diagnostics, dict):
            continue
        machine = diagnostics.get("bottleneck_machine_by_completion")
        if machine is not None:
            key = str(machine)
            by_machine[key] = by_machine.get(key, 0) + 1
        util_values.append(float(diagnostics.get("max_machine_utilization") or 0.0))
        idle_values.extend(float(value) for value in diagnostics.get("machine_idle_time", []) if isinstance(value, (int, float)))
    return {
        "bottleneck_machine_counts": dict(sorted(by_machine.items(), key=lambda item: item[1], reverse=True)),
        "mean_max_machine_utilization": _mean(util_values),
        "mean_machine_idle_time": _mean(idle_values),
    }


def _family_breakdown(instances: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in instances:
        diagnostics = item.get("diagnostics")
        if not isinstance(diagnostics, dict):
            continue
        size = f"{diagnostics.get('num_jobs')}x{diagnostics.get('num_machines')}"
        groups.setdefault(size, []).append(item)
    breakdown: dict[str, dict[str, float]] = {}
    for size, rows in groups.items():
        breakdown[size] = {
            "count": float(len(rows)),
            "mean_score": _mean([float(row.get("best_known_score") or 0.0) for row in rows]),
            "mean_gap_to_target_pct": _mean([float(row.get("gap_to_target_pct") or 0.0) for row in rows if row.get("gap_to_target_pct") is not None]),
            "mean_runtime_s": _mean([float(row.get("baseline_elapsed_s") or 0.0) for row in rows]),
        }
    return breakdown


def _invalid_notes(instances: list[dict[str, Any]], limit: int = 5) -> list[str]:
    notes: list[str] = []
    for item in instances:
        if item.get("baseline_valid"):
            continue
        notes.append(f"{item.get('name')}: {item.get('baseline_note')}")
        if len(notes) >= limit:
            break
    return notes


def _recommendations(metrics: dict[str, Any], instances: list[dict[str, Any]]) -> list[str]:
    recommendations: list[str] = []
    success_rate = float(metrics.get("baseline_success_rate", 0.0) or 0.0)
    if success_rate < 1.0:
        recommendations.append("First fix schedule construction invariants: every operation exactly once, correct machine, no overlaps, precedence, exact reported makespan.")
        return recommendations

    worst = _worst_by_score(instances, 5)
    large_worst = [item for item in worst if (item.get("diagnostics") or {}).get("num_jobs") == 50]
    if large_worst:
        recommendations.append("Worst cases include 50x10 instances; add scalable neighborhood moves and avoid exhaustive pairwise repair over all operations.")
    else:
        recommendations.append("Worst cases are not only the largest instances; tune dispatching priority and tie-breakers by machine/job slack rather than size alone.")

    bottleneck = _bottleneck_stats(worst)
    if bottleneck.get("mean_max_machine_utilization", 0.0) > 0.85:
        recommendations.append("Completion is dominated by loaded machines; prioritize operations on critical machines earlier and use local swaps on bottleneck timelines.")
    else:
        recommendations.append("Machine utilization is not saturated; investigate precedence-driven waiting and job completion tail operations.")

    avg_gap = float(metrics.get("optimality_gap_avg_baseline", 0.0) or 0.0)
    if avg_gap > 20.0:
        recommendations.append("Average optimum gap is large; a single EST/SPT rule is likely insufficient, so try multiple dispatching rules and keep the best valid schedule per instance.")
    return recommendations


def analyze(
    program_path: str | None = None,
    output_dir: str | None = None,
    result: dict[str, Any] | None = None,
    archive_dir: str | None = None,
    workspace_dir: str | None = None,
) -> str:
    if output_dir is None and program_path:
        output_dir = program_path
    output_path = Path(output_dir) if output_dir else None
    raw = load_raw_artifact(output_path, result, archive_dir, workspace_dir)
    metrics = _metrics(output_path, result, raw)
    instances = _instances(raw)
    worst = _worst_by_score(instances, 8)
    bottleneck = _bottleneck_stats(instances)
    breakdown = _family_breakdown(instances)
    invalid = _invalid_notes(instances)

    lines = [
        "JobShop SWV PRO analyzer",
        f"score={float(metrics.get('combined_score', 0.0) or 0.0):.4f} valid={bool(float(metrics.get('valid', 0.0) or 0.0) > 0.0)} instances={int(float(metrics.get('instances', 0.0) or 0.0))}",
        f"success_rate={float(metrics.get('baseline_success_rate', 0.0) or 0.0):.3f} lb_score={float(metrics.get('score_lb_avg_baseline', 0.0) or 0.0):.4f} opt_gap={float(metrics.get('optimality_gap_avg_baseline', 0.0) or 0.0):.2f}%",
        f"score_distribution: p10={float(metrics.get('score_p10', 0.0) or 0.0):.2f} p50={float(metrics.get('score_p50', 0.0) or 0.0):.2f} p90={float(metrics.get('score_p90', 0.0) or 0.0):.2f}",
        f"raw_artifact_present={bool(raw)} per_instance_records={len(instances)}",
        "",
        "Worst instances",
    ]
    if worst:
        for item in worst:
            diagnostics = item.get("diagnostics") if isinstance(item.get("diagnostics"), dict) else {}
            lines.append(
                f"- {item.get('name')}: score={float(item.get('best_known_score') or 0.0):.2f} "
                f"makespan={item.get('baseline_makespan')} target={item.get('target')} "
                f"gap={float(item.get('gap_to_target_pct') or 0.0):.2f}% "
                f"size={diagnostics.get('num_jobs')}x{diagnostics.get('num_machines')} "
                f"bottleneckM={diagnostics.get('bottleneck_machine_by_completion')}"
            )
    else:
        lines.append("- no per-instance raw artifact records available")

    lines.append("")
    lines.append("Family breakdown")
    for size, stats in sorted(breakdown.items()):
        lines.append(
            f"- {size}: count={int(stats['count'])} mean_score={stats['mean_score']:.2f} "
            f"mean_gap={stats['mean_gap_to_target_pct']:.2f}% runtime={stats['mean_runtime_s']:.4f}s"
        )

    lines.append("")
    lines.append("Bottleneck summary")
    lines.append(f"- machine counts: {bottleneck.get('bottleneck_machine_counts', {})}")
    lines.append(f"- mean max machine utilization: {float(bottleneck.get('mean_max_machine_utilization') or 0.0):.3f}")
    lines.append(f"- mean machine idle time: {float(bottleneck.get('mean_machine_idle_time') or 0.0):.2f}")

    if invalid:
        lines.append("")
        lines.append("Invalid schedule notes")
        lines.extend(f"- {note}" for note in invalid)

    lines.append("")
    lines.append("Recommendations")
    lines.extend(f"- {item}" for item in _recommendations(metrics, instances))
    return "\n".join(lines)
