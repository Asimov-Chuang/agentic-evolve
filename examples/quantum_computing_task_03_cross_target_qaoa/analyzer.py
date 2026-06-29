"""Standard analyzer for cross-target QAOA raw artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_raw_artifact(output_dir: str | Path) -> dict[str, Any] | None:
    path = Path(output_dir) / "raw-artifact.json"
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _metrics_from(result: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    metrics = result.get("metrics")
    if isinstance(metrics, dict) and metrics:
        return dict(metrics)
    construction = result.get("construction")
    if isinstance(construction, dict) and isinstance(construction.get("metrics"), dict):
        return dict(construction["metrics"])
    if raw and isinstance(raw.get("metrics"), dict):
        return dict(raw["metrics"])
    return {}


def _rows(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = (raw or {}).get("case_target_rows")
    return list(rows) if isinstance(rows, list) else []


def _summary(raw: dict[str, Any] | None) -> dict[str, Any]:
    summary = (raw or {}).get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def _target_averages(raw: dict[str, Any] | None) -> dict[str, float]:
    values = (raw or {}).get("target_averages")
    if not isinstance(values, dict):
        return {}
    return {str(key): _as_float(value) for key, value in values.items()}


def _worst_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(rows, key=lambda item: _as_float(item.get("candidate_score_0_to_3"), 1e18))[0]


def _row_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        lines.append(
            f"{row.get('case_id')} @ {row.get('target_name')}: "
            f"score={_as_float(row.get('candidate_score_0_to_3')):.4f}, "
            f"cost={_as_float(row.get('candidate_cost')):.4f}, "
            f"opt3={_as_float(row.get('opt3_cost')):.4f}"
        )
    return lines


def _diagnosis(result: dict[str, Any], raw: dict[str, Any] | None, metrics: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    if not raw:
        return ["No raw artifact was available; inspect evaluator setup."]

    if not result.get("is_valid"):
        artifacts = raw.get("artifacts") if isinstance(raw.get("artifacts"), dict) else {}
        diagnosis.append(f"Invalid attempt: {artifacts.get('error_message') or result.get('feedback', '')}")
        probe = raw.get("dependency_probe") if isinstance(raw.get("dependency_probe"), dict) else {}
        parsed = probe.get("parsed") if isinstance(probe.get("parsed"), dict) else {}
        modules = parsed.get("modules") if isinstance(parsed.get("modules"), dict) else {}
        missing = [name for name, item in modules.items() if isinstance(item, dict) and not item.get("available")]
        if missing:
            diagnosis.append(
                "Evaluator Python is missing dependencies: "
                f"{', '.join(sorted(missing))}. "
                f"python={raw.get('python_bin')} source={raw.get('python_source')}"
            )

    target_avgs = _target_averages(raw)
    if len(target_avgs) >= 2:
        worst_target = min(target_avgs.items(), key=lambda item: item[1])
        best_target = max(target_avgs.items(), key=lambda item: item[1])
        if best_target[1] - worst_target[1] > 0.5:
            diagnosis.append(
                f"Target imbalance: {worst_target[0]} is lower ({worst_target[1]:.3f}) than "
                f"{best_target[0]} ({best_target[1]:.3f})."
            )

    worst = _worst_row(_rows(raw))
    if worst:
        gap = _as_float(worst.get("gap_vs_opt3"))
        if gap > 0.25:
            diagnosis.append(
                f"Largest opt3 gap is {worst.get('case_id')} @ {worst.get('target_name')} "
                f"with gap_vs_opt3={gap:.3f}."
            )

    score = _as_float(metrics.get("combined_score"), -1e18)
    if score < 1.0:
        diagnosis.append("Average score is below opt1-like performance; prioritize reducing two-qubit count before small depth wins.")
    return diagnosis


def analyze(
    program_path: str,
    output_dir: str,
    result: dict,
    archive_dir: str,
    workspace_dir: str,
) -> dict[str, Any]:
    del program_path, archive_dir, workspace_dir

    raw = _load_raw_artifact(output_dir)
    metrics = _metrics_from(result, raw)
    summary = _summary(raw)
    rows = _rows(raw)
    target_avgs = _target_averages(raw)
    diagnosis = _diagnosis(result, raw, metrics)
    manifest_summary = (raw or {}).get("artifact_manifest_summary") or {}
    task_context_summary = (raw or {}).get("task_context_manifest_summary") or {}

    lines = [
        f"Score: {_as_float(metrics.get('combined_score'), -1e18):.6f}",
        f"Valid: {bool(result.get('is_valid'))}",
        f"Avg candidate cost: {_as_float(summary.get('avg_candidate_cost')):.4f}",
        f"Avg opt0/opt3 cost: {_as_float(summary.get('avg_opt0_cost')):.4f}/{_as_float(summary.get('avg_opt3_cost')):.4f}",
        f"Runtime seconds: {_as_float(metrics.get('runtime_s')):.2f}",
        f"Raw artifact files: {int(_as_float(manifest_summary.get('file_count')))}",
        f"Raw task context files: {int(_as_float(task_context_summary.get('file_count')))}",
    ]
    for target, value in sorted(target_avgs.items()):
        lines.append(f"{target}: avg_score={value:.4f}")
    lines.extend(_row_lines(rows))
    lines.extend(f"- {item}" for item in diagnosis)

    worst = _worst_row(rows)
    return {
        "processed_feedback": "\n".join(lines),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score"), -1e18),
            "valid": 1.0 if result.get("is_valid") else 0.0,
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
            "avg_candidate_cost": _as_float(summary.get("avg_candidate_cost")),
            "avg_opt0_cost": _as_float(summary.get("avg_opt0_cost")),
            "avg_opt3_cost": _as_float(summary.get("avg_opt3_cost")),
            "runtime_s": _as_float(metrics.get("runtime_s")),
            "result_count": _as_float(metrics.get("result_count")),
            "artifact_file_count": _as_float(manifest_summary.get("file_count")),
            "task_context_file_count": _as_float(task_context_summary.get("file_count")),
        },
        "analysis": {
            "diagnosis": diagnosis,
            "target_averages": target_avgs,
            "case_target_rows": rows,
            "worst_case_target": worst or {},
            "artifact_manifest_summary": manifest_summary,
            "task_context_manifest_summary": task_context_summary,
            "dependency_probe": (raw or {}).get("dependency_probe", {}),
        },
    }
