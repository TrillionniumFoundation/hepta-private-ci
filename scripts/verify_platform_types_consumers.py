#!/usr/bin/env python3
"""Validate the closed platform.types source-consumer qualification matrix."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json"
EXPECTED = [
    "generated.python",
    "generated.javascript",
    "canonical.python-node",
    "utility.ndu.registered-numeric",
    "runtime.codex.prompt-delivery",
    "learning.ledger.prompt-delivery",
    "runtime.supervisor.topology",
]


def main() -> int:
    value = json.loads(MATRIX.read_text(encoding="utf-8"))
    rows = value.get("consumers")
    if (
        value.get("schema") != "hepta.platform-types.consumer-qualification.v1"
        or value.get("schemaVersion") != 1
        or value.get("module") != "platform.types"
        or not isinstance(rows, list)
        or [row.get("id") for row in rows if isinstance(row, dict)] != EXPECTED
    ):
        raise SystemExit("platform.types consumer matrix header/order mismatch")
    seen: set[str] = set()
    for row in rows:
        identifier = row["id"]
        if identifier in seen:
            raise SystemExit(f"duplicate consumer: {identifier}")
        seen.add(identifier)
        path = ROOT / row["path"]
        if not path.is_file():
            raise SystemExit(f"missing consumer source: {row['path']}")
        text = path.read_text(encoding="utf-8")
        anchors = row.get("mustContain")
        if not isinstance(anchors, list) or not anchors:
            raise SystemExit(f"{identifier}: source anchors required")
        for anchor in anchors:
            if not isinstance(anchor, str) or not anchor or anchor not in text:
                raise SystemExit(f"{identifier}: missing source anchor {anchor!r}")
    print(f"platform.types consumer matrix: {len(rows)} source consumers verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
