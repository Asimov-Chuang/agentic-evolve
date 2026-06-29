from __future__ import annotations

import json
from pathlib import Path

from agentic_evolve.archive import Archive, read_improvement_baseline


def _raw_artifacts_enabled(workspace: Path) -> bool:
    """True when this workspace stores or already has per-attempt raw-artifact.json."""
    meta_path = workspace / "workspace_meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("store_raw_artifacts") is False:
                return False
            if meta.get("store_raw_artifacts"):
                return True
        except (OSError, json.JSONDecodeError):
            pass
    archive_dir = workspace / "archive"
    if archive_dir.is_dir():
        for attempt_dir in archive_dir.glob("attempt_*"):
            if (attempt_dir / "raw-artifact.json").is_file():
                return True
    return False


def build_prompt(
    archive: Archive,
    workspace_dir: Path,
    max_improvements: int,
    *,
    resumed: bool = False,
    hidden_testdata: bool = False,
    agent_readable_evaluator: bool = True,
    prompt_history_top_n: int = 10,
    prompt_history_recent_n: int = 10,
    prompt_history_max_feedback_chars: int = 400,
    mode: str = "standard",
    target_score: float | None = None,
    maximize: bool = True,
) -> str:
    workspace = workspace_dir.resolve()
    pro_mode = mode == "pro"
    raw_artifacts = _raw_artifacts_enabled(workspace) and not hidden_testdata
    analyzer_enabled = (workspace / "analyzer.py").is_file()
    best = archive.best()
    remaining = archive.remaining_improvements(
        max_improvements, baseline=read_improvement_baseline(workspace)
    )

    if best:
        best_score = f"{best.score:.6f}"
        best_id = best.attempt_id
    else:
        best_score = "N/A"
        best_id = "none"

    total_attempts = archive.submission_count()
    summary_attempts = archive.attempts_for_prompt(
        top_n=prompt_history_top_n,
        recent_n=prompt_history_recent_n,
    )
    history = (
        "\n".join(
            archive.summary_lines(
                top_n=prompt_history_top_n,
                recent_n=prompt_history_recent_n,
                max_feedback_chars=prompt_history_max_feedback_chars,
            )
        )
        or "(no attempts yet)"
    )
    if (
        (prompt_history_top_n > 0 or prompt_history_recent_n > 0)
        and len(summary_attempts) < total_attempts
    ):
        history = (
            f"(Showing {len(summary_attempts)} of {total_attempts} attempts: "
            f"top {prompt_history_top_n} by score + {prompt_history_recent_n} most recent; "
            "read archive/attempt_NNNN/ for full history.)\n"
            + history
        )
    resume_note = (
        "This is a RESUMED run. Continue from the existing archive; do not restart from scratch."
        if resumed
        else "This is a new run starting from the seeded archive."
    )

    if remaining <= 0:
        budget_note = (
            f"Improvement budget is exhausted ({max_improvements} submissions after seed). "
            "Do not call submit.py unless the user extends max_improvements in config."
        )
    else:
        budget_note = (
            f"Improvement budget: {remaining} submission(s) remaining "
            f"(max {max_improvements} after the seed)."
        )

    target_note = ""
    target_rule = ""
    target_status = ""
    if target_score is not None:
        direction = "at least" if maximize else "at most"
        comparison = ">=" if maximize else "<="
        target_note = (
            f"Target score: {direction} {target_score:g} "
            f"(score {comparison} {target_score:g}). Treat this as the run goal.\n"
        )
        target_rule = (
            f"- Keep iterating toward the target score ({comparison} {target_score:g}); "
            "do not stop early just because the score improves but remains short of the target.\n"
        )
        if best and ((maximize and best.score >= target_score) or (not maximize and best.score <= target_score)):
            target_status = f"Target status: reached by {best_id}.\n"
        else:
            target_status = "Target status: not reached yet. Keep searching for improvements within the budget.\n"

    if pro_mode:
        analyzer_file = (
            "- analyzer.py — processed-feedback logic (every iteration must consider whether to evolve it; reads raw-artifact.json)\n"
        )
    elif analyzer_enabled:
        analyzer_file = "- analyzer.py — optional processed-feedback logic (editable; improve if useful)\n"
    else:
        analyzer_file = ""

    rerun_file = (
        "- rerun_analyzer.py — re-run analyzer on an existing attempt without re-evaluating\n"
        if pro_mode
        else ""
    )

    evaluator_file = (
        "- evaluator.py — scoring logic (read-only, do not modify)\n"
        if agent_readable_evaluator
        else ""
    )
    evaluator_rule = (
        "- Do NOT modify evaluator.py.\n"
        if agent_readable_evaluator
        else "- Do NOT read, search for, or infer evaluator source code or scoring implementation.\n"
    )
    evaluation_rule = (
        "- Every candidate that needs to be evaluated MUST go through submit.py (do not run evaluator.py directly).\n"
        if agent_readable_evaluator
        else "- Every candidate that needs to be evaluated MUST go through submit.py (do not run evaluation outside submit.py).\n"
    )
    result_layout = (
        "score, is_valid, feedback, metrics, processed_feedback, analysis_metrics"
        if analyzer_enabled
        else "score, is_valid, feedback, metrics"
    )
    archive_layout_extra = ""
    if pro_mode or raw_artifacts:
        archive_layout_extra = (
            "  archive/attempt_NNNN/raw-artifact.json — evaluator raw trajectories"
            + (" (for analyzer.py)\n" if pro_mode else "\n")
        )
    construction_note = (
        "\nNote: Large fields such as construction are stored in result.json for analyzer.py "
        "but omitted from submit.py stdout; rely on metrics and processed_feedback instead."
    )
    if pro_mode:
        construction_note += (
            "\nIn PRO mode, analyzer.py should read raw-artifact.json from output_dir "
            "(the attempt folder) to extract richer signals beyond construction summaries."
        )
    elif raw_artifacts:
        construction_note += (
            "\nWhen raw-artifact.json is present under an attempt folder, inspect it for that "
            "attempt (especially the latest or best-scoring runs) to see trajectories beyond "
            "aggregate metrics. Do NOT bulk-read raw-artifact.json across the entire archive."
        )

    raw_artifact_step = (
        " If archive/attempt_NNNN/raw-artifact.json exists, read it for the latest attempt "
        "(or best-scoring attempts) to understand behavior beyond aggregate metrics; "
        "do not bulk-read every attempt's raw-artifact."
    )

    if pro_mode:
        workflow_feedback = (
            "4. Read archive/attempt_NNNN/result.json AND raw-artifact.json for the latest attempt.\n"
            "5. Make an explicit analyzer-evolution decision for this iteration: determine whether "
            "analyzer.py should be changed to extract more actionable information from the latest raw artifacts "
            "before the next candidate change. If recent scores are stuck or plateauing, treat that as a strong "
            "reason to try evolving analyzer.py for new diagnostics.\n"
            "6. If the decision is to evolve analyzer.py, update it and test it without re-evaluating: "
            "python rerun_analyzer.py [attempt_id] (default: latest attempt). Read updated processed_feedback.\n"
            "7. If the decision is to keep analyzer.py unchanged, proceed only after using the existing "
            "processed_feedback/raw-artifact signals to choose the next candidate change.\n"
            "8. Evolve candidate.py based on the best available analysis.\n"
            "9. Repeat from step 3 until you reach the improvement budget."
        )
        closing = "Every iteration must include an analyzer-evolution decision, then keep improving candidate.py until the budget is used up."
    elif analyzer_enabled:
        workflow_feedback = (
            "4. Read the printed submit output and archive/attempt_NNNN/result.json, "
            "including processed_feedback from analyzer.py."
            + (raw_artifact_step if raw_artifacts else "")
            + "\n"
            "5. You may edit analyzer.py to produce more useful feedback for future submissions.\n"
            "6. Iterate until you reach the improvement budget."
        )
        closing = "Propose and submit improved algorithms until the budget is used up."
    else:
        workflow_feedback = (
            "4. Read the printed submit output and archive/attempt_NNNN/result.json."
            + (raw_artifact_step if raw_artifacts else "")
            + "\n"
            "5. Iterate until you reach the improvement budget."
        )
        closing = "Propose and submit improved algorithms until the budget is used up."

    if pro_mode:
        analyzer_rule = (
            "- On every iteration, explicitly consider whether analyzer.py needs to evolve before changing candidate.py. "
            "Evolve it when current feedback is insufficient, raw artifacts contain untapped actionable signals, "
            "or recent candidate scores appear stuck/plateaued; "
            "if you keep it unchanged, that should be a deliberate decision, not an omission.\n"
            "- If you change analyzer.py, test it with rerun_analyzer.py before relying on its feedback.\n"
            "- analyzer.py may read output_dir/raw-artifact.json, full result.json (including construction), "
            "and the attempt code.py.\n"
            "- Keep all analysis and logs in English. If validator text contains non-English or escaped Unicode messages, "
            "do not decode or reproduce them; rely on translated fields, metrics, and trajectory data.\n"
        )
    elif analyzer_enabled:
        analyzer_rule = "- analyzer.py is editable; improve it when richer feedback would help.\n"
    else:
        analyzer_rule = ""

    mode_note = (
        "PRO mode: every iteration must consider whether to evolve analyzer.py, then evolve candidate.py to improve score.\n"
        if pro_mode
        else ""
    )

    hidden_testdata_rules = ""
    if hidden_testdata:
        hidden_testdata_rules = """
"""
    if not agent_readable_evaluator:
        hidden_testdata_rules += """
"""

    dataset_file = ""
    dataset_rules = ""
    if (workspace / "dataset").exists():
        dataset_file = "- dataset/ — read-only reference data (symlinked source archive; do not modify)\n"
        dataset_rules = """
"""

    return f"""You are improving candidate programs for a discovery problem.

{mode_note}{resume_note}
{target_note}

Workspace directory (work ONLY here):
{workspace}

Files:
{evaluator_file}{analyzer_file}{rerun_file}{dataset_file}- submit.py — evaluate a candidate and archive it

Archive layout (each attempt is one folder):
  archive/attempt_NNNN/code.py      — candidate source code
  archive/attempt_NNNN/result.json  — {result_layout}
{archive_layout_extra}
Workflow:
1. Read problem.md and inspect archive/ for past attempts (code + results).
2. Write the next candidate to candidate.py (overwrite this file each iteration).
3. Submit it: python submit.py candidate.py
{workflow_feedback}
{construction_note}

Rules:
{evaluator_rule}{analyzer_rule}{target_rule}- Do NOT change the required function signature or output format.
{evaluation_rule}- Do not modify past attempts in archive/; submit new ones instead.
{dataset_rules}{hidden_testdata_rules}
Current best: {best_id} with score {best_score}
{target_status}{budget_note}

Previous attempts:
{history}

{closing}
"""


