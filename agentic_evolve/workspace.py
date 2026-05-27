from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

from agentic_evolve.archive import Archive
from agentic_evolve.config import Config
from agentic_evolve.evaluator import run_evaluation


def setup_workspace(config: Config) -> Path:
    workspace = config.workspace_dir
    workspace.mkdir(parents=True, exist_ok=True)

    shutil.copy2(config.problem, workspace / "problem.md")
    shutil.copy2(config.evaluator, workspace / "evaluator.py")

    meta = {
        "project_name": config.project_name,
        "maximize": config.maximize,
        "max_improvements": config.max_improvements,
        "evaluation_timeout_seconds": config.evaluation_timeout_seconds,
    }
    with open(workspace / "workspace_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    submit_src = resources.files("agentic_evolve").joinpath("submit.py")
    shutil.copy2(submit_src, workspace / "submit.py")

    archive = Archive(config.archive_dir, config.maximize)
    if not archive.list_attempts():
        result = run_evaluation(
            evaluator_path=workspace / "evaluator.py",
            program_path=config.initial_program,
            output_dir=config.archive_dir / "_seed_eval",
            timeout_seconds=config.evaluation_timeout_seconds,
            maximize=config.maximize,
        )
        archive.seed_initial(config.initial_program, result)

    return workspace
