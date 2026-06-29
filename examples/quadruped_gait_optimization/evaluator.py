"""QuadrupedGaitOptimization evaluator bridge for agentic-evolve."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

BENCHMARK_REL = Path("benchmarks") / "Robotics" / "QuadrupedGaitOptimization"
FRONTIER_VERIFICATION_REL = BENCHMARK_REL / "verification" / "evaluator.py"
FRONTIER_CONFIG_REL = BENCHMARK_REL / "references" / "gait_config.json"
FRONTIER_MODEL_REL = BENCHMARK_REL / "references" / "ant.xml"
LOCAL_REFERENCES = Path(__file__).resolve().parent / "references"
LOCAL_CONFIG_PATH = LOCAL_REFERENCES / "gait_config.json"
LOCAL_MODEL_PATH = LOCAL_REFERENCES / "ant.xml"
DEFAULT_SCORE = 0.0
PARAM_KEYS = [
    "step_frequency",
    "duty_factor",
    "step_length",
    "step_height",
    "phase_FR",
    "phase_RL",
    "phase_RR",
    "lateral_distance",
]
LEG_ACT = {
    "FL": (2, 3),
    "FR": (4, 5),
    "RL": (6, 7),
    "RR": (0, 1),
}


def _frontier_root_from_env() -> Path | None:
    raw = os.environ.get("FRONTIER_ENGINEERING_ROOT", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _is_frontier_root(path: Path) -> bool:
    return (path / "frontier_eval").is_dir() and (path / FRONTIER_VERIFICATION_REL).is_file()


def _default_frontier_root() -> Path:
    env_root = _frontier_root_from_env()
    if env_root is not None:
        return env_root

    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / "Frontier-Engineering", parent.parent / "Frontier-Engineering"):
            if _is_frontier_root(candidate):
                return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate Frontier-Engineering checkout. "
        "Set FRONTIER_ENGINEERING_ROOT to the repository root."
    )


def _load_frontier_verification(frontier_root: Path) -> Any:
    evaluator_path = (frontier_root / FRONTIER_VERIFICATION_REL).resolve()
    if not evaluator_path.is_file():
        raise FileNotFoundError(f"Frontier verification evaluator not found: {evaluator_path}")
    spec = importlib.util.spec_from_file_location("_quadruped_frontier_verification", evaluator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load Frontier verification evaluator from {evaluator_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _asset_paths(frontier_root: Path) -> tuple[Path, Path]:
    config_path = frontier_root / FRONTIER_CONFIG_REL
    model_path = frontier_root / FRONTIER_MODEL_REL
    return (
        config_path.resolve() if config_path.is_file() else LOCAL_CONFIG_PATH.resolve(),
        model_path.resolve() if model_path.is_file() else LOCAL_MODEL_PATH.resolve(),
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _numeric_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    return {key: float(value) for key, value in metrics.items() if isinstance(value, (int, float))}


def _round_list(values: Any, digits: int = 6) -> list[float]:
    try:
        return [round(float(item), digits) for item in values]
    except Exception:
        return []


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return payload


def _validate_submission(params: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, float] | None, str]:
    out: dict[str, float] = {}
    for key in PARAM_KEYS:
        if key not in params:
            return None, f"missing key '{key}'"
        try:
            out[key] = float(params[key])
        except Exception:
            return None, f"key '{key}' is not numeric"
    ranges = cfg["ranges"]
    for key, bounds in ranges.items():
        lo, hi = float(bounds[0]), float(bounds[1])
        inclusive_hi = key not in {"phase_FR", "phase_RL", "phase_RR"}
        value = out[key]
        ok = lo <= value <= hi if inclusive_hi else lo <= value < hi
        if not ok:
            close = "]" if inclusive_hi else ")"
            return None, f"{key}={value:.4f} out of range [{lo}, {hi}{close}"
    return out, ""


def _leg_phase(t: float, freq: float, offset: float) -> float:
    return (t * freq + offset) % 1.0


def _quat_to_roll_pitch(qw: float, qx: float, qy: float, qz: float) -> tuple[float, float]:
    import numpy as np

    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    roll = np.arctan2(sinr_cosp, cosr_cosp)
    sinp = 2.0 * (qw * qy - qz * qx)
    pitch = np.arcsin(np.clip(sinp, -1.0, 1.0))
    return float(roll), float(pitch)


def _run_candidate(program_path: Path, timeout_s: float, work_dir: Path) -> tuple[dict[str, Any], dict[str, Any], Path | None]:
    artifacts: dict[str, Any] = {"candidate_work_dir": str(work_dir)}
    metrics: dict[str, Any] = {"candidate_returncode": -1.0, "timeout": 0.0}
    sandbox_program = work_dir / "solution.py"
    sandbox_submission = work_dir / "submission.json"
    shutil.copy2(program_path, sandbox_program)
    try:
        completed = subprocess.run(
            [sys.executable, str(sandbox_program)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout_s),
        )
    except subprocess.TimeoutExpired as exc:
        metrics["timeout"] = 1.0
        artifacts["error_message"] = f"candidate timeout: {exc}"
        artifacts["candidate_stdout"] = str(exc.stdout or "")[-8000:]
        artifacts["candidate_stderr"] = str(exc.stderr or "")[-8000:]
        return metrics, artifacts, None

    metrics["candidate_returncode"] = float(completed.returncode)
    artifacts["candidate_stdout"] = (completed.stdout or "")[-8000:]
    artifacts["candidate_stderr"] = (completed.stderr or "")[-8000:]
    if completed.returncode != 0:
        artifacts["error_message"] = "candidate program exited non-zero"
        return metrics, artifacts, None
    if not sandbox_submission.is_file():
        artifacts["error_message"] = "candidate did not generate submission.json"
        return metrics, artifacts, None
    return metrics, artifacts, sandbox_submission


def _compute_derived(
    steps: list[dict[str, Any]],
    events: list[dict[str, Any]],
    params: dict[str, float],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    if not steps:
        return {"step_count": 0, "events": events, "submission": params}

    duration = float(cfg["eval"]["duration_s"])
    initial_x = 0.0
    final_x = _as_float(steps[-1].get("x"))
    distance = final_x - initial_x
    max_abs_roll = max(abs(_as_float(step.get("roll_rad"))) for step in steps)
    max_abs_pitch = max(abs(_as_float(step.get("pitch_rad"))) for step in steps)
    max_abs_force = max(_as_float(step.get("max_abs_actuator_force")) for step in steps)
    max_abs_ctrl = max(_as_float(step.get("max_abs_ctrl")) for step in steps)
    stance_fractions = {
        leg: sum(1 for step in steps if (step.get("stance") or {}).get(leg)) / len(steps)
        for leg in LEG_ACT
    }
    torque_limit = float(cfg["eval"]["torque_limit"])
    saturated_steps = sum(1 for step in steps if _as_float(step.get("max_abs_actuator_force")) > torque_limit + 1e-6)
    attitude_limit = float(cfg["eval"]["pitch_roll_limit_rad"])
    first_crossing: dict[str, Any] | None = None
    for step in steps:
        reason = ""
        if abs(_as_float(step.get("roll_rad"))) > attitude_limit or abs(_as_float(step.get("pitch_rad"))) > attitude_limit:
            reason = "attitude_limit"
        elif _as_float(step.get("max_abs_actuator_force")) > torque_limit + 1e-6:
            reason = "actuator_force_limit"
        if reason:
            first_crossing = {
                "failure_reason": reason,
                "step_index": int(step.get("step_index", 0)),
                "time_s": _as_float(step.get("time_s")),
                "x": _as_float(step.get("x")),
                "roll_rad": _as_float(step.get("roll_rad")),
                "pitch_rad": _as_float(step.get("pitch_rad")),
                "max_abs_actuator_force": _as_float(step.get("max_abs_actuator_force")),
            }
            break

    progress_samples = []
    for target_t in [0.0, 2.0, 4.0, 6.0, duration]:
        nearest = min(steps, key=lambda step: abs(_as_float(step.get("time_s")) - target_t))
        progress_samples.append(
            {
                "time_s": _as_float(nearest.get("time_s")),
                "x": _as_float(nearest.get("x")),
                "progress_m": _as_float(nearest.get("x")) - initial_x,
                "z": _as_float(nearest.get("z")),
            }
        )

    return {
        "step_count": len(steps),
        "events": events,
        "submission": params,
        "final_distance_m": distance,
        "derived_speed_mps": distance / duration if duration > 0 else 0.0,
        "max_abs_roll_rad": max_abs_roll,
        "max_abs_pitch_rad": max_abs_pitch,
        "max_abs_actuator_force": max_abs_force,
        "max_abs_ctrl": max_abs_ctrl,
        "min_body_height_m": min(_as_float(step.get("z")) for step in steps),
        "max_abs_lateral_y_m": max(abs(_as_float(step.get("y"))) for step in steps),
        "avg_forward_velocity_mps": sum(_as_float(step.get("forward_velocity_mps")) for step in steps) / len(steps),
        "avg_abs_ctrl": sum(_as_float(step.get("mean_abs_ctrl")) for step in steps) / len(steps),
        "torque_saturation_fraction": saturated_steps / len(steps),
        "stance_fractions": stance_fractions,
        "phase_offsets": {
            "FL": 0.0,
            "FR": params.get("phase_FR", 0.0),
            "RL": params.get("phase_RL", 0.0),
            "RR": params.get("phase_RR", 0.0),
        },
        "first_constraint_crossing": first_crossing,
        "progress_samples": progress_samples,
    }


def _trace_rollout(submission_path: Path, config_path: Path, model_path: Path) -> dict[str, Any]:
    import mujoco
    import numpy as np

    cfg = _load_json(config_path)
    raw_params = _load_json(submission_path)
    params, validation_error = _validate_submission(raw_params, cfg)
    if params is None:
        event = {"event": "failure", "failure_reason": validation_error, "step_index": 0, "time_s": 0.0}
        return {
            "submission": raw_params,
            "metrics": {"valid": 0.0, "feasible": 0.0, "combined_score": 0.0, "trace_failure_reason": validation_error},
            "trajectory": {"steps": [], "events": [event]},
            "derived": {"step_count": 0, "events": [event], "submission": raw_params},
        }

    duration = float(cfg["eval"]["duration_s"])
    torque_limit = float(cfg["eval"]["torque_limit"])
    attitude_limit = float(cfg["eval"]["pitch_roll_limit_rad"])
    min_distance = float(cfg["eval"]["min_distance_m"])
    kp = float(cfg["eval"]["control_kp"])
    kd = float(cfg["eval"]["control_kd"])

    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    ctrl_min = np.full(model.nu, -1.0)
    ctrl_max = np.full(model.nu, 1.0)
    if model.actuator_ctrllimited is not None and np.any(model.actuator_ctrllimited):
        ctrl_min = model.actuator_ctrlrange[:, 0].copy()
        ctrl_max = model.actuator_ctrlrange[:, 1].copy()

    freq = params["step_frequency"]
    duty = params["duty_factor"]
    step_len = params["step_length"]
    step_h = params["step_height"]
    lateral = params["lateral_distance"]
    phase_leg = {"FL": 0.0, "FR": params["phase_FR"], "RL": params["phase_RL"], "RR": params["phase_RR"]}
    hip_amp = np.clip(2.0 * step_len, 0.08, 0.65)
    knee_amp = np.clip(3.0 * step_h, 0.05, 0.85)
    lateral_bias = np.clip((lateral - 0.14) * 4.0, -0.25, 0.25)

    x0 = float(data.qpos[0])
    previous_x = x0
    n_steps = int(duration / model.opt.timestep)
    steps: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    failure_reason = ""

    for step_index in range(n_steps):
        t = step_index * model.opt.timestep
        qj = data.qpos[7:15]
        vj = data.qvel[6:14]
        target = np.zeros(8, dtype=float)
        phases: dict[str, float] = {}
        stance: dict[str, bool] = {}

        for leg_name, (hip_idx, knee_idx) in LEG_ACT.items():
            ph = _leg_phase(t, freq, phase_leg[leg_name])
            in_stance = ph < duty
            swing = 0.0 if in_stance else (ph - duty) / (1.0 - duty)
            stance_wave = np.sin(2.0 * np.pi * ph)
            swing_wave = np.sin(np.pi * swing)
            sign = 1.0 if leg_name in {"FL", "RR"} else -1.0
            hip_target = sign * hip_amp * stance_wave + (lateral_bias if leg_name in {"FL", "RL"} else -lateral_bias)
            knee_target = -0.45 + knee_amp * swing_wave
            target[hip_idx] = hip_target
            target[knee_idx] = knee_target
            phases[leg_name] = round(float(ph), 6)
            stance[leg_name] = bool(in_stance)

        ctrl = kp * (target - qj) - kd * vj
        ctrl = np.clip(ctrl, ctrl_min, ctrl_max)
        data.ctrl[:] = ctrl
        mujoco.mj_step(model, data)

        qw, qx, qy, qz = map(float, data.qpos[3:7])
        roll, pitch = _quat_to_roll_pitch(qw, qx, qy, qz)
        x = float(data.qpos[0])
        max_abs_force = float(np.max(np.abs(data.actuator_force))) if len(data.actuator_force) else 0.0
        step = {
            "step_index": step_index,
            "time_s": round(float(t), 6),
            "x": round(x, 6),
            "y": round(float(data.qpos[1]), 6),
            "z": round(float(data.qpos[2]), 6),
            "forward_velocity_mps": round((x - previous_x) / float(model.opt.timestep), 6),
            "roll_rad": round(float(roll), 6),
            "pitch_rad": round(float(pitch), 6),
            "orientation_quat_wxyz": _round_list(data.qpos[3:7], 6),
            "qpos": _round_list(data.qpos, 6),
            "qvel": _round_list(data.qvel, 6),
            "target": _round_list(target, 6),
            "ctrl": _round_list(ctrl, 6),
            "actuator_force": _round_list(data.actuator_force, 6),
            "max_abs_ctrl": round(float(np.max(np.abs(ctrl))) if len(ctrl) else 0.0, 6),
            "mean_abs_ctrl": round(float(np.mean(np.abs(ctrl))) if len(ctrl) else 0.0, 6),
            "max_abs_actuator_force": round(max_abs_force, 6),
            "phase": phases,
            "stance": stance,
        }
        previous_x = x

        if abs(roll) > attitude_limit or abs(pitch) > attitude_limit:
            failure_reason = "attitude_limit"
            step["event"] = failure_reason
            steps.append(step)
            events.append({"event": "failure", "failure_reason": failure_reason, "step_index": step_index, "time_s": float(t), "roll_rad": roll, "pitch_rad": pitch})
            break
        if max_abs_force > torque_limit + 1e-6:
            failure_reason = "actuator_force_limit"
            step["event"] = failure_reason
            steps.append(step)
            events.append({"event": "failure", "failure_reason": failure_reason, "step_index": step_index, "time_s": float(t), "max_abs_actuator_force": max_abs_force})
            break
        steps.append(step)

    distance = float(data.qpos[0] - x0)
    if not failure_reason and distance < min_distance:
        failure_reason = "insufficient_progress"
        events.append({"event": "failure", "failure_reason": failure_reason, "step_index": len(steps), "time_s": float(len(steps) * model.opt.timestep), "distance_m": distance})
    elif not failure_reason:
        events.append({"event": "success", "failure_reason": "", "step_index": len(steps), "time_s": float(len(steps) * model.opt.timestep), "distance_m": distance})

    feasible = not failure_reason
    speed = distance / duration if feasible and duration > 0 else 0.0
    derived = _compute_derived(steps, events, params, cfg)
    return {
        "submission": params,
        "metrics": {
            "valid": 1.0 if feasible else 0.0,
            "feasible": 1.0 if feasible else 0.0,
            "combined_score": float(speed),
            "speed_mps": float(speed) if feasible else 0.0,
            "trace_failure_reason": failure_reason,
            "trace_distance_m": distance,
            "trace_duration_s": duration,
            "trace_step_count": float(len(steps)),
        },
        "trajectory": {"steps": steps, "events": events},
        "derived": derived,
    }


def _run_official_verification(frontier: Any, submission_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    start = time.time()
    metrics: dict[str, Any] = {"combined_score": 0.0, "valid": 0.0, "feasible": 0.0, "runtime_s": 0.0}
    artifacts: dict[str, Any] = {"local_evaluator_path": str(Path(frontier.__file__).resolve())}
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            speed = float(frontier.evaluate(submission_path))
        feasible = speed > 0.0
        metrics["feasible"] = 1.0 if feasible else 0.0
        metrics["valid"] = 1.0 if feasible else 0.0
        metrics["speed_mps"] = speed if feasible else 0.0
        metrics["combined_score"] = speed if feasible else 0.0
        if not feasible:
            artifacts["error_message"] = "infeasible gait"
    except Exception as exc:
        artifacts["error_message"] = f"official verification failed: {exc}"
        artifacts["traceback"] = traceback.format_exc()
    artifacts["official_stdout"] = stdout.getvalue()[-8000:]
    artifacts["official_stderr"] = stderr.getvalue()[-8000:]
    metrics["runtime_s"] = float(time.time() - start)
    return metrics, artifacts


def _persist_sidecars(output_dir: Path, metrics: dict[str, Any], artifacts: dict[str, Any], raw_artifacts: dict[str, Any]) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(json.dumps(_json_safe(metrics), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "artifacts.json").write_text(json.dumps(_json_safe(artifacts), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "raw-artifact.json").write_text(json.dumps(_json_safe(raw_artifacts), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _failure_result(message: str, output_dir: Path, details: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = {"combined_score": DEFAULT_SCORE, "valid": 0.0, "feasible": 0.0, "failure_reason": message}
    artifacts = {"error_message": message, "details": details or {}}
    raw_artifacts = {
        "benchmark": "Robotics/QuadrupedGaitOptimization",
        "metrics": metrics,
        "artifacts": artifacts,
        "trajectory": {"steps": [], "events": []},
        "derived": {},
    }
    _persist_sidecars(output_dir, metrics, artifacts, raw_artifacts)
    return {
        "score": DEFAULT_SCORE,
        "is_valid": False,
        "feedback": message,
        "metrics": metrics,
        "construction": {"metrics": metrics, "summary": {"error_message": message}},
        "raw_artifacts": raw_artifacts,
    }


def _format_feedback(score: float, valid: bool, metrics: dict[str, Any], artifacts: dict[str, Any], raw: dict[str, Any]) -> str:
    derived = raw.get("derived") or {}
    lines = [
        f"Score: {score:.6f}",
        f"Valid: {valid}",
        f"Speed m/s: {_as_float(metrics.get('speed_mps'), score):.6f}",
        f"Feasible: {_as_float(metrics.get('feasible')) > 0.0}",
        f"Runtime seconds: {_as_float(metrics.get('runtime_s')):.2f}",
        f"Trace steps: {int(_as_float(derived.get('step_count')))}",
        f"Final distance m: {_as_float(derived.get('final_distance_m')):.4f}",
        f"Max abs roll rad: {_as_float(derived.get('max_abs_roll_rad')):.4f}",
        f"Max abs pitch rad: {_as_float(derived.get('max_abs_pitch_rad')):.4f}",
        f"Max abs actuator force: {_as_float(derived.get('max_abs_actuator_force')):.4f}",
    ]
    error = artifacts.get("error_message") or metrics.get("failure_reason")
    if error:
        lines.append(f"Error: {error}")
    return "\n".join(lines)


def _build_result(
    output_dir: Path,
    score: float,
    valid: bool,
    metrics: dict[str, Any],
    artifacts: dict[str, Any],
    raw_artifacts: dict[str, Any],
) -> dict[str, Any]:
    construction = {
        "benchmark": "Robotics/QuadrupedGaitOptimization",
        "metrics": metrics,
        "summary": {
            "step_count": int(_as_float((raw_artifacts.get("derived") or {}).get("step_count"))),
            "final_distance_m": _as_float((raw_artifacts.get("derived") or {}).get("final_distance_m")),
            "max_abs_roll_rad": _as_float((raw_artifacts.get("derived") or {}).get("max_abs_roll_rad")),
            "max_abs_pitch_rad": _as_float((raw_artifacts.get("derived") or {}).get("max_abs_pitch_rad")),
            "max_abs_actuator_force": _as_float((raw_artifacts.get("derived") or {}).get("max_abs_actuator_force")),
            "error_message": artifacts.get("error_message", ""),
        },
        "derived": raw_artifacts.get("derived", {}),
    }
    feedback = _format_feedback(score, valid, metrics, artifacts, raw_artifacts)
    _persist_sidecars(output_dir, metrics, artifacts, raw_artifacts)
    return {
        "score": score,
        "is_valid": valid,
        "feedback": feedback,
        "metrics": _numeric_metrics(metrics),
        "construction": construction,
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
        frontier_verification = _load_frontier_verification(frontier_root)
        config_path, model_path = _asset_paths(frontier_root)
    except Exception as exc:
        return _failure_result(str(exc), output_dir_p, {"traceback": traceback.format_exc()})

    timeout_s = float(os.environ.get("FRONTIER_EVAL_EVALUATOR_TIMEOUT_S", "240") or "240")
    work_dir = Path(tempfile.mkdtemp(prefix="ae_quadruped_volatile_")).resolve()
    try:
        candidate_metrics, candidate_artifacts, submission_path = _run_candidate(program_path_p, timeout_s, work_dir)
        if submission_path is None:
            metrics = {"combined_score": 0.0, "valid": 0.0, "feasible": 0.0, **candidate_metrics}
            artifacts = {"frontier_root": str(frontier_root), **candidate_artifacts}
            raw_artifacts = {
                "benchmark": "Robotics/QuadrupedGaitOptimization",
                "frontier_root": str(frontier_root),
                "candidate_program": str(program_path_p),
                "config_path": str(config_path),
                "model_path": str(model_path),
                "submission": {},
                "metrics": metrics,
                "artifacts": artifacts,
                "trajectory": {"steps": [], "events": []},
                "derived": {},
            }
            return _build_result(output_dir_p, 0.0, False, metrics, artifacts, raw_artifacts)

        official_metrics, official_artifacts = _run_official_verification(frontier_verification, submission_path)
        try:
            trace = _trace_rollout(submission_path, config_path, model_path)
        except Exception as exc:
            trace = {
                "submission": {},
                "metrics": {},
                "trajectory": {"steps": [], "events": []},
                "derived": {},
                "traceback": traceback.format_exc(),
            }
            official_artifacts["trace_artifact_warning"] = f"failed to build MuJoCo trace: {exc}"

        metrics = {**candidate_metrics, **official_metrics}
        metrics["candidate_path"] = str(program_path_p)
        metrics["config_path"] = str(config_path)
        metrics["model_path"] = str(model_path)
        metrics["trace_speed_mps"] = _as_float((trace.get("metrics") or {}).get("speed_mps"), 0.0)
        metrics["trace_distance_m"] = _as_float((trace.get("derived") or {}).get("final_distance_m"), 0.0)
        metrics["trace_step_count"] = _as_float((trace.get("derived") or {}).get("step_count"), 0.0)

        artifacts = {
            "frontier_root": str(frontier_root),
            "candidate_path": str(program_path_p),
            "submission_path": str(submission_path),
            **candidate_artifacts,
            **official_artifacts,
        }
        score = _as_float(metrics.get("combined_score"), 0.0)
        valid = _as_float(metrics.get("valid"), 0.0) > 0.0
        if not valid:
            score = 0.0

        raw_artifacts = {
            "benchmark": "Robotics/QuadrupedGaitOptimization",
            "frontier_root": str(frontier_root),
            "candidate_program": str(program_path_p),
            "config_path": str(config_path),
            "model_path": str(model_path),
            "submission": trace.get("submission", {}),
            "metrics": metrics,
            "trace_metrics": trace.get("metrics", {}),
            "artifacts": artifacts,
            "trajectory": trace.get("trajectory", {"steps": [], "events": []}),
            "derived": trace.get("derived", {}),
        }
        return _build_result(output_dir_p, score, valid, metrics, artifacts, raw_artifacts)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    result = evaluate(candidate, out)
    printable = dict(result)
    raw = printable.pop("raw_artifacts", {})
    trajectory = raw.get("trajectory", {}) if isinstance(raw, dict) else {}
    printable["raw_artifacts_summary"] = {
        "present": bool(raw),
        "step_count": len(trajectory.get("steps") or []),
        "event_count": len(trajectory.get("events") or []),
        "derived_keys": sorted((raw.get("derived") or {}).keys()) if isinstance(raw, dict) else [],
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
