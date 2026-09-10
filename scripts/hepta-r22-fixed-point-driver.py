#!/usr/bin/env python3
"""Materialize the r22 exact-source convergence executor.

The driver applies three narrowly scoped, hash-receipted controller corrections:

1. the exact merged Lane D source contains two redundant ``record_id.clone()``
   occurrences, so the strict mechanical repair contract must expect two;
2. Lane F must select the sealed owner branch that contains the r12 zero-drift
   standalone lock verifier, valid workflow YAML, and canonical rustfmt output;
3. Lane G must select the exact engineering-owner branch with the explicit
   ``control_engineering_v2`` public surface, rather than a newer governance-only
   branch selected by the generic timestamp fallback.

The repository copy of the r7 executor remains immutable.  Only the generated
executor is used by the r22 workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PATCHES: tuple[tuple[str, str, str], ...] = (
    (
        "cognitive-store-clone-count",
        '''        (
            Path("codex-rs/hepta-cognitive-store/src/v2.rs"),
            "record_id: record_id.clone(),",
            "record_id: record_id,",
            1,
        ),''',
        '''        (
            Path("codex-rs/hepta-cognitive-store/src/v2.rs"),
            "record_id: record_id.clone(),",
            "record_id: record_id,",
            2,
        ),''',
    ),
    (
        "lane-f-sealed-owner-selection",
        '''    "F": (
        "codex/lane-f-gap-closure-20260910",
        "codex/hepta-lane-f-gap-closure-20260910",
    ),''',
        '''    "F": (
        "codex/lane-f-gap-closure-20260910-r2",
        "codex/lane-f-gap-closure-20260910",
        "codex/hepta-lane-f-gap-closure-20260910",
    ),''',
    ),
    (
        "lane-g-engineering-owner-selection",
        '''    "G": (
        "codex/hepta-lane-g-gap-closure-20260910",
        "codex/lane-g-gap-closure-20260910",
    ),''',
        '''    "G": (
        "codex/lane-g-real-full-closure-v2-20260910",
        "codex/hepta-lane-g-gap-closure-20260910",
        "codex/lane-g-gap-closure-20260910",
    ),''',
    ),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def materialize(source: Path, output: Path, receipt: Path) -> None:
    raw = source.read_bytes()
    text = raw.decode("utf-8")
    receipts: list[dict[str, object]] = []

    for patch_id, anchor, replacement in PATCHES:
        anchor_count = text.count(anchor)
        replacement_count = text.count(replacement)
        if anchor_count != 1 or replacement_count != 0:
            raise RuntimeError(
                f"patch precondition failed for {patch_id}: "
                f"anchor={anchor_count} replacement={replacement_count}"
            )
        text = text.replace(anchor, replacement, 1)
        if text.count(anchor) != 0 or text.count(replacement) != 1:
            raise RuntimeError(f"patch postcondition failed for {patch_id}")
        receipts.append(
            {
                "patchId": patch_id,
                "anchorOccurrencesBefore": anchor_count,
                "replacementOccurrencesAfter": 1,
                "anchorSha256": sha256(anchor.encode("utf-8")),
                "replacementSha256": sha256(replacement.encode("utf-8")),
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "controllerId": "HEPTA-R22-FIXED-POINT",
                "source": source.as_posix(),
                "output": output.as_posix(),
                "sourceSha256": sha256(raw),
                "outputSha256": sha256(text.encode("utf-8")),
                "patches": receipts,
                "selectedLaneFBranch": "codex/lane-f-gap-closure-20260910-r2",
                "selectedLaneGBranch": "codex/lane-g-real-full-closure-v2-20260910",
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
