"""PRO-mode analyzer for cross-target QAOA raw artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_raw_artifact(output_dir: str | Path) -> dict[str, Any] | None:
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


def _case_averages(raw: dict[str, Any] | None) -> dict[str, float]:
    values = (raw or {}).get("case_averages")
    if not isinstance(values, dict):
        return {}
    return {str(key): _as_float(value) for key, value in values.items()}


def _candidate_metrics(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("candidate_metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def _gate_totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        metrics = _candidate_metrics(row)
        for key in ("depth", "size", "two_qubit_count", "cx_count", "ecr_count", "swap_count", "t_count", "tdg_count"):
            totals[key] = totals.get(key, 0.0) + _as_float(metrics.get(key))
    count = max(len(rows), 1)
    return {f"avg_{key}": value / count for key, value in totals.items()}


def _rank_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"best": {}, "worst": {}, "largest_opt3_gap": {}, "slowest": {}}
    return {
        "best": sorted(rows, key=lambda item: _as_float(item.get("candidate_score_0_to_3")), reverse=True)[0],
        "worst": sorted(rows, key=lambda item: _as_float(item.get("candidate_score_0_to_3"), 1e18))[0],
        "largest_opt3_gap": sorted(rows, key=lambda item: _as_float(item.get("gap_vs_opt3")), reverse=True)[0],
        "slowest": sorted(rows, key=lambda item: _as_float(item.get("candidate_total_runtime_s")), reverse=True)[0],
    }


def _artifact_counts(raw: dict[str, Any] | None) -> dict[str, float]:
    manifest = (raw or {}).get("artifact_manifest")
    if not isinstance(manifest, list):
        manifest = []
    counts: dict[str, float] = {"artifact_file_count": float(len(manifest))}
    total_size = 0.0
    for item in manifest:
        if not isinstance(item, dict):
            continue
        suffix = str(item.get("suffix") or "no_suffix")
        key = f"artifact_count_{suffix.lstrip('.') or 'no_suffix'}"
        counts[key] = counts.get(key, 0.0) + 1.0
        total_size += _as_float(item.get("size_bytes"))
        if "content" in item:
            counts["artifact_inline_text_count"] = counts.get("artifact_inline_text_count", 0.0) + 1.0
        if "content_base64" in item:
            counts["artifact_inline_binary_count"] = counts.get("artifact_inline_binary_count", 0.0) + 1.0
    counts["artifact_total_size_bytes"] = total_size
    task_context = (raw or {}).get("task_context_manifest")
    if isinstance(task_context, list):
        counts["task_context_file_count"] = float(len(task_context))
        counts["task_context_inline_text_count"] = float(sum(1 for item in task_context if isinstance(item, dict) and "content" in item))
    return counts


def _dependency_diagnosis(raw: dict[str, Any] | None) -> list[str]:
    probe = (raw or {}).get("dependency_probe")
    if not isinstance(probe, dict):
        return []
    parsed = probe.get("parsed") if isinstance(probe.get("parsed"), dict) else {}
    modules = parsed.get("modules") if isinstance(parsed.get("modules"), dict) else {}
    missing = [name for name, item in modules.items() if isinstance(item, dict) and not item.get("available")]
    if not missing:
        return []
    return [
        "Evaluator Python is missing dependencies: "
        f"{', '.join(sorted(missing))}. "
        f"python={(raw or {}).get('python_bin')} source={(raw or {}).get('python_source')}"
    ]


def _target_gate_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("target_name", "unknown")), []).append(row)
    return {target: _gate_totals(items) for target, items in grouped.items()}


def _diagnosis(result: dict[str, Any], raw: dict[str, Any] | None, metrics: dict[str, Any], ranks: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    if not raw:
        return ["Raw artifact missing; pro feedback cannot inspect per-target QAOA metrics."]

    if not result.get("is_valid"):
        artifacts = raw.get("artifacts") if isinstance(raw.get("artifacts"), dict) else {}
        diagnosis.append(f"Invalid attempt: {artifacts.get('error_message') or result.get('feedback', '')}")
        diagnosis.extend(_dependency_diagnosis(raw))

    target_avgs = _target_averages(raw)
    if target_avgs:
        worst_target = min(target_avgs.items(), key=lambda item: item[1])
        best_target = max(target_avgs.items(), key=lambda item: item[1])
        diagnosis.append(
            f"Target bottleneck: {worst_target[0]} avg_score={worst_target[1]:.3f}; "
            f"best target {best_target[0]} avg_score={best_target[1]:.3f}."
        )

    worst = ranks.get("worst") or {}
    if worst:
        metrics_row = _candidate_metrics(worst)
        diagnosis.append(
            f"Worst pair {worst.get('case_id')} @ {worst.get('target_name')}: "
            f"score={_as_float(worst.get('candidate_score_0_to_3')):.3f}, "
            f"cost={_as_float(worst.get('candidate_cost')):.3f}, "
            f"depth={_as_float(metrics_row.get('depth')):.0f}, "
            f"two_qubit={_as_float(metrics_row.get('two_qubit_count')):.0f}."
        )

    gap = ranks.get("largest_opt3_gap") or {}
    if gap:
        diagnosis.append(
            f"Largest reference gap is {gap.get('case_id')} @ {gap.get('target_name')} "
            f"gap_vs_opt3={_as_float(gap.get('gap_vs_opt3')):.3f}; inspect target-specific routing and two-qubit gates."
        )

    gate_totals = _gate_totals(_rows(raw))
    avg_two = _as_float(gate_totals.get("avg_two_qubit_count"))
    avg_depth = _as_float(gate_totals.get("avg_depth"))
    if avg_two > 0.0 and avg_depth > 0.0:
        depth_cost = 0.2 * avg_depth
        if avg_two > depth_cost:
            diagnosis.append("Cost is dominated by two-qubit gates; prioritize routing, basis selection, and cancellation around entanglers.")
        else:
            diagnosis.append("Depth is a large share of cost; prioritize schedule shortening and repeated rotation merges.")

    score = _as_float(metrics.get("combined_score"), -1e18)
    if score < 2.0:
        diagnosis.append("Average score is still well below opt3; use per-target branches sparingly and keep both backends robust.")
    return diagnosis


def format_processed_feedback(
    result: dict[str, Any],
    metrics: dict[str, Any],
    raw: dict[str, Any] | None,
    ranks: dict[str, Any],
    diagnosis: list[str],
) -> str:
    summary = _summary(raw)
    target_avgs = _target_averages(raw)
    case_avgs = _case_averages(raw)
    rows = _rows(raw)
    gate_totals = _gate_totals(rows)
    artifact_counts = _artifact_counts(raw)

    lines = [
        f"Score: {_as_float(metrics.get('combined_score'), -1e18):.6f} (valid={int(bool(result.get('is_valid')))})",
        f"Avg cost candidate/opt0/opt3: {_as_float(summary.get('avg_candidate_cost')):.3f}/"
        f"{_as_float(summary.get('avg_opt0_cost')):.3f}/{_as_float(summary.get('avg_opt3_cost')):.3f}",
        f"Avg candidate gates: depth={_as_float(gate_totals.get('avg_depth')):.1f}, "
        f"two_qubit={_as_float(gate_totals.get('avg_two_qubit_count')):.1f}, "
        f"cx={_as_float(gate_totals.get('avg_cx_count')):.1f}, ecr={_as_float(gate_totals.get('avg_ecr_count')):.1f}, "
        f"swap={_as_float(gate_totals.get('avg_swap_count')):.1f}",
        f"Runtime seconds: {_as_float(metrics.get('runtime_s')):.2f}",
        f"Artifacts: files={int(_as_float(artifact_counts.get('artifact_file_count')))}, "
        f"qasm={int(_as_float(artifact_counts.get('artifact_count_qasm')))}, "
        f"png={int(_as_float(artifact_counts.get('artifact_count_png')))}, "
        f"inline_text={int(_as_float(artifact_counts.get('artifact_inline_text_count')))}, "
        f"task_context={int(_as_float(artifact_counts.get('task_context_file_count')))}",
    ]
    for target, value in sorted(target_avgs.items()):
        gates = _target_gate_breakdown(rows).get(target, {})
        lines.append(
            f"{target}: avg_score={value:.4f}, avg_two_qubit={_as_float(gates.get('avg_two_qubit_count')):.1f}, "
            f"avg_depth={_as_float(gates.get('avg_depth')):.1f}"
        )
    for case_id, value in sorted(case_avgs.items()):
        lines.append(f"{case_id}: avg_score={value:.4f}")
    for label in ("best", "worst", "largest_opt3_gap", "slowest"):
        row = ranks.get(label) or {}
        if row:
            lines.append(
                f"{label}: {row.get('case_id')} @ {row.get('target_name')} "
                f"score={_as_float(row.get('candidate_score_0_to_3')):.4f}, "
                f"cost={_as_float(row.get('candidate_cost')):.4f}, "
                f"runtime={_as_float(row.get('candidate_total_runtime_s')):.4f}s"
            )
    for item in diagnosis:
        lines.append(f"- {item}")
    return "\n".join(lines)


def analyze(
    program_path: str,
    output_dir: str,
    result: dict,
    archive_dir: str,
    workspace_dir: str,
) -> dict[str, Any]:
    del program_path, archive_dir, workspace_dir

    raw = load_raw_artifact(output_dir)
    metrics = _metrics_from(result, raw)
    rows = _rows(raw)
    ranks = _rank_rows(rows)
    gate_totals = _gate_totals(rows)
    artifact_counts = _artifact_counts(raw)
    target_gate_breakdown = _target_gate_breakdown(rows)
    diagnosis = _diagnosis(result, raw, metrics, ranks)

    return {
        "processed_feedback": format_processed_feedback(result, metrics, raw, ranks, diagnosis),
        "analysis_metrics": {
            "combined_score": _as_float(metrics.get("combined_score"), -1e18),
            "valid": 1.0 if result.get("is_valid") else 0.0,
            "raw_artifact_present": 1.0 if raw is not None else 0.0,
            "runtime_s": _as_float(metrics.get("runtime_s")),
            "result_count": _as_float(metrics.get("result_count")),
            **gate_totals,
            **artifact_counts,
        },
        "analysis": {
            "diagnosis": diagnosis,
            "target_averages": _target_averages(raw),
            "case_averages": _case_averages(raw),
            "ranked_rows": ranks,
            "gate_totals": gate_totals,
            "target_gate_breakdown": target_gate_breakdown,
            "artifact_counts": artifact_counts,
            "artifact_manifest_summary": (raw or {}).get("artifact_manifest_summary", {}),
            "task_context_manifest_summary": (raw or {}).get("task_context_manifest_summary", {}),
            "dependency_probe": (raw or {}).get("dependency_probe", {}),
        },
    }
