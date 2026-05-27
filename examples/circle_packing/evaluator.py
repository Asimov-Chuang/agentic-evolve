"""Circle packing evaluator for agentic-evolve."""

from __future__ import annotations

import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import traceback

NUM_CIRCLES = 26
PENALTY_PER_VIOLATION = 10.0


def evaluate(program_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    try:
        centers, radii = _load_program(program_path)
    except Exception as exc:
        return {
            "score": -PENALTY_PER_VIOLATION,
            "is_valid": False,
            "feedback": f"Failed to run program: {exc}",
            "metrics": {"sum_radii": 0.0, "num_circles": 0, "num_violations": 1},
        }

    violations, feedback_lines = _check_constraints(centers, radii)
    sum_radii = float(sum(radii))
    num_violations = len(violations)
    valid = num_violations == 0

    if valid:
        score = sum_radii
    else:
        score = sum_radii - PENALTY_PER_VIOLATION * num_violations - 1.0

    feedback = "Valid packing." if valid else "; ".join(feedback_lines)

    return {
        "score": score,
        "is_valid": valid,
        "feedback": feedback,
        "metrics": {
            "sum_radii": sum_radii,
            "num_circles": len(radii),
            "num_violations": num_violations,
        },
    }


def _load_program(program_path: str):
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        result_file = tmp.name

    script = f"""
import importlib.util
import pickle
import traceback

program_path = {program_path!r}
result_file = {result_file!r}

try:
    spec = importlib.util.spec_from_file_location("program", program_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    centers, radii = module.construct_packing()
    with open(result_file, "wb") as f:
        pickle.dump({{"centers": centers, "radii": radii}}, f)
except Exception:
    with open(result_file, "wb") as f:
        pickle.dump({{"error": traceback.format_exc()}}, f)
"""

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp_script:
        tmp_script.write(script.encode("utf-8"))
        script_path = tmp_script.name

    try:
        completed = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        import pickle

        with open(result_file, "rb") as f:
            payload = pickle.load(f)
        if "error" in payload:
            raise RuntimeError(payload["error"])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Program subprocess failed")
        return payload["centers"], payload["radii"]
    finally:
        os.unlink(result_file)
        os.unlink(script_path)


def _check_constraints(centers, radii):
    violations = []
    feedback = []

    if len(centers) != NUM_CIRCLES or len(radii) != NUM_CIRCLES:
        msg = f"Expected {NUM_CIRCLES} circles, got {len(centers)} centers and {len(radii)} radii"
        violations.append("count")
        feedback.append(msg)
        return violations, feedback

    for i, r in enumerate(radii):
        if r <= 0:
            violations.append(f"nonpositive_radius_{i}")
            feedback.append(f"Circle {i} has non-positive radius {r}")

    for i, (x, y) in enumerate(centers):
        r = radii[i]
        if x - r < -1e-6 or x + r > 1 + 1e-6 or y - r < -1e-6 or y + r > 1 + 1e-6:
            violations.append(f"boundary_{i}")
            feedback.append(f"Circle {i} at ({x:.4f}, {y:.4f}) with r={r:.4f} violates boundary")

    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            dx = centers[i][0] - centers[j][0]
            dy = centers[i][1] - centers[j][1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < radii[i] + radii[j] - 1e-6:
                violations.append(f"overlap_{i}_{j}")
                feedback.append(
                    f"Circles {i} and {j} overlap: dist={dist:.4f}, r_sum={radii[i]+radii[j]:.4f}"
                )

    return violations, feedback


if __name__ == "__main__":
    program = sys.argv[1] if len(sys.argv) > 1 else "program.py"
    result = evaluate(program, ".")
    print(result)
