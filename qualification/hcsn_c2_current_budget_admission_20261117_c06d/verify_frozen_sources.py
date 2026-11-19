#!/usr/bin/env python3
"""Verify immutable local source bytes without importing the candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FREEZE = ROOT / "SOURCE-FREEZE.json"


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> int:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    files = freeze.get("files")
    if not isinstance(files, dict) or not files:
        fail("missing frozen files")
    for name, expected in sorted(files.items()):
        path = ROOT / name
        if not path.is_file():
            fail(f"missing frozen file: {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            fail(f"source hash mismatch: {name}")
    counters = freeze.get("execution_counters")
    if counters != {
        "model_executions": 0,
        "native_jobs": 0,
        "new_execution_keys": 0,
        "optimizer_calls": 0,
        "torch_executions": 0,
    }:
        fail("execution counters changed")
    print(json.dumps({"frozen_files": len(files), "status": "PASS", **counters}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
