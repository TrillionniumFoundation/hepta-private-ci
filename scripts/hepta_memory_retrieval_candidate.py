#!/usr/bin/env python3
"""Bind retrieval CI to fetched main and construct an ordered deterministic merge.

Ref discovery does not fetch, approve, or mutate a branch. The workflow must
fetch the repository before invoking it. Synthetic commits are unreferenced
Git objects, never pushes, and are not passing qualification receipts.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


class CandidateError(ValueError):
    pass


def exact_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise CandidateError("an exact lowercase commit SHA is required")
    return value


def git(root, *args, input_text=None, env=None):
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=input_text, text=True,
        capture_output=True, timeout=60, check=False, env=env,
    )
    if result.returncode:
        raise CandidateError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def refs(root, source):
    source = exact_sha(source)
    if git(root, "rev-parse", "HEAD") != source:
        raise CandidateError("source is not the checked out HEAD")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise CandidateError("candidate checkout is dirty")
    main = exact_sha(git(root, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}"))
    # PR event base.sha can lag the fetched main. It is provenance only.
    # On a main push, use its first parent to avoid duplicate merge parents.
    base = main if main != source else exact_sha(git(root, "rev-parse", f"{source}^1"))
    return {"source_sha": source, "base_sha": base, "main_sha": main}


def synthetic_commit(root, base, source):
    base, source = exact_sha(base), exact_sha(source)
    if base == source:
        raise CandidateError("synthetic merge requires distinct ordered parents")
    for value in (base, source):
        if git(root, "rev-parse", "--verify", f"{value}^{{commit}}") != value:
            raise CandidateError("parent is not the exact commit object")
    tree = exact_sha(git(root, "merge-tree", "--write-tree", base, source))
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "Memory retrieval qualification",
        "GIT_AUTHOR_EMAIL": "qualification@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "Memory retrieval qualification",
        "GIT_COMMITTER_EMAIL": "qualification@users.noreply.github.com",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
    })
    commit = exact_sha(git(
        root, "-c", "commit.gpgSign=false", "commit-tree", tree,
        "-p", base, "-p", source,
        input_text="Deterministic memory retrieval qualification\n", env=env,
    ))
    if git(root, "show", "-s", "--format=%P", commit).split() != [base, source]:
        raise CandidateError("synthetic parent order differs from declared order")
    if git(root, "rev-parse", f"{commit}^{{tree}}") != tree:
        raise CandidateError("synthetic tree differs from computed merge")
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("refs", "merge"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", required=True)
    parser.add_argument("--base")
    args = parser.parse_args()
    try:
        if args.command == "refs":
            if args.base is not None:
                raise CandidateError("base override is forbidden during ref discovery")
            for key, value in refs(args.root, args.source).items():
                print(f"{key}={value}")
        else:
            print(synthetic_commit(args.root, args.base, args.source))
    except (CandidateError, OSError, subprocess.TimeoutExpired) as error:
        print(f"memory.retrieval candidate refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
