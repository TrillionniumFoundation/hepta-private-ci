#!/usr/bin/env python3
"""Generate or verify the cognitive.types seven-layer status projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/cognitive.types/IMPLEMENTATION_MAP.json"
STATUS = ROOT / "docs/modules/cognitive.types/STATUS.json"


def render() -> str:
    implementation = json.loads(MAP.read_text(encoding="utf-8"))
    status = {
        "schema": "hepta.module-status.v1",
        "moduleId": implementation["moduleId"],
        "generatedFrom": "docs/modules/cognitive.types/IMPLEMENTATION_MAP.json",
        "reviewBaselineCommit": implementation["sourceBase"]["reviewBaselineCommit"],
        "layers": implementation["statusLayers"],
        "claimBoundary": implementation["claimBoundary"],
    }
    return json.dumps(status, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    expected = render()
    if args.write:
        STATUS.write_text(expected, encoding="utf-8")
        return 0

    actual = STATUS.read_text(encoding="utf-8") if STATUS.exists() else ""
    if actual != expected:
        raise SystemExit(
            "cognitive.types STATUS.json is stale; run "
            "python3 scripts/hepta-cognitive-types-status.py --write"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
