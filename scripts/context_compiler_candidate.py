#!/usr/bin/env python3
"""Build/verify an immutable source or deterministic synthetic-merge candidate.

This tool checks out Git objects; it never edits source, formats code, generates
implementation, commits to a branch, or pushes. Execution evidence is separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

OID = re.compile(r"[0-9a-f]{40}\Z")


def git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "context-compiler-qualification",
        "GIT_AUTHOR_EMAIL": "context-compiler-qualification@invalid.example",
        "GIT_COMMITTER_NAME": "context-compiler-qualification",
        "GIT_COMMITTER_EMAIL": "context-compiler-qualification@invalid.example",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        "LC_ALL": "C",
    })
    return env


def git(root: Path, *args: str, stdin: str | None = None) -> str:
    process = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
         "-c", "core.fsmonitor=false", *args],
        cwd=root, env=git_env(), input=stdin, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    if process.returncode:
        raise ValueError(f"Git command rejected ({args[0]}, exit {process.returncode})")
    return process.stdout.strip()


def commit_oid(root: Path, value: str) -> str:
    if not OID.fullmatch(value) or git(root, "cat-file", "-t", value) != "commit":
        raise ValueError("expected an existing full commit OID")
    return value


def clean(root: Path) -> None:
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("candidate worktree is not clean")


def prepare(root: Path, source: str, base: str, lane: str) -> dict[str, Any]:
    root = root.resolve()
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("root must be the repository top level")
    source = commit_oid(root, source)
    base = commit_oid(root, base)
    if lane not in {"source-head", "synthetic-merge"}:
        raise ValueError("unsupported candidate lane")
    clean(root)
    if git(root, "rev-parse", "HEAD") != source:
        raise ValueError("checkout differs from the requested source head")
    tested = source
    if lane == "synthetic-merge":
        if base == source:
            raise ValueError("synthetic merge needs distinct ordered parents")
        tree = git(root, "merge-tree", "--write-tree", base, source).splitlines()[0]
        if not OID.fullmatch(tree) or git(root, "cat-file", "-t", tree) != "tree":
            raise ValueError("merge-tree did not produce an exact tree")
        tested = git(root, "commit-tree", tree, "-p", base, "-p", source,
                     stdin=f"context.compiler qualification\nbase={base}\nsource={source}\n")
        commit_oid(root, tested)
        if git(root, "show", "-s", "--format=%P", tested).split() != [base, source]:
            raise ValueError("synthetic merge parent order changed")
        git(root, "checkout", "--detach", tested)
    tree = git(root, "rev-parse", "HEAD^{tree}")
    record = {
        "schema": "hepta.context-compiler-candidate.v1", "lane": lane,
        "sourceHeadSha": source, "baseSha": base, "testedHeadSha": tested,
        "testedTreeSha": tree,
        "parents": git(root, "show", "-s", "--format=%P", tested).split(),
        "executionPassed": False, "independentAcceptance": False,
    }
    verify(root, record)
    return record


def verify(root: Path, record: dict[str, Any]) -> None:
    if record.get("schema") != "hepta.context-compiler-candidate.v1":
        raise ValueError("unknown candidate schema")
    for field in ("sourceHeadSha", "baseSha", "testedHeadSha"):
        commit_oid(root, record[field])
    if record.get("executionPassed") is not False or record.get("independentAcceptance") is not False:
        raise ValueError("source identity must not self-certify execution or acceptance")
    clean(root)
    if git(root, "rev-parse", "HEAD") != record["testedHeadSha"]:
        raise ValueError("tested commit changed")
    if git(root, "rev-parse", "HEAD^{tree}") != record["testedTreeSha"]:
        raise ValueError("tested tree changed")
    parents = git(root, "show", "-s", "--format=%P", "HEAD").split()
    if parents != record["parents"]:
        raise ValueError("candidate parent identity changed")
    if record["lane"] == "source-head":
        if record["testedHeadSha"] != record["sourceHeadSha"]:
            raise ValueError("source lane is not the requested source")
    elif record["lane"] == "synthetic-merge":
        if parents != [record["baseSha"], record["sourceHeadSha"]]:
            raise ValueError("merge does not bind ordered base/source parents")
        tree = git(root, "merge-tree", "--write-tree", *parents).splitlines()[0]
        if tree != record["testedTreeSha"]:
            raise ValueError("candidate is not the recomputed merge tree")
        expected_commit = git(root, "commit-tree", tree, "-p", record["baseSha"],
                              "-p", record["sourceHeadSha"],
                              stdin=f"context.compiler qualification\nbase={record['baseSha']}\nsource={record['sourceHeadSha']}\n")
        if expected_commit != record["testedHeadSha"]:
            raise ValueError("candidate merge metadata is not deterministic")
    else:
        raise ValueError("unsupported candidate lane")


def write_record(path: Path, record: dict[str, Any]) -> None:
    data = dict(record)
    data.pop("recordSha256", None)
    data["recordSha256"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source")
    parser.add_argument("--base")
    parser.add_argument("--lane", choices=["source-head", "synthetic-merge"])
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.record.resolve()
    if output == root or root in output.parents:
        parser.error("candidate evidence must be outside the source checkout")
    try:
        if args.verify:
            data = json.loads(output.read_text(encoding="utf-8"))
            digest = data.pop("recordSha256", None)
            expected = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if digest != expected:
                raise ValueError("candidate record digest mismatch")
            verify(root, data)
        else:
            if not args.source or not args.base or not args.lane:
                parser.error("source, base and lane are required")
            data = prepare(root, args.source, args.base, args.lane)
            write_record(output, data)
        print(json.dumps(data, sort_keys=True))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as error:
        print(f"candidate verification failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
