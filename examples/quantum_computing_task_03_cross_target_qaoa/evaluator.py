"""Cross-target QAOA evaluator bridge for agentic-evolve."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

BENCHMARK = "QuantumComputing/task_03_cross_target_qaoa"
BENCHMARK_REL = Path("benchmarks") / "QuantumComputing" / "task_03_cross_target_qaoa"
VERIFICATION_EVALUATOR_REL = BENCHMARK_REL / "verification" / "evaluate.py"
DEFAULT_SCORE = -1e18
DEFAULT_TIMEOUT_SECONDS = 600
INLINE_TEXT_LIMIT_BYTES = 512_000
INLINE_BINARY_LIMIT_BYTES = 2_000_000


def _frontier_root_from_env() -> Path | None:
    raw = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _is_frontier_root(path: Path) -> bool:
    return (path / "frontier_eval").is_dir() and (path / VERIFICATION_EVALUATOR_REL).is_file()


def _default_frontier_root() -> Path:
    env_root = _frontier_root_from_env()
    if env_root is not None:
        if _is_frontier_root(env_root):
            return env_root
        raise FileNotFoundError(f"FRONTIER_ENGINEERING_ROOT is not a valid Frontier checkout: {env_root}")

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates = (
            parent / "Frontier-Engineering",
            parent.parent / "Frontier-Engineering",
            parent / "Evaluator-Discovery" / "Frontier-Engineering",
            parent,
        )
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                continue
            if _is_frontier_root(resolved):
                return resolved

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _python_bin() -> str:
    raw = os.environ.get("QUANTUM_QAOA_PYTHON")
    return str(Path(raw).expanduser()) if raw else sys.executable


def _python_source() -> str:
    if os.environ.get("QUANTUM_QAOA_PYTHON"):
        return "QUANTUM_QAOA_PYTHON"
    return "sys.executable"


def _program_timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        try:
            with open(meta_path, encoding="utf-8") as f:
                return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        except Exception:
            pass
    raw = os.environ.get("QUANTUM_QAOA_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            return int(raw)
        except Exception:
            pass
    return DEFAULT_TIMEOUT_SECONDS


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _maybe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None
    return None


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _numeric_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in metrics.items():
        numeric = _maybe_float(value)
        if numeric is not None:
            out[key] = numeric
    return out


def _should_inline_png() -> bool:
    raw = os.environ.get("QUANTUM_QAOA_INLINE_PNG_BASE64", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_text_artifact(path: Path) -> bool:
    return path.suffix.lower() in {
        ".json",
        ".md",
        ".py",
        ".qasm",
        ".txt",
        ".stdout",
        ".stderr",
        ".log",
        ".yaml",
        ".yml",
    }


def _read_text_snapshot(path: Path) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
    }
    if not path.is_file():
        return item
    size = path.stat().st_size
    item.update(
        {
            "size_bytes": size,
            "sha256": _sha256(path),
            "suffix": path.suffix.lower(),
        }
    )
    if size <= INLINE_TEXT_LIMIT_BYTES:
        try:
            item["content"] = path.read_text(encoding="utf-8-sig")
        except Exception as exc:
            item["content_error"] = str(exc)
    return item


def _artifact_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    inline_png = _should_inline_png()
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        item: dict[str, Any] = {
            "relative_path": rel,
            "suffix": path.suffix.lower(),
            "size_bytes": size,
            "sha256": _sha256(path),
        }
        if _is_text_artifact(path) and size <= INLINE_TEXT_LIMIT_BYTES:
            try:
                item["content"] = path.read_text(encoding="utf-8-sig")
            except Exception as exc:
                item["content_error"] = str(exc)
        elif path.suffix.lower() == ".png" and inline_png and size <= INLINE_BINARY_LIMIT_BYTES:
            item["content_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
        entries.append(item)
    return entries


def _task_context_manifest(task_dir: Path) -> list[dict[str, Any]]:
    if not task_dir.is_dir():
        return []
    wanted: list[Path] = []
    for rel in ("TASK.md", "README.md", "baseline/solve.py", "baseline/structural_optimizer.py"):
        path = task_dir / rel
        if path.is_file():
            wanted.append(path)
    for pattern in ("tests/*.json", "verification/*.py"):
        wanted.extend(sorted(task_dir.glob(pattern)))

    entries: list[dict[str, Any]] = []
    for path in sorted(set(wanted)):
        item = _read_text_snapshot(path)
        item["relative_path"] = path.relative_to(task_dir).as_posix()
        entries.append(item)
    return entries


def _dependency_probe(python_bin: str, env: dict[str, str]) -> dict[str, Any]:
    probe = """
