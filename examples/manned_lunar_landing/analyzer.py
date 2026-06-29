"""Fixed processed-feedback analyzer for the Manned Lunar Landing example."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


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
    ("\u6df1\u7a7a\u673a\u52a8\u4e8b\u4ef6\u68c0\u9a8c\u901a\u8fc7", "deep-space maneuver event check passed"),
    ("\u6df1\u7a7a\u673a\u52a8\u4e8b\u4ef6\u68c0\u9a8c\u672a\u901a\u8fc7", "deep-space maneuver event check failed"),
    ("\u65e0\u52a8\u529b\u6ed1\u7fd4\u6bb5\u68c0\u9a8c\u901a\u8fc7", "unpowered coast segment check passed"),
    ("\u65e0\u52a8\u529b\u6ed1\u7fd4\u6bb5\u68c0\u9a8c\u672a\u901a\u8fc7", "unpowered coast segment check failed"),
    ("\u8865\u7ed9\u98de\u8239\u72b6\u6001\u68c0\u9a8c\u901a\u8fc7", "supply ship state check passed"),
    ("\u8865\u7ed9\u98de\u8239\u72b6\u6001\u68c0\u9a8c\u672a\u901a\u8fc7", "supply ship state check failed"),
    ("\u68c0\u9a8c\u901a\u8fc7", "check passed"),
    ("\u672a\u901a\u8fc7", "check failed"),
    ("\u6709\u8bef", "state error"),
)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _tail_text(value: Any, limit: int = 2500) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[-limit:]


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


def _translate_validator_text(value: Any) -> str:
    text = "" if value is None else str(value)
    if not CJK_RE.search(text) and not UNICODE_ESCAPE_RE.search(text):
        return text
    return "\n".join(_translate_validator_line(line) for line in text.splitlines())


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


def _metrics_from(result: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    metrics = result.get("metrics")
    if isinstance(metrics, dict) and metrics:
        return metrics
    construction = result.get("construction")
    if isinstance(construction, dict) and isinstance(construction.get("metrics"), dict):
        return dict(construction["metrics"])
    if raw and isinstance(raw.get("metrics"), dict):
        return dict(raw["metrics"])
    return {}


def _artifacts_from(result: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw and isinstance(raw.get("artifacts"), dict):
        return dict(raw["artifacts"])
    construction = result.get("construction")
    if isinstance(construction, dict):
        summary = construction.get("summary")
        if isinstance(summary, dict):
            return dict(summary)
    return {}


def _diagnosis(metrics: dict[str, Any], artifacts: dict[str, Any]) -> list[str]:
    diagnosis: list[str] = []
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    payload = _as_float(metrics.get("payload_kg"), 0.0)

    if valid:
        diagnosis.append(f"Validator passed; payload={payload:.4f} kg.")
    else:
        diagnosis.append("Validator did not pass; inspect raw artifacts before tuning payload.")

    if _as_float(metrics.get("timeout"), 0.0) > 0.0:
        diagnosis.append("Evaluation timed out; reduce search cost or improve convergence.")

    program_returncode = metrics.get("program_returncode")
    if program_returncode is not None and _as_float(program_returncode, 0.0) != 0.0:
        diagnosis.append(f"Candidate exited with return code {_as_float(program_returncode):.0f}.")

    octave_returncode = metrics.get("octave_returncode")
    if octave_returncode is not None and _as_float(octave_returncode, 0.0) != 0.0:
        diagnosis.append(f"Octave validator exited with return code {_as_float(octave_returncode):.0f}.")

    error_message = artifacts.get("error_message")
    if error_message:
        diagnosis.append(f"Error: {_tail_text(error_message, 800)}")

    outputlog_tail = artifacts.get("outputlog_tail") or artifacts.get("outputlog.txt")
    if outputlog_tail:
        diagnosis.append("Validator log tail is available in raw artifacts.")

    if not artifacts.get("results.txt") and not artifacts.get("has_results_txt"):
        diagnosis.append("No results.txt artifact was captured; candidate may not be writing the required file.")

    return diagnosis


def _format_feedback(metrics: dict[str, Any], artifacts: dict[str, Any], raw_present: bool) -> str:
    score = _as_float(metrics.get("combined_score"), _as_float(metrics.get("score"), 0.0))
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    payload = _as_float(metrics.get("payload_kg"), 0.0)
    runtime = _as_float(metrics.get("runtime_s"), 0.0)

    lines = [
        f"Score: {score:.4f}",
        f"Valid: {valid}",
        f"Payload kg: {payload:.4f}",
        f"Runtime seconds: {runtime:.2f}",
        f"Raw artifact present: {raw_present}",
    ]
    for item in _diagnosis(metrics, artifacts):
        lines.append(f"- {item}")

    outputlog_tail = artifacts.get("outputlog_tail") or artifacts.get("outputlog.txt")
    if outputlog_tail:
        lines.append("Validator tail:")
        lines.append(_tail_text(_translate_validator_text(outputlog_tail), 1800))

    program_stderr = artifacts.get("program_stderr") or artifacts.get("program_stderr_tail")
    if program_stderr:
        lines.append("Program stderr tail:")
        lines.append(_tail_text(program_stderr, 1000))

    return "\n".join(lines)


def analyze(
    program_path: str,
    output_dir: str,
    result: dict,
    archive_dir: str,
    workspace_dir: str,
) -> dict:
    del program_path, archive_dir, workspace_dir

    raw = _load_raw_artifact(output_dir)
    metrics = _metrics_from(result, raw)
    artifacts = _artifacts_from(result, raw)
    raw_present = raw is not None

    return {
        "processed_feedback": _format_feedback(metrics, artifacts, raw_present),
        "analysis_metrics": {
            "payload_kg": _as_float(metrics.get("payload_kg"), 0.0),
            "valid": 1.0 if _as_float(metrics.get("valid"), 0.0) > 0.0 else 0.0,
            "runtime_s": _as_float(metrics.get("runtime_s"), 0.0),
            "raw_artifact_present": 1.0 if raw_present else 0.0,
        },
        "analysis": {
            "diagnosis": _diagnosis(metrics, artifacts),
            "artifact_keys": sorted(artifacts.keys()),
            "raw_artifact_present": raw_present,
        },
    }
