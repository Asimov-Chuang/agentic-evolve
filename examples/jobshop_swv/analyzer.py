"""Analyzer for the JobShop SWV agentic-evolve example."""

from __future__ import annotations

import json
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


def _metrics_from(output_dir: Path | None, result: dict[str, Any] | None, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    if result and isinstance(result.get("metrics"), dict):
        return dict(result["metrics"])
    if raw and isinstance(raw.get("metrics"), dict):
        return dict(raw["metrics"])
    payload = _load_json(output_dir / "metrics.json") if output_dir is not None else {}
    return dict(payload) if payload else {}


def _worst_instances(raw: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    instances = raw.get("instances")
    if not isinstance(instances, list):
        return []
    valid_instances = [item for item in instances if isinstance(item, dict)]
    return sorted(
        valid_instances,
        key=lambda item: float(item.get("best_known_score") or 0.0),
    )[:limit]


def _diagnosis(metrics: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    score = float(metrics.get("combined_score", 0.0) or 0.0)
    success_rate = float(metrics.get("baseline_success_rate", 0.0) or 0.0)
    if success_rate < 1.0:
        failures = int(float(metrics.get("baseline_failures", 0.0) or 0.0))
        lines.append(f"Schedule validity is the first priority: {failures} evaluated instance(s) failed validation.")
    elif score < 85.0:
        lines.append("Schedules are feasible but far from best-known targets; improve dispatching/search quality before micro-optimizing runtime.")
    elif score < 95.0:
        lines.append("Feasibility is stable and the main gap is makespan quality on hard instances.")
    else:
        lines.append("The candidate is close to best-known targets; focus on worst-instance repairs and avoiding regressions.")

    worst = _worst_instances(raw, 3)
    if worst:
        formatted = ", ".join(
            f"{item.get('name')}={float(item.get('best_known_score') or 0.0):.2f}"
            for item in worst
        )
        lines.append(f"Worst best-known scores: {formatted}.")

    bottlenecks: list[str] = []
    for item in worst:
        diagnostics = item.get("diagnostics") if isinstance(item, dict) else None
        if isinstance(diagnostics, dict):
            machine = diagnostics.get("bottleneck_machine_by_completion")
            util = diagnostics.get("max_machine_utilization")
            if machine is not None:
                bottlenecks.append(f"{item.get('name')}:M{machine} util={float(util or 0.0):.2f}")
    if bottlenecks:
        lines.append("Completion bottlenecks: " + "; ".join(bottlenecks) + ".")
    return lines


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
    metrics = _metrics_from(output_path, result, raw)

    lines = [
        "JobShop SWV evaluation summary",
        f"- score: {float(metrics.get('combined_score', 0.0) or 0.0):.4f}",
        f"- valid: {bool(float(metrics.get('valid', 0.0) or 0.0) > 0.0)}",
        f"- instances: {int(float(metrics.get('instances', 0.0) or 0.0))}",
        f"- success rate: {float(metrics.get('baseline_success_rate', 0.0) or 0.0):.3f}",
        f"- avg lower-bound score: {float(metrics.get('score_lb_avg_baseline', 0.0) or 0.0):.4f}",
        f"- avg optimality gap: {float(metrics.get('optimality_gap_avg_baseline', 0.0) or 0.0):.2f}%",
        f"- raw artifact present: {bool(raw)}",
        "",
        "Diagnosis",
    ]
    lines.extend(f"- {line}" for line in _diagnosis(metrics, raw))
    return "\n".join(lines)
