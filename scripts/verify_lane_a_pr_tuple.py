#!/usr/bin/env python3
"""Fail when the Lane A pull-request exact-subject block is stale."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BEGIN = "<!-- lane-a-exact-subject:v4 -->"
END = "<!-- /lane-a-exact-subject:v4 -->"
FIELDS = {
    "base branch": "base_branch",
    "base SHA": "base_sha",
    "head branch": "head_branch",
    "head SHA": "head_sha",
    "head tree": "head_tree",
    "commits": "commits",
}


class TupleError(RuntimeError):
    pass


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def parse_block(body: str) -> dict[str, str]:
    if body.count(BEGIN) != 1 or body.count(END) != 1:
        raise TupleError(
            "PR body must contain exactly one Lane A exact-subject v4 block"
        )
    block = body.split(BEGIN, 1)[1].split(END, 1)[0]
    values: dict[str, str] = {}
    for line in block.splitlines():
        match = re.fullmatch(r"\s*([^:]+):\s*(\S+)\s*", line)
        if not match:
            continue
        label, value = match.groups()
        if label in FIELDS:
            values[FIELDS[label]] = value
    missing = sorted(set(FIELDS.values()) - set(values))
    if missing:
        raise TupleError(f"exact-subject block missing fields: {missing}")
    return values


def verify(event_path: Path) -> None:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        print("lane-a PR tuple: skipped for non-pull-request event")
        return
    body = pull_request.get("body") or ""
    observed = parse_block(body)
    expected = {
        "base_branch": pull_request["base"]["ref"],
        "base_sha": pull_request["base"]["sha"],
        "head_branch": pull_request["head"]["ref"],
        "head_sha": pull_request["head"]["sha"],
        "head_tree": git_value("rev-parse", "HEAD^{tree}"),
        "commits": str(pull_request["commits"]),
    }
    if git_value("rev-parse", "HEAD") != expected["head_sha"]:
        raise TupleError("checkout is not the pull-request head")
    mismatches = {
        key: {"body": observed[key], "event": value}
        for key, value in expected.items()
        if observed[key] != value
    }
    if mismatches:
        raise TupleError(f"stale Lane A exact-subject tuple: {mismatches}")
    print("lane-a PR exact-subject tuple: ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        verify(args.event)
    except (
        OSError,
        KeyError,
        ValueError,
        subprocess.SubprocessError,
        TupleError,
    ) as error:
        print(f"lane-a PR tuple verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
