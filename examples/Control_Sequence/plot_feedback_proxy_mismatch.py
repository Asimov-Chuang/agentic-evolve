"""Plot proxy-metric mismatch evidence for cond_a vs cond_e."""

from __future__ import annotations

import importlib.util
import json
import statistics
from pathlib import Path

import matplotlib.pyplot as plt

from evaluator_core import compute_signal_metrics, hidden_target, _rmse

EXAMPLE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = EXAMPLE_DIR / ".run_configs" / "outputs"
PLOT_DIR = EXAMPLE_DIR / ".run_configs" / "plots"

CONDS = {
    "cond_a": {"label": "score only", "color": "#2563eb"},
    "cond_e": {"label": "truthful diagnostics", "color": "#dc2626"},
}
RUN_IDS = range(1, 9)


def load_best_score(run_dir: Path) -> float:
    score = None
    for line in (run_dir / "score_trajectory.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") in {"backfill", "submit"} and "best_so_far" in row:
            score = float(row["best_so_far"])
    if score is None:
        raise ValueError(f"No best score in {run_dir}")
    return score


def load_sequence(program_path: Path) -> list[float]:
    spec = importlib.util.spec_from_file_location("program", program_path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise ImportError(f"Could not load {program_path}")
    spec.loader.exec_module(module)
    return [float(value) for value in module.generate_control_sequence()]


def collect_rows() -> list[dict[str, float | int | str]]:
    target = hidden_target()
    rows: list[dict[str, float | int | str]] = []
    for cond in CONDS:
        for run_id in RUN_IDS:
            run_dir = OUTPUTS_DIR / cond / f"ablation_run_{run_id}"
            if not run_dir.is_dir():
                continue
            sequence = load_sequence(run_dir / "best_program.py")
            metrics = compute_signal_metrics(sequence, target)
            rows.append(
                {
                    "cond": cond,
                    "run_id": run_id,
                    "score": load_best_score(run_dir),
                    "rmse": _rmse(sequence, target),
                    "early_rmse": metrics["early_rmse"],
                    "mid_rmse": metrics["mid_rmse"],
                    "late_rmse": metrics["late_rmse"],
                    "mean_signed_error": metrics["mean_signed_error"],
                    "peak_abs_error": metrics["peak_abs_error"],
                }
            )
    return rows


def plot_proxy_mismatch(rows: list[dict[str, float | int | str]]) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), constrained_layout=True)

    for cond in CONDS:
        cond_rows = [row for row in rows if row["cond"] == cond]
        color = CONDS[cond]["color"]
        label = CONDS[cond]["label"]
        axes[0].scatter(
            [float(row["peak_abs_error"]) for row in cond_rows],
            [float(row["rmse"]) for row in cond_rows],
            color=color,
            s=68,
            alpha=0.85,
            label=label,
        )
        axes[1].scatter(
            [float(row["mid_rmse"]) for row in cond_rows],
            [float(row["rmse"]) for row in cond_rows],
            color=color,
            s=68,
            alpha=0.85,
            label=label,
        )
        for row in cond_rows:
            axes[0].text(
                float(row["peak_abs_error"]) + 0.003,
                float(row["rmse"]),
                str(row["run_id"]),
                fontsize=8,
                color=color,
            )
            axes[1].text(
                float(row["mid_rmse"]) + 0.003,
                float(row["rmse"]),
                str(row["run_id"]),
                fontsize=8,
                color=color,
            )

    axes[0].set_title("Proxy can improve without winning the objective")
    axes[0].set_xlabel("Peak absolute error metric (lower is better)")
    axes[0].set_ylabel("True RMSE (lower is better)")
    axes[0].grid(True, alpha=0.28)
    axes[0].legend(loc="upper left")

    axes[1].set_title("The bottleneck remains the middle segment")
    axes[1].set_xlabel("Middle-third RMSE metric (lower is better)")
    axes[1].set_ylabel("True RMSE (lower is better)")
    axes[1].grid(True, alpha=0.28)
    axes[1].legend(loc="upper left")

    out = PLOT_DIR / "cond_a_vs_cond_e_proxy_mismatch.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def print_summary(rows: list[dict[str, float | int | str]]) -> None:
    for cond in CONDS:
        cond_rows = [row for row in rows if row["cond"] == cond]
        scores = [float(row["score"]) for row in cond_rows]
        rmses = [float(row["rmse"]) for row in cond_rows]
        peak = [float(row["peak_abs_error"]) for row in cond_rows]
        mid = [float(row["mid_rmse"]) for row in cond_rows]
        best = min(cond_rows, key=lambda row: float(row["rmse"]))
        print(
            f"{cond} ({CONDS[cond]['label']}): "
            f"score_mean={statistics.mean(scores):.6f} "
            f"score_stdev={statistics.pstdev(scores):.6f} "
            f"score_best={max(scores):.6f} score_worst={min(scores):.6f} "
            f"rmse_mean={statistics.mean(rmses):.6f} "
            f"peak_mean={statistics.mean(peak):.6f} "
            f"mid_mean={statistics.mean(mid):.6f}"
        )
        print(
            f"  best run {best['run_id']}: rmse={float(best['rmse']):.6f} "
            f"peak={float(best['peak_abs_error']):.6f} "
            f"mid={float(best['mid_rmse']):.6f} "
            f"mean_signed={float(best['mean_signed_error']):.6f}"
        )


def main() -> None:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    rows = collect_rows()
    out = plot_proxy_mismatch(rows)
    print_summary(rows)
    print(f"Saved proxy mismatch plot: {out}")


if __name__ == "__main__":
    main()