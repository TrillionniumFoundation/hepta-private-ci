#!/usr/bin/env python3
"""Bind kernel.authority's implementation map to one exact candidate.

An implementation-map file cannot contain the SHA/tree of the commit that
contains itself without a self-reference paradox.  `sourceBase` is therefore a
historical source anchor, while this verifier produces the current-candidate
binding: exact HEAD/tree + SHA-256 of the map bytes + validated anchor ancestry.
The receipt is suitable for exact-head and synthetic-merge qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/kernel.authority/IMPLEMENTATION_MAP.json"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def rev(*args: str) -> str:
    return git("rev-parse", *args).stdout.strip()


def verify(expected_sha: str | None = None) -> dict[str, object]:
    head = rev("HEAD")
    tree = rev("HEAD^{tree}")
    if expected_sha is not None and head != expected_sha:
        raise RuntimeError(f"exact candidate mismatch: expected {expected_sha}, got {head}")
    payload = MAP.read_bytes()
    row = json.loads(payload)
    if row.get("module") != "kernel.authority":
        raise RuntimeError("implementation map module identity mismatch")
    source_base = row.get("sourceBase")
    if not isinstance(source_base, dict):
        raise RuntimeError("implementation map lacks sourceBase")
    anchor_commit = source_base.get("commit")
    anchor_tree = source_base.get("tree")
    if not isinstance(anchor_commit, str) or not anchor_commit:
        raise RuntimeError("implementation map lacks sourceBase.commit")
    if not isinstance(anchor_tree, str) or not anchor_tree:
        raise RuntimeError("implementation map lacks sourceBase.tree")
    observed_anchor_tree = rev(f"{anchor_commit}^{{tree}}")
    if observed_anchor_tree != anchor_tree:
        raise RuntimeError(
            f"sourceBase tree mismatch: recorded {anchor_tree}, observed {observed_anchor_tree}"
        )
    ancestry = git("merge-base", "--is-ancestor", anchor_commit, head, check=False)
    if ancestry.returncode != 0:
        raise RuntimeError("implementation map sourceBase is not an ancestor of candidate HEAD")
    claim = row.get("claimBoundary")
    if not isinstance(claim, dict):
        raise RuntimeError("implementation map lacks claimBoundary")
    return {
        "schema": "hepta.kernel-authority-map-candidate-receipt.v1",
        "status": "PASS_KERNEL_AUTHORITY_MAP_CANDIDATE_BINDING",
        "candidate": {"commit": head, "tree": tree},
        "map": {
            "path": str(MAP.relative_to(ROOT)),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "sourceAnchor": {"commit": anchor_commit, "tree": anchor_tree},
        },
        "claims": {
            "productionImplementation": bool(row.get("productionImplementation", False)),
            "productCallerState": row.get("productCallerState"),
            "productExecutionProved": bool(claim.get("productExecutionProved", False)),
            "independentAcceptance": bool(claim.get("independentAcceptance", False)),
            "activation": bool(claim.get("activation", False)),
            "release": bool(claim.get("release", False)),
        },
        "authorityGranted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = verify(args.expected_sha)
    except (OSError, ValueError, subprocess.CalledProcessError, RuntimeError) as exc:
        raise SystemExit(f"FAIL_KERNEL_AUTHORITY_MAP_FRESHNESS: {exc}") from exc
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
