from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class RuleSpec:
    index: int
    name: str
    description: str
    # "positive" | "negative" when regression coef sign is known; None otherwise.
    score_effect: str | None = None


def _score_effect_from_coef(coef: float) -> str | None:
    if coef > 0:
        return "positive"
    if coef < 0:
        return "negative"
    return None


def extract_rules_from_result(result_path: Path) -> List[RuleSpec]:
    with open(result_path, encoding="utf-8") as f:
        result = json.load(f)
    metrics = result.get("metrics") or {}
    descriptions = metrics.get("rule_descriptions")
    names = metrics.get("rule_names")
    if isinstance(descriptions, list) and descriptions:
        rules: List[RuleSpec] = []
        for i, desc in enumerate(descriptions):
            name = names[i] if isinstance(names, list) and i < len(names) else f"rule_{i}"
            coef_raw = metrics.get(f"coef_{i}")
            score_effect = (
                _score_effect_from_coef(float(coef_raw)) if coef_raw is not None else None
            )
            rules.append(
                RuleSpec(
                    index=i,
                    name=str(name),
                    description=str(desc),
                    score_effect=score_effect,
                )
            )
        return rules

    rule_set_size = int(metrics.get("rule_set_size", 0))
    rules = []
    for i in range(rule_set_size):
        name = metrics.get(f"rule_name_{i}", f"rule_{i}")
        desc = metrics.get(f"rule_description_{i}", str(name))
        coef_raw = metrics.get(f"coef_{i}")
        score_effect = (
            _score_effect_from_coef(float(coef_raw)) if coef_raw is not None else None
        )
        rules.append(
            RuleSpec(
                index=i,
                name=str(name),
                description=str(desc),
                score_effect=score_effect,
            )
        )
    if rules:
        return rules
    raise ValueError(f"No rule descriptions in {result_path}")


def extract_rules_from_code(code_path: Path) -> List[RuleSpec]:
    source = code_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "RULE_CATALOG":
                    value = ast.literal_eval(node.value)
                    rules: List[RuleSpec] = []
                    for i, entry in enumerate(value):
                        if isinstance(entry, (tuple, list)) and len(entry) >= 2:
                            rules.append(
                                RuleSpec(index=i, name=str(entry[0]), description=str(entry[1]))
                            )
                    if rules:
                        return rules
    raise ValueError(f"Cannot parse RULE_CATALOG from {code_path}")


def extract_rules(attempt_dir: Path) -> List[RuleSpec]:
    result_path = attempt_dir / "result.json"
    code_path = attempt_dir / "code.py"
    if result_path.is_file():
        try:
            return extract_rules_from_result(result_path)
        except ValueError:
            pass
    if code_path.is_file():
        return extract_rules_from_code(code_path)
    raise ValueError(f"No rules found in {attempt_dir}")
