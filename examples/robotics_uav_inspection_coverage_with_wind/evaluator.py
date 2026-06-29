"""UAV inspection coverage evaluator for agentic-evolve.

This bridge keeps the Frontier-Engineering task semantics and adds a
stepwise replay trace as the raw artifact consumed by analyzers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import numpy as np

BENCHMARK = "Robotics/UAVInspectionCoverageWithWind"
BENCHMARK_REL = Path("benchmarks") / "Robotics" / "UAVInspectionCoverageWithWind"
VERIFICATION_EVALUATOR_REL = BENCHMARK_REL / "verification" / "evaluator.py"
SCENARIOS_REL = BENCHMARK_REL / "references" / "scenarios.json"
DEFAULT_SCORE = 0.0
DEFAULT_PROGRAM_TIMEOUT_SECONDS = 300


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
        return env_root

    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering", parent):
            if _is_frontier_root(candidate):
                return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _program_timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        try:
            with open(meta_path, encoding="utf-8") as f:
                return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))
        except Exception:
            pass
    return DEFAULT_PROGRAM_TIMEOUT_SECONDS


def _python_bin() -> Path:
    raw = os.environ.get("UAV_INSPECTION_PYTHON") or os.environ.get("FRONTIER_EVAL_DRIVER_PYTHON")
    return Path(raw).expanduser() if raw else Path(sys.executable)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _numeric_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in metrics.items():
        if isinstance(value, bool):
            out[key] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            out[key] = float(value)
    return out


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _wind_velocity(scene: dict[str, Any], t: float) -> np.ndarray:
    wind = scene["wind"]
    base = np.array(wind["base"], dtype=float)
    amp = np.array(wind["amplitude"], dtype=float)
    freq = np.array(wind["frequency"], dtype=float)
    phase = np.array(wind["phase"], dtype=float)
    return base + amp * np.sin(freq * t + phase)


def _in_bounds(pos: np.ndarray, bounds: list[float]) -> bool:
    xmin, xmax, ymin, ymax, zmin, zmax = map(float, bounds)
    return bool(xmin <= pos[0] <= xmax and ymin <= pos[1] <= ymax and zmin <= pos[2] <= zmax)


def _boundary_clearance(pos: np.ndarray, bounds: list[float]) -> float:
    xmin, xmax, ymin, ymax, zmin, zmax = map(float, bounds)
    return float(min(pos[0] - xmin, xmax - pos[0], pos[1] - ymin, ymax - pos[1], pos[2] - zmin, zmax - pos[2]))


def _in_no_fly(pos: np.ndarray, no_fly_zones: list[dict[str, Any]]) -> bool:
    for zone in no_fly_zones:
        if zone.get("type") != "box":
            return True
        pmin = np.array(zone["min"], dtype=float)
        pmax = np.array(zone["max"], dtype=float)
        if np.all(pos >= pmin) and np.all(pos <= pmax):
            return True
    return False


def _no_fly_clearance(pos: np.ndarray, no_fly_zones: list[dict[str, Any]]) -> float | None:
    clearances: list[float] = []
    for zone in no_fly_zones:
        if zone.get("type") != "box":
            continue
        pmin = np.array(zone["min"], dtype=float)
        pmax = np.array(zone["max"], dtype=float)
        outside = np.maximum(np.maximum(pmin - pos, pos - pmax), 0.0)
        outside_dist = float(np.linalg.norm(outside))
        if outside_dist > 0.0:
            clearances.append(outside_dist)
        else:
            inside_margin = float(min(pos[0] - pmin[0], pmax[0] - pos[0], pos[1] - pmin[1], pmax[1] - pos[1], pos[2] - pmin[2], pmax[2] - pos[2]))
            clearances.append(-inside_margin)
    return min(clearances) if clearances else None


def _control_at_time(timestamps: np.ndarray, controls: np.ndarray, t: float) -> np.ndarray:
    idx = int(np.searchsorted(timestamps, t, side="right") - 1)
    idx = max(0, min(idx, len(controls) - 1))
    return controls[idx]


def _dynamic_obstacle_position(obstacle: dict[str, Any], t: float) -> np.ndarray:
    traj = obstacle.get("trajectory", [])
    if not isinstance(traj, list) or len(traj) == 0:
        raise ValueError("invalid_dynamic_obstacle_trajectory")

    t_nodes = np.array([float(node["t"]) for node in traj], dtype=float)
    p_nodes = np.array([node["pos"] for node in traj], dtype=float)
    if p_nodes.ndim != 2 or p_nodes.shape[1] != 3:
        raise ValueError("invalid_dynamic_obstacle_position_shape")
    if not np.all(np.diff(t_nodes) >= 0):
        raise ValueError("non_monotonic_dynamic_obstacle_timestamps")

    if t <= t_nodes[0]:
        return p_nodes[0]
    if t >= t_nodes[-1]:
        return p_nodes[-1]

    idx = int(np.searchsorted(t_nodes, t, side="right") - 1)
    idx = max(0, min(idx, len(t_nodes) - 2))
    t0, t1 = float(t_nodes[idx]), float(t_nodes[idx + 1])
    p0, p1 = p_nodes[idx], p_nodes[idx + 1]
    alpha = 0.0 if t1 <= t0 else float((t - t0) / (t1 - t0))
    return p0 + alpha * (p1 - p0)


def _dynamic_obstacle_status(pos: np.ndarray, scene: dict[str, Any], t: float) -> dict[str, Any]:
    nearest: dict[str, Any] | None = None
    collision = False
    for obs_idx, obs in enumerate(scene.get("dynamic_obstacles", [])):
        radius = float(obs.get("radius", 0.0))
        if radius <= 0.0:
            continue
        center = _dynamic_obstacle_position(obs, t)
        distance = float(np.linalg.norm(pos - center))
        clearance = distance - radius
        if distance <= radius + 1e-9:
            collision = True
        item = {
            "index": obs_idx,
            "center": center.tolist(),
            "radius": radius,
            "distance": distance,
            "clearance": clearance,
        }
        if nearest is None or clearance < float(nearest["clearance"]):
            nearest = item
    return {"collision": collision, "nearest": nearest}


def _validate_entry(scene: dict[str, Any], entry: dict[str, Any]) -> tuple[bool, str, np.ndarray | None, np.ndarray | None]:
    if "timestamps" not in entry or "controls" not in entry:
        return False, "missing_timestamps_or_controls", None, None

    try:
        timestamps = np.array(entry["timestamps"], dtype=float)
        controls = np.array(entry["controls"], dtype=float)
    except Exception:
        return False, "invalid_numeric_format", None, None

    if timestamps.ndim != 1 or len(timestamps) < 2:
        return False, "invalid_timestamps", timestamps, controls
    if controls.ndim != 2 or controls.shape[1] != 3:
        return False, "controls_must_be_Nx3", timestamps, controls
    if len(timestamps) != len(controls):
        return False, "length_mismatch", timestamps, controls
    if abs(float(timestamps[0])) > 1e-12:
        return False, "timestamps_must_start_at_zero", timestamps, controls
    if not np.all(np.diff(timestamps) > 0):
        return False, "timestamps_must_be_strictly_increasing", timestamps, controls
    if float(timestamps[-1]) > float(scene["T_max"]) + 1e-9:
        return False, "timestamps_exceed_T_max", timestamps, controls

    a_max = float(scene["uav"]["a_max"])
    acc_norm = np.linalg.norm(controls, axis=1)
    if np.any(acc_norm > a_max + 1e-9):
        return False, "acceleration_limit_violation", timestamps, controls

    return True, "ok", timestamps, controls


def _failure_scene(scene: dict[str, Any], reason: str, trace: list[dict[str, Any]] | None = None) -> tuple[bool, dict[str, Any]]:
    return False, {
        "success": False,
        "reason": reason,
        "scene_id": scene["id"],
        "trace": trace or [],
        "summary": {"trace_steps": len(trace or [])},
        "first_failure": {"reason": reason, "step_index": len(trace or []) - 1 if trace else None},
    }


def _simulate_scene_with_trace(
    scene: dict[str, Any],
    entry: dict[str, Any],
    dt: float,
    coverage_radius: float,
) -> tuple[bool, dict[str, Any]]:
    ok, reason, timestamps, controls = _validate_entry(scene, entry)
    if not ok or timestamps is None or controls is None:
        return _failure_scene(scene, reason)

    t_max = float(scene["T_max"])
    v_max = float(scene["uav"]["v_max"])
    a_max = float(scene["uav"]["a_max"])
    points = np.array(scene["inspection_points"], dtype=float)

    state = np.array(scene["start"], dtype=float)
    pos = state[:3].copy()
    vel = state[3:].copy()

    trace: list[dict[str, Any]] = []
    visited = np.zeros(len(points), dtype=bool)
    energy = 0.0
    max_speed_norm = float(np.linalg.norm(vel))
    max_acc_norm = 0.0
    min_boundary_clearance = _boundary_clearance(pos, scene["bounds"])
    no_fly_clearance = _no_fly_clearance(pos, scene.get("no_fly_zones", []))
    min_no_fly_clearance = no_fly_clearance
    min_dynamic_clearance: float | None = None

    if not _in_bounds(pos, scene["bounds"]):
        return _failure_scene(scene, "start_out_of_bounds", trace)
    if _in_no_fly(pos, scene.get("no_fly_zones", [])):
        return _failure_scene(scene, "start_in_no_fly_zone", trace)
    start_dyn = _dynamic_obstacle_status(pos, scene, 0.0)
    if start_dyn["nearest"] is not None:
        min_dynamic_clearance = float(start_dyn["nearest"]["clearance"])
    if bool(start_dyn["collision"]):
        return _failure_scene(scene, "collision_dynamic_obstacle", trace)

    t = 0.0
    step_index = 0
    first_failure: dict[str, Any] | None = None

    while t <= t_max + 1e-9:
        dists = np.linalg.norm(points - pos, axis=1)
        in_range = np.where(dists <= coverage_radius)[0].astype(int).tolist()
        previous_visited = visited.copy()
        visited |= dists <= coverage_radius
        covered_this_step = np.where(visited & ~previous_visited)[0].astype(int).tolist()

        dyn_pre = _dynamic_obstacle_status(pos, scene, t)
        if dyn_pre["nearest"] is not None:
            clearance = float(dyn_pre["nearest"]["clearance"])
            min_dynamic_clearance = clearance if min_dynamic_clearance is None else min(min_dynamic_clearance, clearance)

        u = _control_at_time(timestamps, controls, t)
        a_norm = float(np.linalg.norm(u))
        max_acc_norm = max(max_acc_norm, a_norm)
        wind_v = _wind_velocity(scene, t)
        energy_increment = float(np.dot(u, u) * dt)

        step: dict[str, Any] = {
            "step_index": step_index,
            "t": float(t),
            "position": pos.tolist(),
            "velocity": vel.tolist(),
            "control": u.tolist(),
            "wind": wind_v.tolist(),
            "speed_norm": float(np.linalg.norm(vel)),
            "acceleration_norm": a_norm,
            "energy_increment": energy_increment,
            "cumulative_energy_before": float(energy),
            "covered_this_step": covered_this_step,
            "total_visited": int(np.sum(visited)),
            "coverage_ratio_so_far": float(np.mean(visited)) if len(visited) else 1.0,
            "points_in_range": in_range,
            "boundary_clearance": _boundary_clearance(pos, scene["bounds"]),
            "no_fly_clearance": no_fly_clearance,
            "in_bounds": _in_bounds(pos, scene["bounds"]),
            "in_no_fly_zone": _in_no_fly(pos, scene.get("no_fly_zones", [])),
            "dynamic_collision": bool(dyn_pre["collision"]),
            "nearest_dynamic_obstacle": dyn_pre["nearest"],
            "failure_reason": None,
        }

        min_boundary_clearance = min(min_boundary_clearance, float(step["boundary_clearance"]))
        if no_fly_clearance is not None:
            min_no_fly_clearance = no_fly_clearance if min_no_fly_clearance is None else min(min_no_fly_clearance, no_fly_clearance)

        if bool(dyn_pre["collision"]):
            step["failure_reason"] = "collision_dynamic_obstacle"
            trace.append(step)
            first_failure = {"reason": "collision_dynamic_obstacle", "step_index": step_index, "t": float(t)}
            return _finish_failed_scene(scene, trace, first_failure, visited, energy)

        if a_norm > a_max + 1e-9:
            step["failure_reason"] = "acceleration_limit_violation"
            trace.append(step)
            first_failure = {"reason": "acceleration_limit_violation", "step_index": step_index, "t": float(t)}
            return _finish_failed_scene(scene, trace, first_failure, visited, energy)

        energy += energy_increment
        vel = vel + u * dt
        speed_norm = float(np.linalg.norm(vel))
        max_speed_norm = max(max_speed_norm, speed_norm)
        step["velocity_after"] = vel.tolist()
        step["speed_norm_after"] = speed_norm
        step["cumulative_energy_after"] = float(energy)

        if speed_norm > v_max + 1e-9:
            step["failure_reason"] = "speed_limit_violation"
            trace.append(step)
            first_failure = {"reason": "speed_limit_violation", "step_index": step_index, "t": float(t)}
            return _finish_failed_scene(scene, trace, first_failure, visited, energy)

        pos = pos + (vel + wind_v) * dt
        t = t + dt
        post_dyn = _dynamic_obstacle_status(pos, scene, t)
        post_no_fly_clearance = _no_fly_clearance(pos, scene.get("no_fly_zones", []))
        post_boundary_clearance = _boundary_clearance(pos, scene["bounds"])
        min_boundary_clearance = min(min_boundary_clearance, post_boundary_clearance)
        if post_no_fly_clearance is not None:
            min_no_fly_clearance = post_no_fly_clearance if min_no_fly_clearance is None else min(min_no_fly_clearance, post_no_fly_clearance)
        if post_dyn["nearest"] is not None:
            clearance = float(post_dyn["nearest"]["clearance"])
            min_dynamic_clearance = clearance if min_dynamic_clearance is None else min(min_dynamic_clearance, clearance)

        step["position_after"] = pos.tolist()
        step["t_after"] = float(t)
        step["post_boundary_clearance"] = post_boundary_clearance
        step["post_no_fly_clearance"] = post_no_fly_clearance
        step["post_in_bounds"] = _in_bounds(pos, scene["bounds"])
        step["post_in_no_fly_zone"] = _in_no_fly(pos, scene.get("no_fly_zones", []))
        step["post_dynamic_collision"] = bool(post_dyn["collision"])
        step["post_nearest_dynamic_obstacle"] = post_dyn["nearest"]

        if not bool(step["post_in_bounds"]):
            step["failure_reason"] = "out_of_bounds"
        elif bool(step["post_in_no_fly_zone"]):
            step["failure_reason"] = "entered_no_fly_zone"
        elif bool(step["post_dynamic_collision"]):
            step["failure_reason"] = "collision_dynamic_obstacle"

        trace.append(step)
        if step["failure_reason"]:
            first_failure = {"reason": step["failure_reason"], "step_index": step_index, "t": float(t)}
            return _finish_failed_scene(scene, trace, first_failure, visited, energy)

        step_index += 1

    coverage_ratio = float(np.mean(visited)) if len(visited) > 0 else 1.0
    scene_score = coverage_ratio * 100.0 - energy * 0.5
    covered_points = np.where(visited)[0].astype(int).tolist()
    return True, {
        "success": True,
        "scene_id": scene["id"],
        "coverage_ratio": coverage_ratio,
        "energy": float(energy),
        "scene_score": float(scene_score),
        "covered_points": covered_points,
        "covered_count": len(covered_points),
        "point_count": int(len(points)),
        "trace": trace,
        "first_failure": None,
        "summary": {
            "trace_steps": len(trace),
            "max_speed_norm": max_speed_norm,
            "max_speed_ratio": max_speed_norm / max(v_max, 1e-12),
            "max_acceleration_norm": max_acc_norm,
            "max_acceleration_ratio": max_acc_norm / max(a_max, 1e-12),
            "min_boundary_clearance": min_boundary_clearance,
            "min_no_fly_clearance": min_no_fly_clearance,
            "min_dynamic_clearance": min_dynamic_clearance,
            "final_position": pos.tolist(),
            "final_velocity": vel.tolist(),
        },
    }


def _finish_failed_scene(
    scene: dict[str, Any],
    trace: list[dict[str, Any]],
    first_failure: dict[str, Any],
    visited: np.ndarray,
    energy: float,
) -> tuple[bool, dict[str, Any]]:
    coverage_ratio = float(np.mean(visited)) if len(visited) > 0 else 1.0
    covered_points = np.where(visited)[0].astype(int).tolist()
    return False, {
        "success": False,
        "reason": first_failure["reason"],
        "scene_id": scene["id"],
        "coverage_ratio_at_failure": coverage_ratio,
        "energy_at_failure": float(energy),
        "covered_points": covered_points,
        "covered_count": len(covered_points),
        "point_count": int(len(visited)),
        "trace": trace,
        "first_failure": first_failure,
        "summary": _summarize_trace(trace, scene),
    }


def _summarize_trace(trace: list[dict[str, Any]], scene: dict[str, Any]) -> dict[str, Any]:
    if not trace:
        return {"trace_steps": 0}
    v_max = float(scene["uav"]["v_max"])
    a_max = float(scene["uav"]["a_max"])
    speed_values = [_as_float(step.get("speed_norm_after", step.get("speed_norm"))) for step in trace]
    acc_values = [_as_float(step.get("acceleration_norm")) for step in trace]
    boundary_values = [_as_float(step.get("post_boundary_clearance", step.get("boundary_clearance"))) for step in trace]
    no_fly_values = [step.get("post_no_fly_clearance", step.get("no_fly_clearance")) for step in trace]
    no_fly_numeric = [_as_float(value) for value in no_fly_values if value is not None]
    dyn_values: list[float] = []
    for step in trace:
        for key in ("nearest_dynamic_obstacle", "post_nearest_dynamic_obstacle"):
            item = step.get(key)
            if isinstance(item, dict) and item.get("clearance") is not None:
                dyn_values.append(_as_float(item.get("clearance")))
    last = trace[-1]
    return {
        "trace_steps": len(trace),
        "max_speed_norm": max(speed_values) if speed_values else 0.0,
        "max_speed_ratio": (max(speed_values) / max(v_max, 1e-12)) if speed_values else 0.0,
        "max_acceleration_norm": max(acc_values) if acc_values else 0.0,
        "max_acceleration_ratio": (max(acc_values) / max(a_max, 1e-12)) if acc_values else 0.0,
        "min_boundary_clearance": min(boundary_values) if boundary_values else None,
        "min_no_fly_clearance": min(no_fly_numeric) if no_fly_numeric else None,
        "min_dynamic_clearance": min(dyn_values) if dyn_values else None,
        "final_position": last.get("position_after", last.get("position")),
        "final_velocity": last.get("velocity_after", last.get("velocity")),
    }


def _trace_evaluate(submission: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(submission, dict) or not isinstance(submission.get("scenarios"), list):
        return {
            "score": None,
            "feasible": False,
            "details": {"global": {"success": False, "reason": "missing_scenarios_array"}},
            "scenes": [],
        }

    submitted_map = {
        str(entry["id"]): entry
        for entry in submission["scenarios"]
        if isinstance(entry, dict) and "id" in entry
    }

    dt = float(cfg.get("dt", 0.1))
    coverage_radius = float(cfg.get("coverage_radius", 0.5))
    details: dict[str, Any] = {}
    scenes: list[dict[str, Any]] = []
    scores: list[float] = []

    for scene in cfg["scenarios"]:
        scene_id = str(scene["id"])
        if scene_id not in submitted_map:
            info = {
                "success": False,
                "reason": "missing_scene_entry",
                "scene_id": scene_id,
                "trace": [],
                "summary": {"trace_steps": 0},
                "first_failure": {"reason": "missing_scene_entry", "step_index": None},
            }
            details[scene_id] = {"success": False, "reason": "missing_scene_entry"}
            scenes.append(info)
            continue

        success, info = _simulate_scene_with_trace(scene, submitted_map[scene_id], dt, coverage_radius)
        scenes.append(info)
        if success:
            details[scene_id] = {
                "success": True,
                "coverage_ratio": info["coverage_ratio"],
                "energy": info["energy"],
                "scene_score": info["scene_score"],
            }
            scores.append(float(info["scene_score"]))
        else:
            details[scene_id] = {"success": False, "reason": info.get("reason", "scene_failed")}

    feasible = len(scores) == len(cfg["scenarios"])
    score = float(np.mean(scores)) if feasible else None
    return {"score": score, "feasible": feasible, "details": details, "scenes": scenes}


def _load_official_evaluator(frontier_root: Path) -> Any:
    evaluator_path = frontier_root / VERIFICATION_EVALUATOR_REL
    spec = importlib.util.spec_from_file_location("_uav_official_verification_evaluator", evaluator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load official evaluator: {evaluator_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_candidate(program_path: Path, benchmark_dir: Path, python_bin: Path) -> tuple[Path | None, dict[str, Any], str | None]:
    work_dir = Path(tempfile.mkdtemp(prefix="uav_inspection_eval_")).resolve()
    artifacts: dict[str, Any] = {"work_dir": str(work_dir)}
    try:
        baseline_dir = work_dir / "baseline"
        references_dir = work_dir / "references"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(program_path, baseline_dir / "solution.py")
        shutil.copytree(benchmark_dir / "references", references_dir)

        completed = subprocess.run(
            [str(python_bin), str(baseline_dir / "solution.py")],
            cwd=str(baseline_dir),
            capture_output=True,
            text=True,
            timeout=_program_timeout_seconds(),
        )
        artifacts["candidate_stdout"] = completed.stdout[-8000:]
        artifacts["candidate_stderr"] = completed.stderr[-8000:]
        artifacts["candidate_returncode"] = completed.returncode
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            shutil.rmtree(work_dir, ignore_errors=True)
            return None, artifacts, f"Candidate exited with code {completed.returncode}: {detail[-2000:]}"

        submission_path = baseline_dir / "submission.json"
        if not submission_path.is_file():
            shutil.rmtree(work_dir, ignore_errors=True)
            return None, artifacts, "Candidate did not write submission.json"
        return submission_path, artifacts, None
    except subprocess.TimeoutExpired:
        shutil.rmtree(work_dir, ignore_errors=True)
        return None, artifacts, f"Candidate timed out after {_program_timeout_seconds()} seconds"
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        return None, artifacts, f"Failed to run candidate: {exc}"


def _cleanup_submission_workdir(submission_path: Path | None) -> None:
    if submission_path is None:
        return
    try:
        shutil.rmtree(submission_path.parents[1], ignore_errors=True)
    except Exception:
        pass


def _submission_summary(submission: dict[str, Any]) -> dict[str, Any]:
    entries = submission.get("scenarios") if isinstance(submission, dict) else []
    summary: dict[str, Any] = {"scene_count": len(entries) if isinstance(entries, list) else 0, "scenarios": {}}
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            scene_id = str(entry.get("id", "unknown"))
            timestamps = entry.get("timestamps") or []
            controls = entry.get("controls") or []
            summary["scenarios"][scene_id] = {
                "timestamp_count": len(timestamps) if isinstance(timestamps, list) else None,
                "control_count": len(controls) if isinstance(controls, list) else None,
                "first_timestamp": timestamps[0] if isinstance(timestamps, list) and timestamps else None,
                "last_timestamp": timestamps[-1] if isinstance(timestamps, list) and timestamps else None,
            }
    return summary


def _derived_metrics(trace_result: dict[str, Any]) -> dict[str, Any]:
    scenes = list(trace_result.get("scenes") or [])
    summaries = [scene.get("summary") or {} for scene in scenes]
    min_dynamic = [item.get("min_dynamic_clearance") for item in summaries if item.get("min_dynamic_clearance") is not None]
    min_no_fly = [item.get("min_no_fly_clearance") for item in summaries if item.get("min_no_fly_clearance") is not None]
    min_boundary = [item.get("min_boundary_clearance") for item in summaries if item.get("min_boundary_clearance") is not None]
    coverage_values = [scene.get("coverage_ratio", scene.get("coverage_ratio_at_failure")) for scene in scenes]
    coverage_numeric = [_as_float(value) for value in coverage_values if value is not None]
    energy_values = [scene.get("energy", scene.get("energy_at_failure")) for scene in scenes]
    energy_numeric = [_as_float(value) for value in energy_values if value is not None]
    failed = [scene for scene in scenes if not bool(scene.get("success"))]
    return {
        "scene_count": len(scenes),
        "successful_scene_count": sum(1 for scene in scenes if bool(scene.get("success"))),
        "failed_scene_count": len(failed),
        "trace_step_count": sum(int((scene.get("summary") or {}).get("trace_steps", 0)) for scene in scenes),
        "min_coverage_ratio": min(coverage_numeric) if coverage_numeric else 0.0,
        "mean_coverage_ratio": float(np.mean(coverage_numeric)) if coverage_numeric else 0.0,
        "total_energy": sum(energy_numeric),
        "max_speed_ratio": max((_as_float(item.get("max_speed_ratio")) for item in summaries), default=0.0),
        "max_acceleration_ratio": max((_as_float(item.get("max_acceleration_ratio")) for item in summaries), default=0.0),
        "min_boundary_clearance": min(_as_float(value) for value in min_boundary) if min_boundary else None,
        "min_no_fly_clearance": min(_as_float(value) for value in min_no_fly) if min_no_fly else None,
        "min_dynamic_clearance": min(_as_float(value) for value in min_dynamic) if min_dynamic else None,
        "first_failure": failed[0].get("first_failure") if failed else None,
    }


def _persist_sidecars(output_dir: Path, metrics: dict[str, Any], artifacts: dict[str, Any], raw_artifacts: dict[str, Any]) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(json.dumps(_json_safe(metrics), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "artifacts.json").write_text(json.dumps(_json_safe(artifacts), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "raw-artifact.json").write_text(json.dumps(_json_safe(raw_artifacts), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _format_feedback(score: float, valid: bool, metrics: dict[str, Any], raw_artifacts: dict[str, Any]) -> str:
    lines = [
        f"Score: {score:.6f}",
        f"Valid: {valid}",
        f"Feasible scenes: {int(metrics.get('successful_scene_count', 0))}/{int(metrics.get('scene_count', 0))}",
        f"Mean coverage: {_as_float(metrics.get('mean_coverage_ratio')):.3f}",
        f"Total energy: {_as_float(metrics.get('total_energy')):.3f}",
    ]
    for scene in raw_artifacts.get("scenes", []):
        scene_id = scene.get("scene_id")
        if scene.get("success"):
            lines.append(
                f"{scene_id}: coverage={_as_float(scene.get('coverage_ratio')):.3f}, "
                f"energy={_as_float(scene.get('energy')):.3f}, score={_as_float(scene.get('scene_score')):.3f}"
            )
        else:
            lines.append(
                f"{scene_id}: failed ({scene.get('reason')}); "
                f"coverage_at_failure={_as_float(scene.get('coverage_ratio_at_failure')):.3f}"
            )
    first_failure = raw_artifacts.get("derived", {}).get("first_failure")
    if first_failure:
        lines.append(f"First failure: {first_failure}")
    return "\n".join(lines)


def _failure_result(message: str, output_dir: Path, details: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = {
        "combined_score": DEFAULT_SCORE,
        "valid": 0.0,
        "feasible": 0.0,
        "failure_reason": message,
    }
    artifacts = {"error_message": message, "details": details or {}}
    raw_artifacts = {
        "benchmark": BENCHMARK,
        "metrics": metrics,
        "artifacts": artifacts,
        "scenes": [],
        "derived": {"first_failure": {"reason": message}},
    }
    _persist_sidecars(output_dir, metrics, artifacts, raw_artifacts)
    return {
        "score": DEFAULT_SCORE,
        "is_valid": False,
        "feedback": message,
        "metrics": metrics,
        "construction": {"metrics": metrics, "summary": raw_artifacts["derived"]},
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
        benchmark_dir = frontier_root / BENCHMARK_REL
        scenarios_path = frontier_root / SCENARIOS_REL
        python_bin = _python_bin()
        if not benchmark_dir.is_dir():
            return _failure_result(f"Benchmark directory not found: {benchmark_dir}", output_dir_p)
        if not scenarios_path.is_file():
            return _failure_result(f"Scenario file not found: {scenarios_path}", output_dir_p)
        if not python_bin.exists():
            return _failure_result(f"Python executable not found: {python_bin}", output_dir_p)
    except Exception as exc:
        return _failure_result(str(exc), output_dir_p, {"traceback": traceback.format_exc()})

    submission_path: Path | None = None
    try:
        submission_path, run_artifacts, run_error = _run_candidate(program_path_p, benchmark_dir, python_bin)
        if run_error or submission_path is None:
            return _failure_result(run_error or "Candidate run failed", output_dir_p, run_artifacts)

        submission = _load_json_object(submission_path)
        cfg = _load_json_object(scenarios_path)
        trace_result = _trace_evaluate(submission, cfg)

        official_result: dict[str, Any] | None = None
        official_error: str | None = None
        try:
            official_module = _load_official_evaluator(frontier_root)
            official_result = official_module.evaluate(submission_path, scenarios_path)
        except Exception as exc:
            official_error = f"Official evaluator cross-check failed: {exc}"

        feasible = bool(trace_result.get("feasible", False))
        score = _as_float(trace_result.get("score"), DEFAULT_SCORE) if feasible else DEFAULT_SCORE
        derived = _derived_metrics(trace_result)
        metrics: dict[str, Any] = {
            "combined_score": score,
            "coverage_objective": score,
            "valid": 1.0 if feasible else 0.0,
            "feasible": 1.0 if feasible else 0.0,
            **derived,
        }
        for scene in trace_result.get("scenes", []):
            scene_id = str(scene.get("scene_id", "unknown"))
            metrics[f"coverage_{scene_id}"] = _as_float(scene.get("coverage_ratio", scene.get("coverage_ratio_at_failure")))
            metrics[f"energy_{scene_id}"] = _as_float(scene.get("energy", scene.get("energy_at_failure")))
            metrics[f"success_{scene_id}"] = 1.0 if bool(scene.get("success")) else 0.0

        artifacts = {
            **run_artifacts,
            "submission_summary": _submission_summary(submission),
            "official_result": official_result,
            "official_error": official_error,
            "trace_details": trace_result.get("details"),
        }
        raw_artifacts = {
            "benchmark": BENCHMARK,
            "frontier_root": str(frontier_root),
            "candidate_program": str(program_path_p),
            "submission_summary": _submission_summary(submission),
            "metrics": metrics,
            "artifacts": artifacts,
            "official_result": official_result,
            "trace_result": {k: v for k, v in trace_result.items() if k != "scenes"},
            "scenes": trace_result.get("scenes", []),
            "derived": derived,
        }
        construction = {
            "benchmark": BENCHMARK,
            "metrics": metrics,
            "details": trace_result.get("details"),
            "derived": derived,
        }
        feedback = _format_feedback(score, feasible, metrics, raw_artifacts)
        _persist_sidecars(output_dir_p, metrics, artifacts, raw_artifacts)
        return {
            "score": score,
            "is_valid": feasible,
            "feedback": feedback,
            "metrics": _numeric_metrics(metrics),
            "construction": construction,
            "raw_artifacts": raw_artifacts,
        }
    except Exception as exc:
        return _failure_result(f"Evaluation failed: {exc}", output_dir_p, {"traceback": traceback.format_exc()})
    finally:
        _cleanup_submission_workdir(submission_path)


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print(json.dumps(evaluate(candidate, out), ensure_ascii=False, indent=2, default=str))