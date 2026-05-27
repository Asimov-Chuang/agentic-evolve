from __future__ import annotations

from pathlib import Path

from agentic_evolve.archive import Archive


def build_prompt(archive: Archive, workspace_dir: Path, max_improvements: int) -> str:
    workspace = workspace_dir.resolve()
    best = archive.best()
    remaining = archive.remaining_improvements(max_improvements)

    if best:
        best_score = f"{best.score:.6f}"
        best_id = best.attempt_id
    else:
        best_score = "N/A"
        best_id = "none"

    history = "\n".join(archive.summary_lines()) or "(no attempts yet)"

    return f"""You are improving candidate programs for a discovery problem.

Workspace directory (work ONLY here):
{workspace}

Files:
- problem.md — task description
- evaluator.py — scoring logic (read-only, do not modify)
- submit.py — evaluate a candidate and archive it
- archive/ — all previous attempts

Archive layout (each attempt is one folder):
  archive/attempt_NNNN/code.py      — candidate source code
  archive/attempt_NNNN/result.json  — score, is_valid, feedback, metrics

Workflow:
1. Read problem.md and inspect archive/ for past attempts (code + results).
2. Write a new candidate to a scratch file (e.g. candidate.py).
3. Submit it: python submit.py candidate.py
4. Read the printed result and archive/attempt_NNNN/result.json.
5. Iterate until you reach the improvement budget or cannot improve further.

Rules:
- Do NOT modify evaluator.py.
- Do NOT think too much in the early stage, start with trial and feedback.
- Do NOT change the required function signature or output format.
- Do NOT rely on internet access.
- Every candidate that needs to be evaluated MUST go through submit.py (do not run evaluator.py directly).
- Do modify past attempts in archive/, submit new instead.
- Read and write under archive/

Improvement budget: {remaining} submission(s) remaining (max {max_improvements} after the seed).

Previous attempts:
{history}

Propose and submit improved algorithms until the budget is used or you stop improving.
"""
