#!/usr/bin/env python3
"""Sharded exact-tree Cargo impact qualification with no package omissions.

The existing hepta_ci_dependencies planner remains the sole selector: this
module only partitions its FULL selected set across independent native runners.
Every shard recomputes the plan at the same tested SHA and verifies its own
membership before dispatching actual tests.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import hepta_ci_dependencies as dependencies

PACKAGE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*\Z")
MAX_SHARDS = 128


def matrix_for_packages(packages: list[str], maximum_per_shard: int = 12) -> dict:
    """Round-robin deterministic partition; exact set equality is mandatory."""
    if maximum_per_shard <= 0 or maximum_per_shard > 64:
        raise ValueError("maximum_per_shard must be between 1 and 64")
    if not isinstance(packages, list) or any(
        not isinstance(item, str) or not PACKAGE.fullmatch(item) for item in packages
    ):
        raise ValueError("selected package list contains an invalid name")
    if len(set(packages)) != len(packages):
        raise ValueError("duplicate selected Cargo package")
    selected = sorted(packages)
    number = max(1, (len(selected) + maximum_per_shard - 1) // maximum_per_shard)
    if number > MAX_SHARDS:
        raise ValueError("impact plan exceeds maximum safe matrix capacity")
    groups: list[list[str]] = [[] for _ in range(number)]
    for i, package in enumerate(selected):
        groups[i % number].append(package)
    matrix = {"include": [{"index": i, "packages": group} for i, group in enumerate(groups)]}
    # Do not allow a benign-looking matrix to omit reverse consumers.
    flattened = [p for item in matrix["include"] for p in item["packages"]]
    if sorted(flattened) != selected or any(
        len(group) > maximum_per_shard for group in groups
    ):
        raise ValueError("shard coverage or resource bound mismatch")
    return matrix


def verify_shard(matrix: dict, index: int, expected_packages: list[str]) -> list[str]:
    if not isinstance(index, int) or index < 0:
        raise ValueError("invalid shard index")
    rows = matrix.get("include", [])
    if not isinstance(rows, list) or index >= len(rows):
        raise ValueError("shard index outside exact impact matrix")
    row = rows[index]
    if row.get("index") != index or row.get("packages") != expected_packages:
        raise ValueError("shard does not match exact source/base impact plan")
    return expected_packages


def check_checkout(root: Path, tested: str) -> None:
    if not dependencies.OID.fullmatch(tested):
        raise ValueError("tested identity must be an exact commit SHA")
    observed = dependencies.git(root, "rev-parse", "HEAD").decode().strip()
    if observed != tested:
        raise ValueError("checkout is not the exact tested SHA")
    dependencies.git(root, "diff", "--no-ext-diff", "--quiet", "HEAD", "--")


def make_plan(root: Path, base: str, tested: str, limit: int) -> tuple[dict, dict]:
    check_checkout(root, tested)
    selected = dependencies.plan(root, base, tested)
    matrix = matrix_for_packages(selected["packages"], limit)
    return selected, matrix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--tested", required=True)
    parser.add_argument("--max-packages", type=int, default=12)
    parser.add_argument("--action", choices=("plan", "test"), default="plan")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--record-output", type=Path)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--expected-packages-json")
    args = parser.parse_args()

    root = args.root.resolve()
    selected, matrix = make_plan(root, args.base, args.tested, args.max_packages)
    result = {
        "schema": "hepta-ci-sharded-cargo-impact-v1",
        "base_sha": args.base,
        "tested_sha": args.tested,
        "selected": selected,
        "matrix": matrix,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "tested_sha": args.tested,
                "package_count": len(selected["packages"]),
                "shard_count": len(matrix["include"]),
                "full_workspace": selected["full_workspace"],
                "reasons": selected["reasons"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if args.action == "plan":
        if args.shard_index is not None or args.expected_packages_json is not None:
            parser.error("shard parameters require --action test")
        if args.github_output is None:
            parser.error("--github-output required to publish exact matrix")
        compact_matrix = json.dumps(matrix, sort_keys=True, separators=(",", ":"))
        with args.github_output.open("a", encoding="utf-8") as out:
            out.write("matrix=" + compact_matrix + "\n")
        return

    if args.github_output or args.shard_index is None or args.expected_packages_json is None:
        parser.error("--action test requires shard index and expected packages")
    if args.record_output is None:
        parser.error("--record-output is mandatory for real tests")
    try:
        expected = json.loads(args.expected_packages_json)
        packages = verify_shard(matrix, args.shard_index, expected)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    if not packages:
        if selected["packages"]:
            parser.error("empty shard with nonempty exact impact plan")
        print("No affected packages: zero-test selection proven from exact impact plan")
        return
    command = [
        sys.executable,
        str(Path(__file__).resolve().with_name("hepta_ci_exec.py")),
        "--output",
        str(args.record_output.resolve()),
        "--",
        "just",
        "test",
        "--locked",
    ]
    for package in packages:
        command.extend(("-p", package))
    completed = subprocess.run(command, cwd=root / dependencies.WORKSPACE, check=False)
    check_checkout(root, args.tested)
    raise SystemExit(completed.returncode if completed.returncode >= 0 else 128 - completed.returncode)


if __name__ == "__main__":
    main()
