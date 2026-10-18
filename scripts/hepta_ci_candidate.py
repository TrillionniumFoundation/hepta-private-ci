#!/usr/bin/env python3
"""Bind merge qualification to exact Git objects without duplicate native builds.

Identical trees may share native execution only inside a workflow whose final
fan-in also requires source-head success. This plan is not a test-pass receipt.
A different prospective tree must execute its own applicable tests.

The generic tree-check output is only for checks whose content inputs are the
same tree. Do not reuse time-, host-, credential- or history-dependent acceptance.
The document workflow uses the same event/base and preserves source ancestry;
exact merge identity is independently validated here even when content is reused.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], stderr=subprocess.PIPE, text=True
    ).strip()


def candidate_plan(
    *,
    source: str,
    tested: str,
    lane: str,
    base: str | None = None,
    source_head_result: str | None = None,
) -> dict:
    merge_lane = lane in {"base-merge", "synthetic-merge"}
    if lane != "source-head" and not merge_lane:
        raise ValueError("unknown qualification lane")
    identities = (source, tested, *([base] if merge_lane else []))
    for identity in identities:
        if (
            not isinstance(identity, str)
            or re.fullmatch(r"[0-9a-f]{40}", identity) is None
        ):
            raise ValueError("candidate identities must be exact SHA-1 commits")
    for identity in dict.fromkeys(identities):
        if git("cat-file", "-t", identity) != "commit":
            raise ValueError(
                "candidate identities must name commit objects, not tags or trees"
            )
    if git("rev-parse", "HEAD") != tested:
        raise ValueError("checked-out commit differs from tested identity")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError(
            "candidate reuse requires a clean checkout, including untracked inputs"
        )
    if lane == "source-head" and source != tested:
        raise ValueError("source lane is not the exact source head")
    if merge_lane:
        parents = git("show", "-s", "--format=%P", tested).split()
        if parents != [base, source]:
            raise ValueError("prospective merge parents differ from base and source")
    source_tree = git("rev-parse", f"{source}^{{tree}}")
    tested_tree = git("rev-parse", f"{tested}^{{tree}}")
    if merge_lane:
        # Matching parents and a source-equal tree do not prove a merge: a
        # manufactured commit could omit changes from the base. Recompute the
        # same merge used by execution records before deciding to skip work.
        try:
            expected_tree = git("merge-tree", "--write-tree", base, source)
        except subprocess.CalledProcessError as error:
            raise ValueError(
                "prospective merge is conflicting or unavailable"
            ) from error
        if tested_tree != expected_tree:
            raise ValueError(
                "tested merge tree differs from the recomputed base/source merge tree"
            )
    identical = source_tree == tested_tree
    if merge_lane and identical and source_head_result is not None:
        if source_head_result != "success":
            raise ValueError("tree reuse requires successful source-head execution")
    return {
        "schema_version": 1,
        "lane": lane,
        "source_sha": source,
        "tested_sha": tested,
        "base_sha": base,
        "source_head_result": source_head_result,
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
    parser.add_argument(
        "--source-head-result",
        help="Result from the same workflow source-head dependency",
    )
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    plan = candidate_plan(
        source=args.source,
        tested=args.tested,
        lane=args.lane,
        base=args.base,
        source_head_result=args.source_head_result,
    )
    print(json.dumps(plan, sort_keys=True))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(
                f"run_native={str(plan['native_execution_required']).lower()}\n"
                f"run_tree_checks={str(plan['native_execution_required']).lower()}\n"
            )


if __name__ == "__main__":
    main()
