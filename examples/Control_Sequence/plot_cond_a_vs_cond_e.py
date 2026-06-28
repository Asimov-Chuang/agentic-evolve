"""Plot score distributions and best-so-far trajectories for cond_a vs cond_e."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt

from evaluator_core import hidden_target

EXAMPLE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = EXAMPLE_DIR / ".run_configs" / "outputs"
PLOT_DIR = EXAMPLE_DIR / ".run_configs" / "plots"

CONDS = {
    "cond_a": {
        "label": "cond_a / score_only",
        "color": "#2563eb",
    },
    "cond_e": {
        "label": "cond_e / 0pct_metric_meanings",
        "color": "#dc2626",
    },
}
RUN_IDS = range(1, 9)


@dataclass
class RunTrajectory:
    cond: str
    run_id: int
    points: list[tuple[int, float]]

    @property
    def final_best(self) -> float:
        return self.points[-1][1]


def load_best_so_far(path: Path) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    seen_attempts: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") not in {"backfill", "submit"}:
            continue
        if "best_so_far" not in row or "attempt_count" not in row:
            continue
        attempt_count = int(row["attempt_count"])
        if attempt_count in seen_attempts:
            continue
        seen_attempts.add(attempt_count)
        points.append((attempt_count, float(row["best_so_far"])))
    return points


def collect_runs() -> list[RunTrajectory]:
    runs: list[RunTrajectory] = []
    missing: list[Path] = []
    for cond in CONDS:
        for run_id in RUN_IDS:
            path = OUTPUTS_DIR / cond / f"ablation_run_{run_id}" / "score_trajectory.jsonl"
            if not path.is_file():
                missing.append(path)
                continue
            points = load_best_so_far(path)
            if points:
                runs.append(RunTrajectory(cond=cond, run_id=run_id, points=points))
    if missing:
        print("Missing trajectory files:")
        for path in missing:
            print(f"  {path}")
    return runs


def plot_best_distribution(runs: list[RunTrajectory]) -> Path:
    fig, ax = plt.subplots(figsize=(8.5, 5.2), constrained_layout=True)

    grouped = {cond: [run.final_best for run in runs if run.cond == cond] for cond in CONDS}
    positions = list(range(1, len(CONDS) + 1))
    values = [grouped[cond] for cond in CONDS]

    box = ax.boxplot(
        values,
        positions=positions,
        widths=0.42,
        patch_artist=True,
        showmeans=True,
        meanline=True,
    )
    for patch, cond in zip(box["boxes"], CONDS):
        patch.set_facecolor(CONDS[cond]["color"])
        patch.set_alpha(0.18)
        patch.set_edgecolor(CONDS[cond]["color"])
    for key in ("whiskers", "caps", "medians", "means"):
        for artist in box[key]:
            artist.set_linewidth(1.4)

    for xpos, cond in zip(positions, CONDS):
        color = CONDS[cond]["color"]
        cond_runs = [run for run in runs if run.cond == cond]
        for index, run in enumerate(cond_runs):
            jitter = (index - (len(cond_runs) - 1) / 2) * 0.035
            ax.scatter(
                xpos + jitter,
                run.final_best,
                color=color,
                edgecolor="white",
                linewidth=0.6,
                s=58,
                zorder=3,
            )
            ax.text(
                xpos + jitter,
                run.final_best,
                str(run.run_id),
                fontsize=7,
                ha="center",
                va="center",
                color="white",
                zorder=4,
            )

    ax.set_title("Final best score distribution across 8 runs")
    ax.set_ylabel("Final best score (higher is better)")
    ax.set_xticks(positions)
    ax.set_xticklabels([CONDS[cond]["label"] for cond in CONDS])
    ax.grid(axis="y", alpha=0.28)

    out = PLOT_DIR / "cond_a_vs_cond_e_best_score_distribution.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def plot_best_so_far_curves(runs: list[RunTrajectory]) -> Path:
    fig, ax = plt.subplots(figsize=(11, 6.2), constrained_layout=True)

    for cond in CONDS:
        color = CONDS[cond]["color"]
        cond_runs = sorted((run for run in runs if run.cond == cond), key=lambda run: run.run_id)
        for run in cond_runs:
            xs = [point[0] for point in run.points]
            ys = [point[1] for point in run.points]
            ax.plot(xs, ys, color=color, alpha=0.52, linewidth=1.35)
            ax.text(
                xs[-1] + 0.5,
                ys[-1],
                f"{run.run_id}",
                color=color,
                fontsize=8,
                va="center",
            )

        if cond_runs:
            ax.plot([], [], color=color, linewidth=2.2, label=CONDS[cond]["label"])

    ax.set_title("Best-so-far score vs attempt count")
    ax.set_xlabel("Attempt count")
    ax.set_ylabel("Best score so far (higher is better)")
    ax.grid(True, alpha=0.28)
    ax.legend(loc="lower right")

    out = PLOT_DIR / "cond_a_vs_cond_e_best_so_far_trajectories.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def load_sequence(program_path: Path) -> list[float]:
    spec = importlib.util.spec_from_file_location("program", program_path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise ImportError(f"Could not load program: {program_path}")
    spec.loader.exec_module(module)
    return [float(value) for value in module.generate_control_sequence()]


def best_run_for_cond(runs: list[RunTrajectory], cond: str) -> RunTrajectory:
    cond_runs = [run for run in runs if run.cond == cond]
    if not cond_runs:
        raise FileNotFoundError(f"No runs found for {cond}")
    return max(cond_runs, key=lambda run: (run.final_best, -run.run_id))


def plot_best_waveforms(runs: list[RunTrajectory]) -> Path:
    target = hidden_target()
    x = list(range(len(target)))

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True, constrained_layout=True)
    ax = axes[0]
    residual_ax = axes[1]

    ax.plot(x, target, color="#111827", linewidth=2.4, label="ground truth")
    residual_ax.axhline(0.0, color="#6b7280", linestyle="--", linewidth=1.0)

    for cond in CONDS:
        best_run = best_run_for_cond(runs, cond)
        run_dir = OUTPUTS_DIR / cond / f"ablation_run_{best_run.run_id}"
        program_path = run_dir / "best_program.py"
        if not program_path.is_file():
            program_path = run_dir / "candidate.py"
        sequence = load_sequence(program_path)
        color = CONDS[cond]["color"]
        label = f"{CONDS[cond]['label']} best run {best_run.run_id} ({best_run.final_best:.4f})"

        ax.plot(x, sequence, color=color, linewidth=1.9, alpha=0.9, label=label)
        residual_ax.plot(
            x,
            [value - truth for value, truth in zip(sequence, target)],
            color=color,
            linewidth=1.5,
            alpha=0.9,
            label=f"{CONDS[cond]['label']} residual",
        )

    ax.set_title("Best fitted sequence vs ground truth")
    ax.set_ylabel("Control value")
    ax.set_ylim(-1.05, 1.05)
    ax.grid(True, alpha=0.28)
    ax.legend(loc="upper right")

    residual_ax.set_title("Residual: fitted sequence - ground truth")
    residual_ax.set_xlabel("Timestep index")
    residual_ax.set_ylabel("Error")
    residual_ax.grid(True, alpha=0.28)
    residual_ax.legend(loc="lower right")

    out = PLOT_DIR / "cond_a_vs_cond_e_best_waveforms_vs_ground_truth.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def main() -> None:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    runs = collect_runs()
    if not runs:
        raise FileNotFoundError(f"No trajectories found under {OUTPUTS_DIR}")

    distribution_path = plot_best_distribution(runs)
    trajectories_path = plot_best_so_far_curves(runs)
    waveforms_path = plot_best_waveforms(runs)

    print(f"Loaded {len(runs)} trajectories")
    for cond in CONDS:
        scores = [run.final_best for run in runs if run.cond == cond]
        if not scores:
            continue
        print(
            f"{CONDS[cond]['label']}: n={len(scores)} "
            f"mean={sum(scores) / len(scores):.6f} "
            f"best={max(scores):.6f} worst={min(scores):.6f}"
        )
    print(f"Saved distribution plot: {distribution_path}")
    print(f"Saved trajectory plot:   {trajectories_path}")
    print(f"Saved waveform plot:     {waveforms_path}")


if __name__ == "__main__":
    main()