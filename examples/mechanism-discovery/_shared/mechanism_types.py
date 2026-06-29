"""Shared types for mechanism discovery tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


SourceKind = Literal["code", "trace"]
TargetKind = Literal["trace", "metric"]
EffectKind = Literal["increase", "decrease"]


@dataclass(frozen=True)
class MechanismLink:
    """Typed edge in a mechanism model: code/trace -> trace/metric."""

    source_kind: SourceKind
    source_id: str
    target_kind: TargetKind
    target_id: str
    effect: EffectKind
    rationale: str = ""

    @classmethod
    def from_mapping(cls, raw: Any) -> "MechanismLink":
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, dict):
            raise TypeError(f"MechanismLink must be dict or MechanismLink, got {type(raw)!r}")
        return cls(
            source_kind=str(raw["source_kind"]),
            source_id=str(raw["source_id"]),
            target_kind=str(raw["target_kind"]),
            target_id=str(raw["target_id"]),
            effect=str(raw["effect"]),
            rationale=str(raw.get("rationale") or ""),
        )

    def validate_schema(self) -> str | None:
        if self.source_kind not in ("code", "trace"):
            return f"invalid source_kind {self.source_kind!r}"
        if self.target_kind not in ("trace", "metric"):
            return f"invalid target_kind {self.target_kind!r}"
        if self.effect not in ("increase", "decrease"):
            return f"invalid effect {self.effect!r}"
        if self.source_kind == "code" and self.target_kind != "trace":
            return "code links must target trace predicates"
        if self.source_kind == "trace" and self.target_kind != "metric":
            return "trace links must target metric nodes"
        if not self.source_id.strip():
            return "source_id must be non-empty"
        if not self.target_id.strip():
            return "target_id must be non-empty"
        return None


DEFAULT_MECHANISM_CONFIG: dict[str, Any] = {
    "max_code_predicates": 6,
    "max_trace_predicates": 8,
    "max_links": 12,
    "min_support": 3,
    "effect_threshold": 0.05,
    "effect_threshold_metric": 0.10,
    "enable_predictive_r2": False,
    "link_consistency_weight": 0.625,
    "path_coherence_weight": 0.375,
    "predictive_r2_weight": 0.25,
    "degenerate_rate_low": 0.05,
    "degenerate_rate_high": 0.95,
    "degenerate_penalty": 0.05,
    "wrong_direction_penalty": 0.5,
    "metric_nodes": [
        "mean_slew",
        "mean_rms",
        "mean_strehl",
        "score",
        "u_mean_slew",
        "u_mean_rms",
        "u_strehl",
    ],
}


def merged_mechanism_config(meta: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(DEFAULT_MECHANISM_CONFIG)
    override = meta.get("mechanism")
    if isinstance(override, dict):
        cfg.update(override)
    return cfg
