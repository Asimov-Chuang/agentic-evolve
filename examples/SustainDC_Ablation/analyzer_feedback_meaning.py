"""Meaning-rich raw-artifact feedback analyzer for SustainDC ablation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

FEEDBACK_MODE = "feedback_with_meaning"


def _delegate_module():
    here = Path(__file__).resolve().parent
    for root in (here, *here.parents):
        path = root / "_analyzer_delegate.py"
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("sustaindc_ablation_delegate", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    raise ImportError("Missing analyzer delegate")


def analyze(
    program_path: str,
    output_dir: str,
    result: dict,
    archive_dir: str,
    workspace_dir: str,
) -> dict:
    del archive_dir, workspace_dir
    return _delegate_module()._run_analyze(program_path, output_dir, result, FEEDBACK_MODE)