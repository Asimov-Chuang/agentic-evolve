"""Manned Lunar Landing evaluator for agentic-evolve.

This bridges the Frontier-Engineering benchmark-local evaluator into the
agentic-evolve result shape and exposes Frontier artifacts as raw sidecars.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

BENCHMARK_REL = Path("benchmarks") / "Astrodynamics" / "MannedLunarLanding"
LOCAL_EVALUATOR_REL = BENCHMARK_REL / "frontier_eval" / "evaluator.py"
DEFAULT_SCORE = 0.0
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
UNICODE_ESCAPE_RE = re.compile(r"\\+u([0-9a-fA-F]{4})")
PAYLOAD_LABEL = "\u98de\u8239\u8fd0\u8f7d\u8d28\u91cf"
PAYLOAD_LINE_RE = re.compile(PAYLOAD_LABEL + r"\uff1a\s*([0-9.]+)\s*kg")
VALIDATOR_FIELD_LABELS = {
    "\u5730\u7403\u51fa\u53d1\u65f6\u523b": "Earth departure time",
    "\u8fd4\u56de\u5730\u7403\u65f6\u523b": "Earth return time",
    "\u4efb\u52a1\u5468\u671f": "Mission duration",
    "\u53d1\u5c04\u80fd\u91cf": "Launch energy",
    "\u98de\u8239\u603b\u8d28\u91cf": "Spacecraft total mass",
    "\u521d\u59cb\u71c3\u6599\u8d28\u91cf": "Initial fuel mass",
    "\u71c3\u6599\u603b\u6d88\u8017\u8d28\u91cf": "Total fuel consumed",
    "\u98de\u8239\u8fd0\u8f7d\u8d28\u91cf": "Payload mass",
}
VALIDATOR_TRANSLATIONS = (
    ("\u7ed3\u679c\u6587\u4ef6\u5168\u90e8\u68c0\u9a8c\u901a\u8fc7", "results file validation passed"),
    ("\u5168\u6d41\u7a0b\u5b8c\u6574\u6027\u68c0\u9a8c\u901a\u8fc7", "mission-flow completeness check passed"),
    ("\u5168\u6d41\u7a0b\u5b8c\u6574\u6027\u68c0\u9a8c\u672a\u901a\u8fc7", "mission-flow completeness check failed"),
    ("\u4efb\u52a1\u65f6\u95f4\u8282\u70b9\u68c0\u9a8c\u901a\u8fc7", "mission timing check passed"),
    ("\u4efb\u52a1\u65f6\u95f4\u8282\u70b9\u68c0\u9a8c\u672a\u901a\u8fc7", "mission timing check failed"),
    ("\u5730\u7403\u51fa\u53d1\u72b6\u6001\u68c0\u9a8c\u901a\u8fc7", "Earth-departure state check passed"),
    ("\u5730\u7403\u51fa\u53d1\u72b6\u6001\u68c0\u9a8c\u672a\u901a\u8fc7", "Earth-departure state check failed"),
    ("\u62b5\u8fbe\u6708\u7403\u72b6\u6001\u68c0\u9a8c\u901a\u8fc7", "Moon-arrival state check passed"),
    ("\u62b5\u8fbe\u6708\u7403\u72b6\u6001\u68c0\u9a8c\u672a\u901a\u8fc7", "Moon-arrival state check failed"),
    ("\u79bb\u5f00\u6708\u7403\u72b6\u6001\u68c0\u9a8c\u901a\u8fc7", "Moon-departure state check passed"),
    ("\u79bb\u5f00\u6708\u7403\u72b6\u6001\u68c0\u9a8c\u672a\u901a\u8fc7", "Moon-departure state check failed"),
    ("\u8fd4\u56de\u5730\u7403\u72b6\u6001\u68c0\u9a8c\u901a\u8fc7", "Earth-return state check passed"),
    ("\u8fd4\u56de\u5730\u7403\u72b6\u6001\u68c0\u9a8c\u672a\u901a\u8fc7", "Earth-return state check failed"),
    ("\u901f\u5ea6\u589e\u91cf\u8ba1\u7b97\u68c0\u9a8c\u901a\u8fc7", "delta-v calculation check passed"),
    ("\u901f\u5ea6\u589e\u91cf\u8ba1\u7b97\u68c0\u9a8c\u672a\u901a\u8fc7", "delta-v calculation check failed"),
    ("\u8f68\u9053\u9012\u63a8\u68c0\u9a8c\u901a\u8fc7", "trajectory propagation check passed"),
    ("\u8f68\u9053\u9012\u63a8\u68c0\u9a8c\u672a\u901a\u8fc7", "trajectory propagation check failed"),
    ("\u6df1\u7a7a\u673a\u52a8\u4e8b\u4ef6\u68c0\u9a8c\u901a\u8fc7", "deep-space maneuver event check passed"),
    ("\u6df1\u7a7a\u673a\u52a8\u4e8b\u4ef6\u68c0\u9a8c\u672a\u901a\u8fc7", "deep-space maneuver event check failed"),
    ("\u65e0\u52a8\u529b\u6ed1\u7fd4\u6bb5\u68c0\u9a8c\u901a\u8fc7", "unpowered coast segment check passed"),
    ("\u65e0\u52a8\u529b\u6ed1\u7fd4\u6bb5\u68c0\u9a8c\u672a\u901a\u8fc7", "unpowered coast segment check failed"),
    ("\u8865\u7ed9\u98de\u8239\u72b6\u6001\u68c0\u9a8c\u901a\u8fc7", "supply ship state check passed"),
    ("\u8865\u7ed9\u98de\u8239\u72b6\u6001\u68c0\u9a8c\u672a\u901a\u8fc7", "supply ship state check failed"),
)


@contextmanager
def _utf8_subprocess_context():
    keys = ("PYTHONIOENCODING", "PYTHONUTF8")
    previous = {key: os.environ.get(key) for key in keys}
    original_run = subprocess.run

    def run_with_utf8_text(*popenargs, **kwargs):
        if kwargs.get("text") or kwargs.get("universal_newlines"):
            kwargs.setdefault("encoding", "utf-8")
            kwargs.setdefault("errors", "replace")
        return original_run(*popenargs, **kwargs)

    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
    subprocess.run = run_with_utf8_text
    try:
        yield
    finally:
        subprocess.run = original_run
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _frontier_root_from_env() -> Path | None:
    raw = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _is_frontier_root(path: Path) -> bool:
    return (path / "frontier_eval").is_dir() and (path / "benchmarks").is_dir()


def _default_frontier_root() -> Path:
    env_root = _frontier_root_from_env()
    if env_root is not None:
        return env_root

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates = (
            parent / "Frontier-Engineering",
            parent.parent / "Frontier-Engineering",
            parent,
        )
        for candidate in candidates:
            if _is_frontier_root(candidate) and (candidate / LOCAL_EVALUATOR_REL).is_file():
                return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _load_benchmark_evaluator(frontier_root: Path) -> Callable[..., Any]:
    evaluator_path = (frontier_root / LOCAL_EVALUATOR_REL).resolve()
    if not evaluator_path.is_file():
        raise FileNotFoundError(f"Benchmark evaluator not found: {evaluator_path}")

    spec = importlib.util.spec_from_file_location(
        "_manned_lunar_landing_frontier_evaluator",
        evaluator_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load evaluator module from {evaluator_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluate_fn = getattr(module, "evaluate", None)
    if not callable(evaluate_fn):
        raise RuntimeError(f"Benchmark evaluator has no callable evaluate(): {evaluator_path}")
    return evaluate_fn


def _normalize_frontier_result(result: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if hasattr(result, "metrics") and hasattr(result, "artifacts"):
        return dict(getattr(result, "metrics")), dict(getattr(result, "artifacts") or {})

    if isinstance(result, dict):
        raw_metrics = result.get("metrics")
        raw_artifacts = result.get("artifacts")
        if isinstance(raw_metrics, dict):
            return dict(raw_metrics), dict(raw_artifacts or {})
        return dict(result), {}

    raise TypeError(
        "Benchmark evaluator returned unsupported result type: "
        f"{type(result).__name__}"
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_bool_metric(value: Any) -> bool:
    return _as_float(value, 0.0) > 0.0


def _tail_text(value: Any, limit: int = 2000) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[-limit:]


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _translate_validator_line(line: str) -> str:
    if UNICODE_ESCAPE_RE.search(line):
        line = UNICODE_ESCAPE_RE.sub(lambda match: chr(int(match.group(1), 16)), line)

    if not CJK_RE.search(line):
        return line

    payload_match = PAYLOAD_LINE_RE.search(line)
    if payload_match:
        return f"Payload mass: {payload_match.group(1)} kg"

    translated = line
    for source, replacement in VALIDATOR_TRANSLATIONS:
        translated = translated.replace(source, replacement)

    for source, replacement in VALIDATOR_FIELD_LABELS.items():
        translated = translated.replace(source + "\uff1a", replacement + ": ")

    if CJK_RE.search(translated):
        return "Unmapped validator message omitted."
    return translated


def _translate_validator_text(text: str) -> str:
    if not CJK_RE.search(text) and not UNICODE_ESCAPE_RE.search(text):
        return text
    return "\n".join(_translate_validator_line(line) for line in text.splitlines())


def _sanitize_artifact_text(value: Any) -> Any:
    if isinstance(value, str):
        return _translate_validator_text(value)
    if isinstance(value, list):
        return [_sanitize_artifact_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_artifact_text(item) for key, item in value.items()}
    return value


def _artifact_summary(artifacts: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(artifacts)
    return {
        "artifact_keys": keys,
        "error_message": artifacts.get("error_message"),
        "outputlog_tail": _tail_text(
            artifacts.get("outputlog_tail") or artifacts.get("outputlog.txt"),
            4000,
        ),
        "program_stdout_tail": _tail_text(
            artifacts.get("program_stdout") or artifacts.get("program_stdout_full"),
            2000,
        ),
        "program_stderr_tail": _tail_text(
            artifacts.get("program_stderr") or artifacts.get("program_stderr_full"),
            2000,
        ),
        "octave_stdout_tail": _tail_text(
            artifacts.get("octave_stdout") or artifacts.get("octave_stdout_full"),
            2000,
        ),
        "octave_stderr_tail": _tail_text(
            artifacts.get("octave_stderr") or artifacts.get("octave_stderr_full"),
            2000,
        ),
        "has_results_txt": "results.txt" in artifacts,
        "has_outputlog_txt": "outputlog.txt" in artifacts,
    }


def _format_feedback(score: float, valid: bool, metrics: dict[str, Any], artifacts: dict[str, Any]) -> str:
    payload = _as_float(metrics.get("payload_kg"), 0.0)
    runtime = _as_float(metrics.get("runtime_s"), 0.0)
    lines = [
        f"Score: {score:.4f}",
        f"Valid: {valid}",
        f"Payload kg: {payload:.4f}",
        f"Runtime seconds: {runtime:.2f}",
    ]

    error_message = artifacts.get("error_message")
    if error_message:
        lines.append(f"Error: {_tail_text(error_message, 1000)}")

    outputlog_tail = artifacts.get("outputlog_tail") or artifacts.get("outputlog.txt")
    if outputlog_tail:
        lines.append("Validator tail:")
        lines.append(_tail_text(outputlog_tail, 2000))

    program_stderr = artifacts.get("program_stderr") or artifacts.get("program_stderr_full")
    if program_stderr:
        lines.append("Program stderr tail:")
        lines.append(_tail_text(program_stderr, 1000))

    octave_stderr = artifacts.get("octave_stderr") or artifacts.get("octave_stderr_full")
    if octave_stderr:
        lines.append("Octave stderr tail:")
        lines.append(_tail_text(octave_stderr, 1000))

    return "\n".join(line for line in lines if line is not None)


def _failure_result(message: str, output_dir: Path, details: dict[str, Any] | None = None) -> dict:
    metrics = {
        "combined_score": DEFAULT_SCORE,
        "payload_kg": 0.0,
        "valid": 0.0,
    }
    artifacts = {
        "error_message": message,
        "details": details or {},
    }
    raw_artifacts = {
        "metrics": metrics,
        "artifacts": artifacts,
        "derived": _artifact_summary(artifacts),
    }
    _persist_debug_sidecars(output_dir, metrics, artifacts, raw_artifacts)
    return {
        "score": DEFAULT_SCORE,
        "is_valid": False,
        "feedback": message,
        "metrics": metrics,
        "construction": {
            "metrics": metrics,
            "summary": _artifact_summary(artifacts),
        },
        "raw_artifacts": raw_artifacts,
    }


def _persist_debug_sidecars(
    output_dir: Path,
    metrics: dict[str, Any],
    artifacts: dict[str, Any],
    raw_artifacts: dict[str, Any],
) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(
            json.dumps(_json_safe(metrics), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "artifacts.json").write_text(
            json.dumps(_json_safe(artifacts), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "raw-artifact.json").write_text(
            json.dumps(_json_safe(raw_artifacts), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def evaluate(program_path: str, output_dir: str) -> dict:
    output_dir_p = Path(output_dir).expanduser().resolve()
    output_dir_p.mkdir(parents=True, exist_ok=True)
    program_path_p = Path(program_path).expanduser().resolve()

    if not program_path_p.is_file():
        return _failure_result(f"Candidate program not found: {program_path_p}", output_dir_p)

    try:
        frontier_root = _default_frontier_root()
        evaluate_fn = _load_benchmark_evaluator(frontier_root)
    except Exception as exc:
        return _failure_result(
            str(exc),
            output_dir_p,
            {"traceback": traceback.format_exc()},
        )

    try:
        with _utf8_subprocess_context():
            result = evaluate_fn(str(program_path_p), repo_root=frontier_root)
        metrics, artifacts = _normalize_frontier_result(result)
        artifacts = _sanitize_artifact_text(artifacts)
    except Exception as exc:
        return _failure_result(
            f"Failed to run Frontier evaluator: {exc}",
            output_dir_p,
            {"traceback": traceback.format_exc()},
        )

    valid = _as_bool_metric(metrics.get("valid"))
    score = _as_float(metrics.get("combined_score"), DEFAULT_SCORE)
    if not valid:
        score = DEFAULT_SCORE

    summary = _artifact_summary(artifacts)
    raw_artifacts = {
        "benchmark": "Astrodynamics/MannedLunarLanding",
        "frontier_root": str(frontier_root),
        "candidate_program": str(program_path_p),
        "metrics": metrics,
        "artifacts": artifacts,
        "derived": summary,
    }
    construction = {
        "benchmark": "Astrodynamics/MannedLunarLanding",
        "metrics": metrics,
        "summary": summary,
    }
    feedback = _format_feedback(score, valid, metrics, artifacts)

    _persist_debug_sidecars(output_dir_p, metrics, artifacts, raw_artifacts)

    return {
        "score": score,
        "is_valid": valid,
        "feedback": feedback,
        "metrics": {key: value for key, value in metrics.items() if isinstance(value, (int, float))},
        "construction": construction,
        "raw_artifacts": raw_artifacts,
    }


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print(json.dumps(evaluate(candidate, out), ensure_ascii=False, indent=2, default=str))
