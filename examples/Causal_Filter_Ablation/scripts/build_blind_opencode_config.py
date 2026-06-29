#!/usr/bin/env python3
"""Merge CloudGPT OpenCode config with blind-ablation permission rules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXAMPLE_DIR = Path(__file__).resolve().parent.parent
AE_ROOT = EXAMPLE_DIR.parent.parent
BASE_CONFIG = AE_ROOT / "opencode.cloudgpt.json"
PERMISSIONS = EXAMPLE_DIR / "opencode.blind_permissions.json"
OUT_CONFIG = EXAMPLE_DIR / "opencode.blind_ablation.json"


def main() -> int:
    if not BASE_CONFIG.is_file():
        print(f"error: missing base config: {BASE_CONFIG}", file=sys.stderr)
        return 1
    if not PERMISSIONS.is_file():
        print(f"error: missing permissions overlay: {PERMISSIONS}", file=sys.stderr)
        return 1

    base = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    permission = json.loads(PERMISSIONS.read_text(encoding="utf-8"))
    merged = dict(base)
    merged["permission"] = permission
    OUT_CONFIG.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())