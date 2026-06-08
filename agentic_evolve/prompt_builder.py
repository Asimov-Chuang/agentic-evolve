from __future__ import annotations

from pathlib import Path

from agentic_evolve.archive import Archive


def build_prompt(
    archive: Archive,
    workspace_dir: Path,
    max_improvements: int,
    *,
    resumed: bool = False,
    hidden_testdata: bool = False,
    agent_readable_evaluator: bool = True,
) -> str:
    workspace = workspace_dir.resolve()
    analyzer_enabled = (workspace / "analyzer.py").is_file()
    best = archive.best()
    remaining = archive.remaining_improvements(max_improvements)

    if best:
        best_score = f"{best.score:.6f}"
        best_id = best.attempt_id
    else:
        best_score = "N/A"
        best_id = "none"

    history = "\n".join(archive.summary_lines()) or "(no attempts yet)"
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

    analyzer_file = "- analyzer.py — optional processed-feedback logic (editable; improve if useful)\n" if analyzer_enabled else ""
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
    construction_note = (
        "\nNote: Large fields such as construction are stored in result.json for analyzer.py "
        "but omitted from submit.py stdout; rely on metrics and processed_feedback instead."
    )
    workflow_feedback = (
        "4. Read the printed submit output and archive/attempt_NNNN/result.json, "
        "including processed_feedback from analyzer.py.\n"
        "5. You may edit analyzer.py to produce more useful feedback for future submissions.\n"
        "6. Iterate until you reach the improvement budget."
        if analyzer_enabled
        else "4. Read the printed submit output and archive/attempt_NNNN/result.json.\n"
        "5. Iterate until you reach the improvement budget."
    )
    analyzer_rule = (
        "- analyzer.py is part of the workspace, do not modify\n"
        if analyzer_enabled
        else ""
    )
    hidden_testdata_rules = ""
    if hidden_testdata:
        hidden_testdata_rules = """
- Test inputs/answers are HIDDEN. Do NOT read, search for, or infer testdata, `.in`/`.ans` files, or registry paths.
- Do NOT list or read directories outside the workspace (no `..`, no parent folders, no private_testdata).
- Use ONLY aggregate fields from submit.py / result.json: score, is_valid, feedback, metrics, processed_feedback.
"""
    if not agent_readable_evaluator:
        hidden_testdata_rules += """
- Evaluator source code is HIDDEN. Rely on problem.md and submit.py / result.json feedback only.
"""

    dataset_file = ""
    dataset_rules = ""
    if (workspace / "dataset").exists():
        dataset_file = "- dataset/ — read-only reference data (symlinked source archive; do not modify)\n"
        dataset_rules = """
- dataset/ is read-only reference data for evaluation. Do NOT bulk-read raw-artifact.json files (each is very large, ~100k lines).
- You may list dataset/attempt_* and read result.json scores for context; implement rule logic in your candidate program.
- Diagnostic rules must use ONLY observations + actions (policy-visible). Do NOT use common, rewards, or other simulator-internal fields (forbidden in code and stripped at evaluation).
- Each rule must follow the obs-filter + action-fraction pattern documented in problem.md (SustainDC observation index tables are in problem.md).
"""

    return f"""You are improving candidate programs for a discovery problem.

{resume_note}

Workspace directory (work ONLY here):
{workspace}

Files:
- problem.md — task description
{evaluator_file}{analyzer_file}{dataset_file}- submit.py — evaluate a candidate and archive it
- archive/ — all previous attempts
- checkpoint.json — run progress snapshot (managed by the framework)

Archive layout (each attempt is one folder):
  archive/attempt_NNNN/code.py      — candidate source code
  archive/attempt_NNNN/result.json  — {result_layout}

Workflow:
1. Read problem.md and inspect archive/ for past attempts (code + results).
2. Write the next candidate to candidate.py (overwrite this file each iteration).
3. Submit it: python submit.py candidate.py
{workflow_feedback}
{construction_note}

Rules:
{evaluator_rule}{analyzer_rule}- Do NOT change the required function signature or output format.
- Do NOT rely on internet access.
{evaluation_rule}- Do not modify past attempts in archive/; submit new ones instead.
- Use candidate.py as the only working candidate file; do not create candidate_001.py, candidate_v2.py, or other numbered variants in the workspace.
- Read and write under archive/
{dataset_rules}{hidden_testdata_rules}
Current best: {best_id} with score {best_score}
{budget_note}

Previous attempts:
{history}

Propose and submit improved algorithms until the budget is used.
"""
