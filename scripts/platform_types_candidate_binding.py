#!/usr/bin/env python3
"""Bind both qualification lanes to one resolved source/base pair.

This is read-only with respect to tracked source. Output files are evidence,
not qualification receipts. No shell expansion, fallback ref, or moving branch
is used after resolution. A failed invocation never emits GitHub job outputs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise ValueError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def checked_ref(value: str) -> str:
    if not value or value.startswith("-") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("reference must be nonempty and contain no option prefix or control characters")
    return value


def resolve_commit(root: Path, reference: str) -> str:
    reference = checked_ref(reference)
    commit = git(root, "rev-parse", "--verify", "--end-of-options", reference + "^{commit}")
    if not SHA_RE.fullmatch(commit):
        raise ValueError("Git did not return one full commit object ID")
    return commit


def clean_tracked_source(root: Path) -> None:
    # --ignore-submodules=none prevents a changed submodule from being hidden.
    if git(root, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=none"):
        raise ValueError("tracked source is dirty; refusing candidate binding")


def resolve_binding(root: Path, source_ref: str, base_ref: str) -> dict[str, Any]:
    clean_tracked_source(root)
    source = resolve_commit(root, source_ref)
    base = resolve_commit(root, base_ref)
    if resolve_commit(root, "HEAD") != source:
        raise ValueError("checkout does not match the requested source reference")
    return {
        "schema": "hepta.platform.types.candidate-binding.v1",
        "requested_source_ref": source_ref,
        "requested_base_ref": base_ref,
        "source_sha": source,
        "source_tree": git(root, "rev-parse", source + "^{tree}"),
        "base_sha": base,
        "base_tree": git(root, "rev-parse", base + "^{tree}"),
        "qualification_passed": False,
    }


def verify_checkout(root: Path, source_sha: str, base_sha: str) -> dict[str, str]:
    for value in (source_sha, base_sha):
        if not SHA_RE.fullmatch(value):
            raise ValueError("verification requires frozen full object IDs, not refs")
    clean_tracked_source(root)
    if resolve_commit(root, "HEAD") != source_sha:
        raise ValueError("checkout differs from the frozen source candidate")
    if resolve_commit(root, source_sha) != source_sha or resolve_commit(root, base_sha) != base_sha:
        raise ValueError("frozen commit object is unavailable")
    return {
        "source_sha": source_sha,
        "source_tree": git(root, "rev-parse", source_sha + "^{tree}"),
        "base_sha": base_sha,
        "base_tree": git(root, "rev-parse", base_sha + "^{tree}"),
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            name = stream.name
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--source-ref", required=True)
    resolve.add_argument("--base-ref", required=True)
    resolve.add_argument("--output", required=True, type=Path)
    resolve.add_argument("--github-output", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    try:
        if args.command == "resolve":
            payload = resolve_binding(args.repo_root, args.source_ref, args.base_ref)
            atomic_json(args.output, payload)
            if args.github_output is not None:
                # Only full, validated object IDs enter the runner output file.
                with args.github_output.open("a", encoding="utf-8") as stream:
                    for key in ("source_sha", "source_tree", "base_sha", "base_tree"):
                        if not SHA_RE.fullmatch(payload[key]):
                            raise ValueError("invalid object ID in resolved binding")
                        stream.write(f"{key}={payload[key]}\n")
        else:
            payload = verify_checkout(args.repo_root, args.source_sha, args.base_sha)
        print(json.dumps(payload, sort_keys=True))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"candidate binding failed: {exc}\n")


if __name__ == "__main__":
    main()
