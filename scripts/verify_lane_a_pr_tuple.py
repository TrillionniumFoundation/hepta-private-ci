#!/usr/bin/env python3
"""Bind Lane A source validation to the immutable GitHub pull-request event."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")


class TupleError(RuntimeError):
    pass


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def verify(event_path: Path) -> None:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    if "pull_request" not in event:
        print("lane-a PR tuple: skipped for non-pull-request event")
        return
    pull_request = event["pull_request"]
    if not isinstance(pull_request, dict):
        raise TupleError("invalid pull-request event")
    # Event SHAs are the identity authority. A mutable PR description is neither
    # an identity source nor a second registry that authors must synchronize.
    expected = {}
    for role in ("base", "head"):
        identity = pull_request[role]
        sha = identity["sha"]
        if not isinstance(sha, str) or not HEX40.fullmatch(sha):
            raise TupleError(f"invalid pull-request {role} SHA")
        if git_value("rev-parse", "--verify", f"{sha}^{{commit}}") != sha:
            raise TupleError(f"pull-request {role} is not an exact commit")
        expected[f"{role}_branch"] = identity["ref"]
        expected[f"{role}_sha"] = sha
        expected[f"{role}_tree"] = git_value("rev-parse", f"{sha}^{{tree}}")
    if git_value("rev-parse", "HEAD") != expected["head_sha"]:
        raise TupleError("checkout is not the pull-request head")
    git_value("diff", "--exit-code", "HEAD", "--")
    expected["merge_base"] = git_value(
        "merge-base", expected["base_sha"], expected["head_sha"]
    )
    expected["commits"] = int(
        git_value(
            "rev-list", "--count", f"{expected['base_sha']}..{expected['head_sha']}"
        )
    )
    print("lane-a PR source identity: " + json.dumps(expected, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        verify(args.event)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
        TupleError,
    ) as error:
        print(f"lane-a PR tuple verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