import importlib.util
import json
import platform
import sys

modules = ["qiskit", "qiskit_aer", "mqt", "mqt.bench", "matplotlib"]
payload = {
    "executable": sys.executable,
    "version": sys.version,
    "platform": platform.platform(),
    "modules": {},
}
for name in modules:
    item = {"available": False}
    try:
        spec = importlib.util.find_spec(name)
        item["available"] = spec is not None
        item["origin"] = getattr(spec, "origin", None) if spec is not None else None
        if spec is not None:
            module = __import__(name, fromlist=["__name__"])
            item["version"] = getattr(module, "__version__", None)
    except Exception as exc:
        item["error"] = repr(exc)
    payload["modules"][name] = item
print(json.dumps(payload, ensure_ascii=False))
"""
    try:
        completed = subprocess.run(
            [python_bin, "-c", probe],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "python_bin": python_bin}

    payload: dict[str, Any] = {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "python_bin": python_bin,
    }
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
            if isinstance(parsed, dict):
                payload["parsed"] = parsed
        except Exception as exc:
            payload["parse_error"] = str(exc)
    return payload


def _load_cases(task_dir: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted((task_dir / "tests").glob("case_*.json")):
        try:
            cases.append(_load_json_object(path))
        except Exception as exc:
            cases.append({"path": path.name, "error": str(exc)})
    return cases


def _copy_task_skeleton(frontier_task: Path, task_dir: Path, program_path: Path) -> None:
    (task_dir / "baseline").mkdir(parents=True, exist_ok=True)
    shutil.copytree(frontier_task / "verification", task_dir / "verification")
    shutil.copytree(frontier_task / "tests", task_dir / "tests")
    shutil.copy2(frontier_task / "baseline" / "structural_optimizer.py", task_dir / "baseline" / "structural_optimizer.py")
    shutil.copy2(program_path, task_dir / "baseline" / "solve.py")
    for name in ("TASK.md", "README.md"):
        src = frontier_task / name
        if src.is_file():
            shutil.copy2(src, task_dir / name)


def _extract_metrics(report: dict[str, Any] | None, returncode: int, runtime_s: float) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "combined_score": DEFAULT_SCORE,
        "valid": 0.0,
        "eval_returncode": float(returncode),
        "runtime_s": float(runtime_s),
    }
    if not report:
        return metrics

    summary = report.get("summary")
    if isinstance(summary, dict):
        for key, value in summary.items():
            numeric = _maybe_float(value)
            if numeric is not None:
                metrics[f"summary_{key}"] = numeric

    results = report.get("results")
    if isinstance(results, list):
        metrics["result_count"] = float(len(results))

    score = None
    if isinstance(summary, dict):
        score = _maybe_float(summary.get("avg_candidate_score_0_to_3"))
    if score is None and isinstance(results, list):
        values = []
        for row in results:
            if not isinstance(row, dict):
                continue
            candidate = row.get("candidate")
            if not isinstance(candidate, dict):
                continue
            numeric = _maybe_float(candidate.get("score_0_to_3"))
            if numeric is not None:
                values.append(numeric)
        if values:
            score = sum(values) / len(values)

    if returncode == 0 and score is not None:
        metrics["candidate_score_0_to_3"] = float(score)
        metrics["candidate_score_ratio"] = float(score) / 3.0
        metrics["combined_score"] = float(score)
        metrics["valid"] = 1.0
    return metrics


def _target_breakdown(report: dict[str, Any] | None) -> dict[str, Any]:
    rows = report.get("results") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return {"case_target_rows": [], "target_averages": {}, "case_averages": {}}

    case_target_rows: list[dict[str, Any]] = []
    target_scores: dict[str, list[float]] = {}
    case_scores: dict[str, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        refs = row.get("references") if isinstance(row.get("references"), dict) else {}
        opt0 = refs.get("opt_0", {}) if isinstance(refs.get("opt_0"), dict) else {}
        opt3 = refs.get("opt_3", {}) if isinstance(refs.get("opt_3"), dict) else {}
        candidate_metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
        item = {
            "case_id": row.get("case_id"),
            "target_name": row.get("target_name"),
            "candidate_cost": candidate.get("cost"),
            "candidate_score_0_to_3": candidate.get("score_0_to_3"),
            "candidate_total_runtime_s": candidate.get("total_runtime_s"),
            "candidate_metrics": candidate_metrics,
            "opt0_cost": opt0.get("cost"),
            "opt3_cost": opt3.get("cost"),
            "improvement_vs_opt0": row.get("improvement_vs_opt0"),
            "gap_vs_opt3": row.get("gap_vs_opt3"),
            "artifacts_dir": row.get("artifacts_dir"),
        }
        case_target_rows.append(item)
        score = _maybe_float(candidate.get("score_0_to_3"))
        target_name = str(row.get("target_name", "unknown"))
        case_id = str(row.get("case_id", "unknown"))
        if score is not None:
            target_scores.setdefault(target_name, []).append(score)
            case_scores.setdefault(case_id, []).append(score)

    return {
        "case_target_rows": case_target_rows,
        "target_averages": {key: sum(values) / len(values) for key, values in target_scores.items() if values},
        "case_averages": {key: sum(values) / len(values) for key, values in case_scores.items() if values},
    }


def _format_feedback(metrics: dict[str, Any], report: dict[str, Any] | None, artifacts: dict[str, Any]) -> str:
    breakdown = _target_breakdown(report)
    rows = breakdown["case_target_rows"]
    lines = [
        f"Score: {_as_float(metrics.get('combined_score'), DEFAULT_SCORE):.6f}",
        f"Valid: {_as_float(metrics.get('valid')) > 0.0}",
        f"Runtime seconds: {_as_float(metrics.get('runtime_s')):.2f}",
        f"Case-target pairs: {int(_as_float(metrics.get('result_count')))}",
    ]
    summary = report.get("summary") if isinstance(report, dict) else None
    if isinstance(summary, dict):
        lines.extend(
            [
                f"Avg candidate cost: {_as_float(summary.get('avg_candidate_cost')):.4f}",
                f"Avg opt0 cost: {_as_float(summary.get('avg_opt0_cost')):.4f}",
                f"Avg opt3 cost: {_as_float(summary.get('avg_opt3_cost')):.4f}",
            ]
        )
    for target, value in sorted(breakdown["target_averages"].items()):
        lines.append(f"{target}: avg_score={_as_float(value):.4f}")
    if rows:
        worst = sorted(rows, key=lambda item: _as_float(item.get("candidate_score_0_to_3"), 1e18))[0]
        lines.append(
            "Worst pair: "
            f"{worst.get('case_id')} @ {worst.get('target_name')} "
            f"score={_as_float(worst.get('candidate_score_0_to_3')):.4f}, "
            f"cost={_as_float(worst.get('candidate_cost')):.4f}, "
            f"gap_vs_opt3={_as_float(worst.get('gap_vs_opt3')):.4f}"
        )
    if artifacts.get("error_message"):
        lines.append(f"Error: {artifacts['error_message']}")
    return "\n".join(lines)


def _persist_sidecars(output_dir: Path, metrics: dict[str, Any], artifacts: dict[str, Any], raw_artifacts: dict[str, Any]) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(json.dumps(_json_safe(metrics), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (output_dir / "artifacts.json").write_text(json.dumps(_json_safe(artifacts), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (output_dir / "raw-artifact.json").write_text(json.dumps(_json_safe(raw_artifacts), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass


def _failure_result(message: str, output_dir: Path, details: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = {
        "combined_score": DEFAULT_SCORE,
        "valid": 0.0,
        "failure_reason": message,
    }
    artifacts = {
        "error_message": message,
        "details": details or {},
    }
    raw_artifacts = {
        "benchmark": BENCHMARK,
        "metrics": metrics,
        "artifacts": artifacts,
        "eval_report": None,
        "artifact_manifest": [],
    }
    _persist_sidecars(output_dir, metrics, artifacts, raw_artifacts)
    return {
        "score": DEFAULT_SCORE,
        "is_valid": False,
        "feedback": message,
        "metrics": metrics,
        "construction": {"metrics": metrics, "artifacts": artifacts},
        "raw_artifacts": raw_artifacts,
    }


def evaluate(program_path: str, output_dir: str) -> dict[str, Any]:
    output_dir_p = Path(output_dir).expanduser().resolve()
    output_dir_p.mkdir(parents=True, exist_ok=True)
    program_path_p = Path(program_path).expanduser().resolve()

    if not program_path_p.is_file():
        return _failure_result(f"Candidate program not found: {program_path_p}", output_dir_p)

    try:
        frontier_root = _default_frontier_root()
    except Exception as exc:
        return _failure_result(str(exc), output_dir_p, {"traceback": traceback.format_exc()})

    frontier_task = frontier_root / BENCHMARK_REL
    python_bin = _python_bin()
    python_source = _python_source()
    timeout_s = _program_timeout_seconds()

    report: dict[str, Any] | None = None
    stdout_text = ""
    stderr_text = ""
    returncode = 1
    runtime_s = 0.0
    timed_out = False
    artifact_root: Path | None = None
    temp_task: Path | None = None

    try:
        with tempfile.TemporaryDirectory(prefix="agentic_qaoa_task03_") as tmp:
            temp_task = Path(tmp) / "task_03_cross_target_qaoa"
            temp_task.mkdir(parents=True, exist_ok=True)
            _copy_task_skeleton(frontier_task, temp_task, program_path_p)
            artifact_root = temp_task / "runs" / "unified_eval"
            report_path = temp_task / "eval_report.json"
            cmd = [
                python_bin,
                str(temp_task / "verification" / "evaluate.py"),
                "--json-out",
                str(report_path),
                "--artifact-dir",
                str(artifact_root),
            ]
            env = os.environ.copy()
            pythonpath_parts = [str(temp_task / "verification"), str(temp_task / "baseline")]
            if env.get("PYTHONPATH"):
                pythonpath_parts.append(env["PYTHONPATH"])
            env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
            dependency_probe = _dependency_probe(python_bin, env)
            evaluation_context = {
                "cmd": cmd,
                "cwd": str(temp_task),
                "python_bin": python_bin,
                "python_source": python_source,
                "timeout_s": timeout_s,
                "pythonpath": env["PYTHONPATH"],
                "relevant_env": {
                    key: env.get(key)
                    for key in (
                        "FRONTIER_ENGINEERING_ROOT",
                        "FRONTIER_EVAL_DRIVER_PYTHON",
                        "QUANTUM_QAOA_PYTHON",
                        "QUANTUM_QAOA_TIMEOUT_SECONDS",
                        "QUANTUM_QAOA_INLINE_PNG_BASE64",
                    )
                    if env.get(key)
                },
            }

            start = time.perf_counter()
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(temp_task),
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    env=env,
                )
                returncode = int(completed.returncode)
                stdout_text = completed.stdout or ""
                stderr_text = completed.stderr or ""
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                returncode = 124
                stdout_text = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
                stderr_text = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
                stderr_text += f"\nTimed out after {timeout_s} seconds."
            runtime_s = time.perf_counter() - start

            if report_path.is_file():
                try:
                    report = _load_json_object(report_path)
                except Exception as exc:
                    stderr_text += f"\nFailed to parse eval_report.json: {exc}"

            metrics = _extract_metrics(report, returncode, runtime_s)
            valid = _as_float(metrics.get("valid")) > 0.0
            artifacts: dict[str, Any] = {
                "candidate_path": str(program_path_p),
                "frontier_root": str(frontier_root),
                "temp_task_dir": str(temp_task),
                "python_bin": python_bin,
                "python_source": python_source,
                "eval_returncode": returncode,
                "runtime_s": runtime_s,
                "timed_out": timed_out,
            }
            if not valid:
                if timed_out:
                    artifacts["error_message"] = f"verification/evaluate.py timed out after {timeout_s} seconds"
                elif returncode != 0:
                    artifacts["error_message"] = "verification/evaluate.py returned non-zero exit code"
                elif report is None:
                    artifacts["error_message"] = "missing or invalid eval_report.json"
                else:
                    artifacts["error_message"] = "missing candidate score in eval_report.json"

            breakdown = _target_breakdown(report)
            manifest = _artifact_manifest(artifact_root) if artifact_root is not None else []
            cases = _load_cases(temp_task)
            task_context = _task_context_manifest(temp_task)
            raw_artifacts = {
                "benchmark": BENCHMARK,
                "frontier_root": str(frontier_root),
                "candidate_program": str(program_path_p),
                "candidate_source": _read_text_snapshot(program_path_p),
                "python_bin": python_bin,
                "python_source": python_source,
                "evaluation_context": evaluation_context,
                "dependency_probe": dependency_probe,
                "eval_returncode": returncode,
                "runtime_s": runtime_s,
                "timed_out": timed_out,
                "metrics": metrics,
                "artifacts": artifacts,
                "eval_report": report,
                "eval_stdout": stdout_text,
                "eval_stderr": stderr_text,
                "test_cases": cases,
                "task_context_manifest": task_context,
                "summary": report.get("summary") if isinstance(report, dict) else {},
                "case_target_rows": breakdown["case_target_rows"],
                "target_averages": breakdown["target_averages"],
                "case_averages": breakdown["case_averages"],
                "artifact_manifest": manifest,
                "artifact_manifest_summary": {
                    "file_count": len(manifest),
                    "total_size_bytes": sum(int(item.get("size_bytes", 0)) for item in manifest),
                    "inline_text_file_count": sum(1 for item in manifest if "content" in item),
                    "inline_binary_file_count": sum(1 for item in manifest if "content_base64" in item),
                },
                "task_context_manifest_summary": {
                    "file_count": len(task_context),
                    "total_size_bytes": sum(int(item.get("size_bytes", 0)) for item in task_context),
                    "inline_text_file_count": sum(1 for item in task_context if "content" in item),
                },
            }
            feedback = _format_feedback(metrics, report, artifacts)
            _persist_sidecars(output_dir_p, metrics, artifacts, raw_artifacts)
            return {
                "score": _as_float(metrics.get("combined_score"), DEFAULT_SCORE),
                "is_valid": valid,
                "feedback": feedback,
                "metrics": _numeric_metrics(metrics),
                "construction": {
                    "metrics": metrics,
                    "summary": raw_artifacts["summary"],
                    "target_averages": breakdown["target_averages"],
                    "case_averages": breakdown["case_averages"],
                    "artifact_manifest_summary": raw_artifacts["artifact_manifest_summary"],
                },
                "raw_artifacts": raw_artifacts,
            }
    except Exception as exc:
        details = {
            "traceback": traceback.format_exc(),
            "frontier_root": str(frontier_root),
            "frontier_task": str(frontier_task),
            "temp_task": str(temp_task) if temp_task is not None else None,
        }
        return _failure_result(f"Failed to run Frontier evaluator: {exc}", output_dir_p, details)


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "_smoke"
    result = evaluate(candidate, out)
    print(json.dumps({key: value for key, value in result.items() if key != "raw_artifacts"}, indent=2, ensure_ascii=False))
