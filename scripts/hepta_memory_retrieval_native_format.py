#!/usr/bin/env python3
"""Scoped native formatting helper. Never updates a ref or grants qualification."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOTS = ("codex-rs/hepta-agentd/src/", "codex-rs/hepta-memory/src/", "codex-rs/hepta-memory-retrieval/src/")
SHA = re.compile(r"[0-9a-f]{40}\Z")

class FormatError(ValueError):
    pass

def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        raise FormatError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.rstrip("\n")

def safe_source(path):
    return (isinstance(path, str) and path.endswith(".rs") and path.startswith(ROOTS)
            and ".." not in Path(path).parts and not any(c in path for c in "\\\x00\r\n"))

def prepare(root, base, head):
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        raise FormatError("exact lowercase source commits are required")
    if git(root, "rev-parse", "HEAD") != head:
        raise FormatError("requested candidate is not the checkout")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise FormatError("formatting requires a clean checkout")
    git(root, "merge-base", "--is-ancestor", base, head)
    names = git(root, "diff", "--name-only", "-z", "--diff-filter=AM", base, head, "--", *ROOTS)
    paths = sorted(p for p in names.split("\x00") if p.endswith(".rs"))
    if not paths:
        raise FormatError("no changed retrieval Rust inputs")
    root = Path(root).resolve()
    for path in paths:
        target = root / path
        if not safe_source(path) or target.is_symlink() or not target.is_file() or target.resolve() != target:
            raise FormatError("unsafe or redirected Rust source")
    return paths

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        root, output = args.root.resolve(), args.output.resolve()
        if output == root or root in output.parents:
            raise FormatError("diagnostics must be outside the checkout")
        paths = prepare(root, args.base, args.head)
        output.mkdir(parents=True, exist_ok=True)
        command = ["rustup", "run", "1.95.0", "rustfmt", "--edition", "2024", "--config-path",
                   str(root / "codex-rs/rustfmt.toml"), *paths]
        with (output / "rustfmt.log").open("wb") as log:
            result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=300, check=False)
        if result.returncode:
            raise FormatError(f"native rustfmt failed with exit {result.returncode}")
        changed = set(filter(None, git(root, "diff", "--name-only", "-z").split("\x00")))
        unrelated = sorted(changed.difference(paths))
        if unrelated:
            git(root, "restore", "--source", args.head, "--", *unrelated)
        git(root, "diff", "--check")
        if git(root, "ls-files", "--others", "--exclude-standard"):
            raise FormatError("formatter created untracked files")
        actual = sorted(filter(None, git(root, "diff", "--name-only", "-z").split("\x00")))
        if any(p not in paths for p in actual):
            raise FormatError("formatter changed undeclared source")
        patch = subprocess.run(["git", "-C", str(root), "diff", "--binary"], capture_output=True, timeout=60, check=True).stdout
        (output / "format.patch").write_bytes(patch)
        version = subprocess.run(["rustup", "run", "1.95.0", "rustfmt", "--version"], capture_output=True, text=True, timeout=60, check=True).stdout.strip()
        receipt = {"schema": "hepta.retrieval.native-format.v1", "input_head": args.head,
                   "input_tree": git(root, "rev-parse", "HEAD^{tree}"), "base": args.base, "tool": version,
                   "source_paths": paths, "formatted_paths": actual, "patch_sha256": hashlib.sha256(patch).hexdigest(),
                   "native_compilation_proved": False, "production_activation": False}
        (output / "format.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (FormatError, OSError, subprocess.SubprocessError) as error:
        print(f"retrieval native formatting refused: {error}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
