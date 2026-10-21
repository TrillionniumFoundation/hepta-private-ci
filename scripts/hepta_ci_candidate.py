#!/usr/bin/env python3
"""Bind merge qualification to exact Git objects without duplicate native builds.

Identical trees may share native execution only inside a workflow whose final
fan-in also requires source-head success. This plan is not a test-pass receipt.
A different prospective tree must execute its own applicable tests. Optional
paired checkout binding does not establish live PR refs, CI completion, latest
run attempts, full baseline coverage, or independent acceptance.
"""

import argparse
import json
import re
from pathlib import Path

if __package__:
    from .hepta_ci_exec import git, identity
else:
    from hepta_ci_exec import git, identity


def candidate_plan(
    *,
    source: str,
    tested: str,
    lane: str,
    base: str | None = None,
    repository: Path | None = None,
) -> dict:
    merge_lane = lane in {"base-merge", "synthetic-merge"}
    if lane != "source-head" and not merge_lane:
        raise ValueError("unknown qualification lane")
    # workflow_dispatch supplies an empty BASE_SHA for a source-only lane.
    if lane == "source-head" and base == "":
        base = None
    for commit in (source, tested, *([base] if base is not None or merge_lane else [])):
        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise ValueError("candidate identities must be exact SHA-1 commits")
    before = identity(repository=repository)
    if before["commit"] != tested:
        raise ValueError("checked-out commit differs from tested identity")
    if before["dirty"]:
        raise ValueError("candidate checkout is dirty or has hidden index entries")
    if lane == "source-head" and source != tested:
        raise ValueError("source lane is not the exact source head")
    if (
        base is not None
        and git("cat-file", "-t", base, repository=repository) != "commit"
    ):
        raise ValueError("candidate base is not a commit object")
    if merge_lane:
        if before["parents"] != [base, source]:
            raise ValueError("prospective merge parents differ from base and source")
        expected_tree = git(
            "merge-tree", "--write-tree", base, source, repository=repository
        )
        if before["tree"] != expected_tree:
            raise ValueError("prospective merge tree differs from the canonical merge")
    source_tree = git("rev-parse", f"{source}^{{tree}}", repository=repository)
    tested_tree = before["tree"]
    if identity(repository=repository) != before:
        raise ValueError("candidate checkout changed during source binding")
    identical = source_tree == tested_tree
    return {
        "schema_version": 1,
        "lane": lane,
        "source_sha": source,
        "tested_sha": tested,
        "base_sha": base,
        "source_tree": source_tree,
        "tested_tree": tested_tree,
        "native_execution_required": lane == "source-head" or not identical,
        "requires_source_head_success": merge_lane and identical,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tested", required=True)
    parser.add_argument("--base")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--pair-repository", type=Path)
    parser.add_argument("--pair-source")
    parser.add_argument("--pair-tested")
    parser.add_argument("--pair-base")
    args = parser.parse_args()
    plan = candidate_plan(
        source=args.source, tested=args.tested, lane=args.lane, base=args.base
    )
    pair_arguments = (
        args.pair_repository,
        args.pair_source,
        args.pair_tested,
        args.pair_base,
    )
    if any(value is not None for value in pair_arguments):
        if not all(value is not None for value in pair_arguments):
            raise ValueError(
                "paired checkout requires repository, source, tested and base"
            )
        if re.fullmatch(r"[0-9a-f]{40}", args.pair_base) is None:
            raise ValueError("paired checkout requires an exact base commit")
        plan["paired_candidate"] = candidate_plan(
            source=args.pair_source,
            tested=args.pair_tested,
            base=args.pair_base,
            lane=args.lane,
            repository=args.pair_repository,
        )
    print(json.dumps(plan, sort_keys=True))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(
                f"run_native={str(plan['native_execution_required']).lower()}\n"
            )


if __name__ == "__main__":
    main()
