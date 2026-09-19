#!/usr/bin/env python3
"""Bind merge qualification to exact Git objects without duplicate native builds.

Identical trees may share native execution only inside a workflow whose final
fan-in also requires source-head success. This plan is not a test-pass receipt.
A different prospective tree must execute its own applicable tests.
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


def candidate_plan(*, source: str, tested: str, lane: str, base: str | None = None) -> dict:
    if lane not in {"source-head", "base-merge"}:
        raise ValueError("unknown qualification lane")
    for identity in (source, tested, *([base] if lane == "base-merge" else [])):
        if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{40}", identity) is None:
            raise ValueError("candidate identities must be exact SHA-1 commits")
    if git("rev-parse", "HEAD") != tested:
        raise ValueError("checked-out commit differs from tested identity")
    if lane == "source-head" and source != tested:
        raise ValueError("source lane is not the exact source head")
    if lane == "base-merge":
        parents = git("show", "-s", "--format=%P", tested).split()
        if parents != [base, source]:
            raise ValueError("prospective merge parents differ from base and source")
    source_tree = git("rev-parse", f"{source}^{{tree}}")
    tested_tree = git("rev-parse", f"{tested}^{{tree}}")
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
        "requires_source_head_success": lane == "base-merge" and identical,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tested", required=True)
    parser.add_argument("--base")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    plan = candidate_plan(source=args.source, tested=args.tested, lane=args.lane, base=args.base)
    print(json.dumps(plan, sort_keys=True))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"run_native={str(plan['native_execution_required']).lower()}\n")


if __name__ == "__main__":
    main()
