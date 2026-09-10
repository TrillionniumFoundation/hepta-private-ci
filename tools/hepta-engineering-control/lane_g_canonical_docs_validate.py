#!/usr/bin/env python3
"""Verify canonical control.engineering companions exactly mirror source-bound specs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/hepta-engineering-control/control_engineering_v2"
CANONICAL = ROOT / "docs/modules/control.engineering"
MIRRORS = ("IMPLEMENTATION.md", "COMPONENTS.json", "TRACEABILITY.json")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    mismatches: list[str] = []
    receipts: dict[str, str] = {}
    for name in MIRRORS:
        source = SOURCE / name
        canonical = CANONICAL / name
        if not source.is_file() or not canonical.is_file():
            mismatches.append(f"missing:{name}")
            continue
        source_bytes = source.read_bytes()
        canonical_bytes = canonical.read_bytes()
        if source_bytes != canonical_bytes:
            mismatches.append(f"content_mismatch:{name}")
            continue
        receipts[name] = digest(source)

    guide = CANONICAL / "TECHNICAL.md"
    if not guide.is_file():
        mismatches.append("missing:TECHNICAL.md")
    else:
        text = guide.read_text(encoding="utf-8")
        if not text.startswith("# control.engineering technical development guide\n"):
            mismatches.append("technical_guide_identity")

    result = {
        "status": "PASS_LANE_G_CANONICAL_DOC_BINDING" if not mismatches else "FAIL_LANE_G_CANONICAL_DOC_BINDING",
        "mirrors": receipts,
        "mismatches": mismatches,
        "authorityGranted": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
