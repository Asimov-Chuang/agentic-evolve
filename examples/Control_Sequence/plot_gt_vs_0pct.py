"""Plot ground-truth (score_only) vs 0pct-best learning curves and sequence waveforms."""

from __future__ import annotations

import importlib.util
import json
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt

EXAMPLE_DIR = Path(__file__).resolve().parent
OUTPUTS = EXAMPLE_DIR / ".run_configs" / "outputs"
PLOT_DIR = EXAMPLE_DIR / ".run_configs" / "plots"
sys.path.insert(0, str(EXAMPLE_DIR))

from outputs_layout import (  # noqa: E402
    blind_project_name,
    iter_project_dirs,
    nested_project_dir,
    resolve_project_setting,
)
from evaluator_core import hidden_target  # noqa: E402

RUN_IDS = range(2, 8)


def load_sequence(program_path: Path) -> list[float]:
    spec = importlib.util.spec_from_file_location("program", program_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.generate_control_sequence()


def load_best_so_far(traj_path: Path) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for line in traj_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") not in {"submit", "backfill"}:
            continue
        idx = int(row.get("attempt_count", len(points) + 1)) - 1
        points.append((idx, float(row["best_so_far"])))
    return points


def is_complete(traj_path: Path) -> bool:
    completed = False
    for line in traj_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") == "session_end":
            completed = (
                row.get("status") == "completed" and row.get("remaining", 1) == 0
            )
    if completed:
        return True
    pts = load_best_so_far(traj_path)
    return bool(pts) and pts[-1][0] >= 100


def _project_name(setting: str, run_id: int) -> str:
    blind = nested_project_dir(OUTPUTS, setting, blind_project_name(run_id))
    if blind.is_dir():
        return blind_project_name(run_id)
    if setting == "score_only":
        return f"feedback_ablation_score_only_{run_id}"
    return f"feedback_ablation_{setting}_{run_id}"


def _workspace_dir(setting: str, run_id: int) -> Path:
    for name in (blind_project_name(run_id), _project_name(setting, run_id)):
        nested = nested_project_dir(OUTPUTS, setting, name)
        if nested.is_dir():
            return nested
    return nested_project_dir(OUTPUTS, setting, blind_project_name(run_id))


def collect_trajectories(setting: str) -> dict[int, list[tuple[int, float]]]:
    out: dict[int, list[tuple[int, float]]] = {}
    for st, project_dir in iter_project_dirs(OUTPUTS):
        if st != setting:
            continue
        parsed = resolve_project_setting(project_dir.parent.name, project_dir.name)
        if parsed is None:
            continue
        run_id = parsed[1]
        if run_id not in RUN_IDS:
            continue
        traj = project_dir / "score_trajectory.jsonl"
        if traj.is_file() and is_complete(traj):
            out[run_id] = load_best_so_far(traj)
    return out


def mean_curve(curves: dict[int, list[tuple[int, float]]]) -> tuple[list[int], list[float]]:
    if not curves:
        return [], []
    max_len = max(len(c) for c in curves.values())
    xs = list(range(max_len))
    ys = []
    for i in xs:
        vals = [c[i][1] for c in curves.values() if i < len(c)]
        ys.append(statistics.mean(vals))
    return xs, ys


def best_run(curves: dict[int, list[tuple[int, float]]]) -> tuple[int, list[tuple[int, float]]]:
    run_id = max(curves, key=lambda r: curves[r][-1][1])
    return run_id, curves[run_id]


def main() -> None:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    score_only = collect_trajectories("score_only")
    zero_pct = collect_trajectories("0pct")

    if not score_only:
        raise FileNotFoundError("No completed score_only runs (ground-truth feedback) in runs 2-7")
    if not zero_pct:
        raise FileNotFoundError("No completed 0pct runs in runs 2-7")

    gt_x, gt_y = mean_curve(score_only)
    pct_run, pct_curve = best_run(zero_pct)
    pct_x = [p[0] for p in pct_curve]
    pct_y = [p[1] for p in pct_curve]
    pct_final = pct_y[-1]

    # --- Figure 1: learning curves ---
    fig1, ax1 = plt.subplots(figsize=(10, 5.5), constrained_layout=True)

    for run_id, curve in score_only.items():
        ax1.plot(
            [p[0] for p in curve],
            [p[1] for p in curve],
            color="#1f77b4",
            alpha=0.25,
            linewidth=1,
        )
    ax1.plot(
        gt_x,
        gt_y,
        color="#1f77b4",
        linewidth=2.5,
        label=f"Ground truth feedback (score_only mean, n={len(score_only)})",
    )

    for run_id, curve in zero_pct.items():
        if run_id == pct_run:
            continue
        ax1.plot(
            [p[0] for p in curve],
            [p[1] for p in curve],
            color="#d62728",
            alpha=0.2,
            linewidth=1,
        )
    ax1.plot(
        pct_x,
        pct_y,
        color="#d62728",
        linewidth=2.5,
        label=f"0pct best (run {pct_run}, final={pct_final:.4f})",
    )

    ax1.set_title("Best-so-far score trajectory (runs 2-7, 100 submissions)")
    ax1.set_xlabel("Submission index (0 = seed)")
    ax1.set_ylabel("Best score so far (higher is better)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="lower right")

    curve_path = PLOT_DIR / "gt_score_only_vs_0pct_best_curve.png"
    fig1.savefig(curve_path, dpi=150)

    # --- Figure 2: waveform comparison for best 0pct program ---
    run_dir = _workspace_dir("0pct", pct_run)
    program_path = run_dir / "best_program.py"
    if not program_path.is_file():
        program_path = run_dir / "candidate.py"

    gt_seq = hidden_target()
    best_seq = load_sequence(program_path)
    x = list(range(len(gt_seq)))

    fig2, axes = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    ax2 = axes[0]
    ax2.plot(x, gt_seq, label="Hidden target (ground truth sequence)", color="#1f77b4", linewidth=2)
    ax2.plot(
        x,
        best_seq,
        label=f"0pct best program (run {pct_run})",
        color="#d62728",
        linewidth=1.8,
    )
    ax2.set_title("80-step control sequence comparison")
    ax2.set_xlabel("Timestep index")
    ax2.set_ylabel("Control value")
    ax2.set_ylim(-1.05, 1.05)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper right")

    ax3 = axes[1]
    ax3.plot(x, [a - b for a, b in zip(best_seq, gt_seq)], color="#2ca02c", linewidth=1.5)
    ax3.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax3.set_title(f"Residual (0pct best − hidden target), RMSE={(-pct_final):.4f}")
    ax3.set_xlabel("Timestep index")
    ax3.set_ylabel("Error")
    ax3.grid(True, alpha=0.3)

    wave_path = PLOT_DIR / f"gt_target_vs_0pct_best_run{pct_run}_waveform.png"
    fig2.savefig(wave_path, dpi=150)

    print(f"Saved learning curve: {curve_path}")
    print(f"Saved waveform:       {wave_path}")
    print(f"score_only completed runs: {sorted(score_only)}")
    print(f"0pct best run: {pct_run}, final best_so_far={pct_final:.6f}")


if __name__ == "__main__":
    main()
