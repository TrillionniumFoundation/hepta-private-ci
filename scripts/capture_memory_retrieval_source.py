#!/usr/bin/env python3
"""Capture/verify an exact-checkout observation, without a self-referential map SHA.

The whole codex-rs Git tree covers transitive workspace dependencies and locks.
A checked-in provenance map is not silently treated as an exact-head receipt.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from verify_memory_retrieval_slo import canonical, loads, sha256, source_identity, write_immutable

ROOTS = ("codex-rs", "scripts", ".github/workflows", "docs/modules/memory.retrieval",
         "qualification/memory-retrieval")


def capture(root: Path, head: str, tree: str) -> dict:
    source = source_identity(root, head, tree)
    objects = {}
    for path in ROOTS:
        objects[path] = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", f"{head}:{path}"], text=True).strip()
    receipt = {"schema": "hepta.memory-retrieval.source-observation.v1",
               "source": source, "source_objects": objects,
               "qualification_executed": False, "activation": False, "release": False}
    receipt["receipt_sha256"] = sha256(canonical(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        receipt = capture(args.root, args.source_sha, args.source_tree)
        if args.verify:
            if loads(args.verify.read_text()) != receipt:
                raise ValueError("source observation is not fresh for this exact checkout")
        else:
            write_immutable(args.output, receipt)
        print("exact source observation verified; execution and acceptance remain separate")
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__": raise SystemExit(main())
