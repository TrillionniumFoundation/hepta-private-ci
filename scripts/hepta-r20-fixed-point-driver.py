#!/usr/bin/env python3
"""Materialize a narrowly patched, hash-bound Hepta fixed-point executor.

The r19 convergence controller failed before producing a candidate because its
strict-Clippy repair contract expected one redundant ``record_id.clone()`` in
the merged Lane D source, while the exact merged tree contains two equivalent
occurrences.  This driver changes only that count contract from one to two,
records source and output hashes, and leaves the repository copy of the r7
executor unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ANCHOR = '''        (
            Path("codex-rs/hepta-cognitive-store/src/v2.rs"),
            "record_id: record_id.clone(),",
            "record_id: record_id,",
            1,
        ),'''
REPLACEMENT = '''        (
            Path("codex-rs/hepta-cognitive-store/src/v2.rs"),
            "record_id: record_id.clone(),",
            "record_id: record_id,",
            2,
        ),'''


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def materialize(source: Path, output: Path, receipt: Path) -> None:
    raw = source.read_bytes()
    text = raw.decode("utf-8")
    anchor_count = text.count(ANCHOR)
    replacement_count = text.count(REPLACEMENT)
    if anchor_count != 1 or replacement_count != 0:
        raise RuntimeError(
            "executor patch precondition failed: "
            f"anchor={anchor_count} replacement={replacement_count}"
        )

    patched = text.replace(ANCHOR, REPLACEMENT, 1)
    if patched.count(ANCHOR) != 0 or patched.count(REPLACEMENT) != 1:
        raise RuntimeError("executor patch postcondition failed")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(patched, encoding="utf-8")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "patchId": "HEPTA-R20-COGNITIVE-STORE-CLONE-COUNT",
                "source": source.as_posix(),
                "output": output.as_posix(),
                "sourceSha256": sha256(raw),
                "outputSha256": sha256(patched.encode("utf-8")),
                "anchorOccurrencesBefore": anchor_count,
                "replacementOccurrencesAfter": 1,
                "expectedMergedCloneOccurrences": 2,
                "authorityGranted": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    materialize(args.source, args.output, args.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
