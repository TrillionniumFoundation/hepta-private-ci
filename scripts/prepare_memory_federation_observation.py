#!/usr/bin/env python3
"""Author-only rebind of the memory.federation map to a frozen source commit.

Run after committing source/tests/docs, then commit only the produced map. This
command is deliberately absent from the qualification matrix: qualification
must read, never repair, its own inputs. No execution/acceptance claim is set.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

from verify_memory_federation_implementation import _load_canonical_verifier

MAP = "docs/modules/memory.federation/IMPLEMENTATION_MAP.json"
ROOT = pathlib.Path(__file__).resolve().parents[1]
NEW_EVIDENCE = (
    "scripts/prepare_memory_federation_observation.py",
    "scripts/test_memory_federation_entrypoints.py",
    "docs/modules/memory.federation/INDEXED_ADMISSION.md",
)


def prepare(source_sha: str, base_sha: str, branch: str) -> dict:
    if any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in (source_sha, base_sha)):
        raise ValueError("source and base must be literal full commit SHAs")
    verifier = _load_canonical_verifier()
    if verifier.git("rev-parse", "HEAD") != source_sha:
        raise ValueError("source must be the checked-out frozen HEAD")
    if verifier.git("status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("commit source, tests and documentation before observing them")
    if verifier.git("cat-file", "-t", base_sha) != "commit":
        raise ValueError("base must name a locally available commit")
    verifier.git("check-ref-format", "--branch", branch)
    row = verifier.load(MAP)
    if row.get("module") != "memory.federation":
        raise ValueError("incorrect module identity")
    # Source observation must not become an execution or operator-acceptance act.
    for field in ("productionImplementation", "productExecutionProved", "independentAcceptance",
                  "activation", "release"):
        if row.get("claimBoundary", {}).get(field) is not False:
            raise ValueError(f"candidate map must retain {field}=false")
    head = row["headAttestation"]
    head["evidencePaths"] = sorted(set(head["evidencePaths"]) | set(NEW_EVIDENCE))
    paths = sorted(set(verifier.tracked_source_paths(row)) | set(row["observedSourcePaths"]))
    if MAP in paths:
        raise ValueError("implementation map cannot hash its own future commit")
    verifier.require_tracked_paths(source_sha, paths)
    identity = {"commit": source_sha, "tree": verifier.git("rev-parse", "HEAD^{tree}")}
    row["sourceBase"] = dict(identity)
    row["observedAtHead"] = dict(identity)
    row["observedSourcePaths"] = paths
    row["sourceObjects"] = [
        {"path": path, "object": verifier.git("rev-parse", f"{source_sha}:{path}")}
        for path in paths
    ]
    head.update(
        candidateBranch=branch, baseCommit=base_sha,
        candidateHead=source_sha, candidateTree=identity["tree"],
        status="pending_exact_current_head_and_merge_candidate_execution",
        metadataOnlyPaths=[MAP],
        note=("Author-only observation of a committed source/tests/docs candidate. "
              "Authentication precedes staged state, derived expiry indexes preserve canonical "
              "snapshots, and the CLI/guard share one attestation module instance. This map-only "
              "rebind grants no execution, independent acceptance or activation claim. "
              "A fresh read-only exact-head and deterministic-current-base qualification is required."),
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--candidate-branch", required=True)
    parser.add_argument("--write", action="store_true", help="write only IMPLEMENTATION_MAP.json")
    args = parser.parse_args()
    row = prepare(args.source_sha, args.base_sha, args.candidate_branch)
    payload = json.dumps(row, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        path = ROOT / MAP
        path.write_text(payload, encoding="utf-8")
        print(f"Rebound {MAP}; source={args.source_sha}; execution claims remain false")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError) as error:
        raise SystemExit(f"MEMORY_FEDERATION_OBSERVATION_REJECTED: {error}") from error