def build_continuation_prompt(
    archive: Archive,
    workspace_dir: Path,
    max_improvements: int,
    *,
    mode: str = "standard",
    target_score: float | None = None,
    maximize: bool = True,
) -> str:
    workspace = workspace_dir.resolve()
    pro_mode = mode == "pro"
    best = archive.best()
    remaining = archive.remaining_improvements(
        max_improvements, baseline=read_improvement_baseline(workspace)
    )
    if best:
        best_score = f"{best.score:.6f}"
        best_id = best.attempt_id
    else:
        best_score = "N/A"
        best_id = "none"

    pro_note = (
        "Continue the PRO loop: inspect raw artifacts, explicitly decide whether analyzer.py should evolve this iteration, then improve candidate.py. If scores look stuck, try evolving analyzer.py for new diagnostics before another candidate tweak.\n"
        if pro_mode
        else "Continue submitting improved candidates.\n"
    )
    target_note = ""
    if target_score is not None:
        direction = "at least" if maximize else "at most"
        comparison = ">=" if maximize else "<="
        if best and ((maximize and best.score >= target_score) or (not maximize and best.score <= target_score)):
            status = f"reached by {best_id}"
        else:
            status = "not reached yet"
        target_note = (
            f"Target score: {direction} {target_score:g} "
            f"(score {comparison} {target_score:g}); status: {status}.\n"
        )
    raw_note = ""
    if not pro_mode:
        hidden = False
        meta_path = workspace / "workspace_meta.json"
        if meta_path.is_file():
            try:
                hidden = bool(json.loads(meta_path.read_text(encoding="utf-8")).get("hidden_testdata"))
            except (OSError, json.JSONDecodeError):
                pass
        if _raw_artifacts_enabled(workspace) and not hidden:
            raw_note = (
                "- If raw-artifact.json exists under the latest attempt, read it before the next change "
                "(do not bulk-read the whole archive).\n"
            )
    return f"""Continue this evolution run in the SAME OpenCode session. Do not stop yet.

Improvement budget remaining: {remaining} submission(s) (max {max_improvements} after seed).
Current best: {best_id} with score {best_score}
{target_note}
Workspace: {workspace}

You previously exited before the budget was exhausted. Keep your prior context and continue working.
{pro_note}{raw_note}- Read the latest archive/attempt_* results before the next change.

Proceed with the next iteration now.
"""
