#!/usr/bin/env python3
"""Fail-closed blocker gate for complete OpenBao replacement claims."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "qualification/openbao-compatibility/COMPATIBILITY_MATRIX.json"
STATUSES = {"gap", "partial", "closed"}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL_OPENBAO_COMPATIBILITY: {message}")


def main() -> int:
    try:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read matrix: {exc}")
    if matrix.get("schema") != "hepta.openbao-compatibility-matrix.v1":
        fail("unexpected matrix schema")
    authority = matrix.get("authorityFlags")
    if not isinstance(authority, dict) or any(authority.values()):
        fail("compatibility matrix grants authority")
    rows = matrix.get("capabilities")
    if not isinstance(rows, list) or not rows:
        fail("empty capability matrix")
    ids = [row.get("id") for row in rows]
    if any(not isinstance(row, dict) for row in rows) or len(set(ids)) != len(ids):
        fail("capability IDs are not unique")
    blockers = []
    for row in rows:
        status = row.get("status")
        if status not in STATUSES:
            fail(f"{row.get('id')}: invalid status {status!r}")
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            fail(f"{row.get('id')}: evidence must be a list")
        for relative in evidence:
            path = ROOT / relative
            if not path.is_file():
                fail(f"{row.get('id')}: missing evidence path {relative}")
        if row.get("blocking") is True and status != "closed":
            blockers.append(row["id"])
    result = {
        "status": "PASS_OPENBAO_REPLACEMENT"
        if not blockers
        else "BLOCKED_OPENBAO_REPLACEMENT_GAPS",
        "capabilities": len(rows),
        "blockingGaps": blockers,
        "closed": sum(row["status"] == "closed" for row in rows),
    }
    print(json.dumps(result, separators=(",", ":")))
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
