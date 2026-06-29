"""PRO-mode analyzer for Manned Lunar Landing raw artifacts."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

MU_E = 398600.0
MU_M = 4903.0
LU = 384400.0
TU_SECONDS = math.sqrt(LU**3 / (MU_E + MU_M))
SECONDS_PER_DAY = 86400.0
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
UNICODE_ESCAPE_RE = re.compile(r"\\+u([0-9a-fA-F]{4})")
PAYLOAD_LABEL = "\u98de\u8239\u8fd0\u8f7d\u8d28\u91cf"
CHECK_PASSED = "\u68c0\u9a8c\u901a\u8fc7"
CHECK_FAILED = "\u672a\u901a\u8fc7"
STATE_ERROR = "\u6709\u8bef"
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


def _translate_validator_text(text: Any) -> str:
    raw_text = "" if text is None else str(text)
    if not CJK_RE.search(raw_text) and not UNICODE_ESCAPE_RE.search(raw_text):
        return raw_text
    return "\n".join(_translate_validator_line(line) for line in raw_text.splitlines())


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


def _artifacts_from(raw: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any]:
    if raw and isinstance(raw.get("artifacts"), dict):
        return dict(raw["artifacts"])
    construction = result.get("construction")
    if isinstance(construction, dict) and isinstance(construction.get("summary"), dict):
        return dict(construction["summary"])
    return {}


def _parse_results_text(text: Any) -> list[dict[str, float]]:
    if not text:
        return []
    rows: list[dict[str, float]] = []
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.replace(",", " ").split()
        if len(parts) != 10:
            continue
        try:
            event = int(float(parts[0]))
            values = [float(part) for part in parts[1:]]
        except ValueError:
            continue
        rows.append(
            {
                "event": float(event),
                "time": values[0],
                "x": values[1],
                "y": values[2],
                "vx": values[3],
                "vy": values[4],
                "dvx": values[5],
                "dvy": values[6],
                "mfuel": values[7],
                "mcarry": values[8],
            }
        )
    return rows


def _event_sequence(rows: list[dict[str, float]]) -> list[int]:
    return [int(row["event"]) for row in rows]


def _event_counts(rows: list[dict[str, float]]) -> dict[str, int]:
    return {str(key): value for key, value in sorted(Counter(_event_sequence(rows)).items())}


def _duration_days(rows: list[dict[str, float]]) -> float:
    if not rows:
        return 0.0
    times = [row["time"] for row in rows]
    return (max(times) - min(times)) * TU_SECONDS / SECONDS_PER_DAY


def _nonzero_impulses(rows: list[dict[str, float]], *, include_launch: bool) -> list[float]:
    impulses: list[float] = []
    for row in rows:
        event = int(row["event"])
        if event == -1 or (include_launch and event == 1):
            impulse = math.hypot(row["dvx"], row["dvy"])
            if impulse > 1e-12:
                impulses.append(impulse)
    return impulses


def _first_value_for_event(rows: list[dict[str, float]], event: int, key: str) -> float | None:
    for row in rows:
        if int(row["event"]) == event:
            return row[key]
    return None


def _last_value_for_event(rows: list[dict[str, float]], event: int, key: str) -> float | None:
    for row in reversed(rows):
        if int(row["event"]) == event:
            return row[key]
    return None


def analyze_results(rows: list[dict[str, float]]) -> dict[str, Any]:
    if not rows:
        return {
            "row_count": 0,
            "event_counts": {},
            "event_sequence": [],
            "issues": ["No parseable results.txt rows found."],
        }

    sequence = _event_sequence(rows)
    times = [row["time"] for row in rows]
    fuels = [row["mfuel"] for row in rows]
    payloads = [row["mcarry"] for row in rows]
    maneuver_impulses = _nonzero_impulses(rows, include_launch=False)
    launch_impulses = _nonzero_impulses(rows, include_launch=True)

    issues: list[str] = []
    required_events = {-1, 0, 1, 2, 3, 4}
    missing = sorted(required_events.difference(sequence))
    if missing:
        issues.append(f"Missing required event codes: {missing}.")
    if sequence[-1] != 4:
        issues.append("Final row is not event 4 Earth return.")
    if any(next_time < time for time, next_time in zip(times, times[1:])):
        issues.append("Time sequence is not monotonic.")

    event2_indices = [idx for idx, event in enumerate(sequence) if event == 2]
    event3_indices = [idx for idx, event in enumerate(sequence) if event == 3]
    if len(event2_indices) == 1 and len(event3_indices) == 1:
        if event3_indices[0] - event2_indices[0] != 1:
            issues.append("Events 2 and 3 are not consecutive.")
        stay_days = (rows[event3_indices[0]]["time"] - rows[event2_indices[0]]["time"]) * TU_SECONDS / SECONDS_PER_DAY
        if stay_days < 3.0 or stay_days > 10.0:
            issues.append(f"Lunar stay duration outside [3, 10] days: {stay_days:.3f}.")
    else:
        stay_days = 0.0
        issues.append("Expected exactly one event 2 and one event 3 row.")

    duration_days = _duration_days(rows)
    if duration_days > 100.0:
        issues.append(f"Mission duration exceeds 100 days: {duration_days:.3f}.")

    final_fuel = rows[-1]["mfuel"]
    if final_fuel > 100.0 + 1e-6:
        issues.append(f"Return fuel exceeds 100 kg: {final_fuel:.3f}.")

    return {
        "row_count": len(rows),
        "event_counts": _event_counts(rows),
        "event_sequence": sequence,
        "mission_duration_days": duration_days,
        "lunar_stay_days": stay_days,
        "initial_payload_kg": payloads[0] if payloads else 0.0,
        "arrival_payload_kg": _first_value_for_event(rows, 2, "mcarry"),
        "post_departure_payload_kg": _last_value_for_event(rows, 3, "mcarry"),
        "initial_fuel_kg": fuels[0] if fuels else 0.0,
        "final_fuel_kg": final_fuel,
        "min_fuel_kg": min(fuels) if fuels else 0.0,
        "max_fuel_kg": max(fuels) if fuels else 0.0,
        "maneuver_count": len(maneuver_impulses),
        "spacecraft_total_impulse_vu": sum(maneuver_impulses),
        "launch_plus_spacecraft_total_impulse_vu": sum(launch_impulses),
        "max_single_impulse_vu": max(maneuver_impulses) if maneuver_impulses else 0.0,
        "issues": issues,
    }


def _extract_validator_signals(log_text: Any) -> dict[str, Any]:
    text = "" if log_text is None else str(log_text)
    if not text:
        return {
            "pass_lines": [],
            "failure_lines": [],
            "payload_line": None,
            "tail": "",
        }

    pass_lines: list[str] = []
    failure_lines: list[str] = []
    payload_line: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if PAYLOAD_LABEL in stripped:
            payload_line = _translate_validator_line(stripped)
        if CHECK_PASSED in stripped or "pass" in lowered:
            pass_lines.append(_translate_validator_line(stripped))
        if (
            CHECK_FAILED in stripped
            or STATE_ERROR in stripped
            or "error" in lowered
            or "failed" in lowered
            or "not found" in lowered
            or "timeout" in lowered
        ):
            failure_lines.append(_translate_validator_line(stripped))

    return {
        "pass_lines": pass_lines[-20:],
        "failure_lines": failure_lines[-30:],
        "payload_line": payload_line,
        "tail": _tail_text(_translate_validator_text(text), 4000),
    }


def _format_processed_feedback(
    metrics: dict[str, Any],
    trajectory: dict[str, Any],
    validator: dict[str, Any],
    artifacts: dict[str, Any],
    raw_present: bool,
) -> str:
    valid = _as_float(metrics.get("valid"), 0.0) > 0.0
    score = _as_float(metrics.get("combined_score"), _as_float(metrics.get("score"), 0.0))
    payload = _as_float(metrics.get("payload_kg"), 0.0)
    runtime = _as_float(metrics.get("runtime_s"), 0.0)

    lines = [
        f"Score: {score:.4f}",
        f"Valid: {valid}",
        f"Payload kg: {payload:.4f}",
        f"Runtime seconds: {runtime:.2f}",
        f"Raw artifact present: {raw_present}",
    ]

    if trajectory.get("row_count", 0):
        lines.append(
            "Trajectory: "
            f"rows={trajectory.get('row_count')}, "
            f"duration_days={_as_float(trajectory.get('mission_duration_days')):.3f}, "
            f"stay_days={_as_float(trajectory.get('lunar_stay_days')):.3f}, "
            f"maneuvers={trajectory.get('maneuver_count')}, "
            f"final_fuel={_as_float(trajectory.get('final_fuel_kg')):.3f} kg"
        )
        lines.append(f"Event counts: {trajectory.get('event_counts')}")

    for issue in trajectory.get("issues") or []:
        lines.append(f"- Trajectory issue: {issue}")

    failure_lines = validator.get("failure_lines") or []
    if failure_lines:
        lines.append("Validator failures/signals:")
        for line in failure_lines[-8:]:
            lines.append(f"- {line}")

    if validator.get("payload_line"):
        lines.append(f"Validator payload line: {validator['payload_line']}")

    error_message = artifacts.get("error_message")
    if error_message:
        lines.append(f"Error: {_tail_text(error_message, 1000)}")

    if not failure_lines and validator.get("tail") and not valid:
        lines.append("Validator tail:")
        lines.append(_tail_text(validator["tail"], 1800))

    program_stderr = artifacts.get("program_stderr") or artifacts.get("program_stderr_full")
    if program_stderr:
        lines.append("Program stderr tail:")
        lines.append(_tail_text(program_stderr, 1000))

    octave_stderr = artifacts.get("octave_stderr") or artifacts.get("octave_stderr_full")
    if octave_stderr:
        lines.append("Octave stderr tail:")
        lines.append(_tail_text(octave_stderr, 1000))

    return "\n".join(lines)


def analyze(
    program_path: str,
    output_dir: str,
    result: dict,
    archive_dir: str,
    workspace_dir: str,
) -> dict:
    del program_path, archive_dir, workspace_dir

    raw = load_raw_artifact(output_dir)
    metrics = _metrics_from(result, raw)
    artifacts = _artifacts_from(raw, result)
    results_text = artifacts.get("results.txt")
    outputlog_text = artifacts.get("outputlog.txt") or artifacts.get("outputlog_tail")

    rows = _parse_results_text(results_text)
    trajectory = analyze_results(rows)
    validator = _extract_validator_signals(outputlog_text)
    raw_present = raw is not None

    analysis_metrics = {
        "payload_kg": _as_float(metrics.get("payload_kg"), 0.0),
        "valid": 1.0 if _as_float(metrics.get("valid"), 0.0) > 0.0 else 0.0,
        "runtime_s": _as_float(metrics.get("runtime_s"), 0.0),
        "raw_artifact_present": 1.0 if raw_present else 0.0,
        "trajectory_row_count": float(trajectory.get("row_count", 0) or 0),
        "mission_duration_days": _as_float(trajectory.get("mission_duration_days"), 0.0),
        "lunar_stay_days": _as_float(trajectory.get("lunar_stay_days"), 0.0),
        "final_fuel_kg": _as_float(trajectory.get("final_fuel_kg"), 0.0),
        "maneuver_count": float(trajectory.get("maneuver_count", 0) or 0),
        "spacecraft_total_impulse_vu": _as_float(
            trajectory.get("spacecraft_total_impulse_vu"),
            0.0,
        ),
        "validator_failure_count": float(len(validator.get("failure_lines") or [])),
    }

    return {
        "processed_feedback": _format_processed_feedback(
            metrics,
            trajectory,
            validator,
            artifacts,
            raw_present,
        ),
        "analysis_metrics": analysis_metrics,
        "analysis": {
            "trajectory": trajectory,
            "validator": validator,
            "artifact_keys": sorted(artifacts.keys()),
            "raw_artifact_present": raw_present,
        },
    }
