#!/usr/bin/env python3
"""Resolve one exact source/base pair for both evidence qualification lanes.

PR callers supply their event's base. Push/manual callers may supply a full base
OID; otherwise the source's first parent is used. No branch name is resolved at
execution time. A candidate plan is diagnostic and never grants qualification.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=root,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def resolve_candidate(root: Path, source: str, base: str = "") -> dict[str, Any]:
    """Reject aliases, dirty source, missing objects and duplicate parents."""
    if not isinstance(source, str) or OID.fullmatch(source) is None:
        raise ValueError("source must be a full lowercase Git object id")
    if base and (not isinstance(base, str) or OID.fullmatch(base) is None):
        raise ValueError("base must be a full lowercase Git object id")
    if git(root, "cat-file", "-t", source) != "commit":
        raise ValueError("source object is not a commit")
    if git(root, "rev-parse", "HEAD") != source:
        raise ValueError("checked-out source differs from the requested source")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("candidate checkout is dirty")
    selection = "explicit-base"
    if not base:
        parents = git(root, "rev-list", "--parents", "-n", "1", source).split()[1:]
        if not parents:
            raise ValueError("root source requires an explicit, distinct merge base")
        base, selection = parents[0], "source-first-parent"
    if len(base) != len(source) or base == source:
        raise ValueError(
            "base and source must be distinct commits in the same object format"
        )
    if git(root, "cat-file", "-t", base) != "commit":
        raise ValueError("base object is not a commit")
    return {
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "kind": "candidate-plan",
        "resolved": True,
        "sourceCommit": source,
        "sourceTree": git(root, "rev-parse", f"{source}^{{tree}}"),
        "baseCommit": base,
        "baseSelection": selection,
        "expectedMergeParents": [base, source],
        "qualificationGranted": False,
    }


def write_diagnostic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, pending_name = tempfile.mkstemp(dir=path.parent, prefix=".candidate-")
    pending = Path(pending_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        root = Path(git(args.root, "rev-parse", "--show-toplevel")).resolve()
        for output in (args.diagnostic, args.github_env, args.github_output):
            if output is not None and output.resolve().is_relative_to(root):
                raise ValueError(
                    "candidate diagnostics and runner outputs must be outside source"
                )
        plan = resolve_candidate(root, args.source, args.base)
        write_diagnostic(args.diagnostic, plan)
        for path, content in (
            (args.github_env, f"BASE_SHA={plan['baseCommit']}\n"),
            (
                args.github_output,
                f"base-sha={plan['baseCommit']}\nsource-sha={plan['sourceCommit']}\n",
            ),
        ):
            if path is not None:
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(content)
        print(json.dumps(plan, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        failure = {
            "schemaVersion": 1,
            "module": "kernel.evidence",
            "kind": "candidate-plan",
            "resolved": False,
            "qualificationGranted": False,
            "error": str(error),
        }
        # Never write a diagnostic into the candidate whose cleanliness is being proved.
        try:
            root = Path(git(args.root, "rev-parse", "--show-toplevel")).resolve()
            if not args.diagnostic.resolve().is_relative_to(root):
                write_diagnostic(args.diagnostic, failure)
        except (OSError, subprocess.SubprocessError):
            pass
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
