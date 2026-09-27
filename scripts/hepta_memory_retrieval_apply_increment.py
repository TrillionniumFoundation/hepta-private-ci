#!/usr/bin/env python3
"""Apply one owner-scoped reviewed source increment; never push or claim qualification.

The payload is a zlib/base64 UTF-8 git patch with original and resulting Git blob
identities. --extract emits the ordinary reviewable diff without changing source.
The runner verifies both identities before a separate native formatting commit.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zlib

ROOTS = ("codex-rs/hepta-agentd/src/", "codex-rs/hepta-memory/src/", "codex-rs/hepta-memory-retrieval/src/", "codex-rs/hepta-learning-ledger/src/")
LIMIT = 2 * 1024 * 1024
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

class PatchError(ValueError):
    pass

def git(root, *args, data=None, check=True):
    result = subprocess.run(["git", "-C", str(root), *args], input=data, capture_output=True, timeout=60, check=False)
    if check and result.returncode:
        raise PatchError(f"git {args[0]} failed: {result.stderr.decode(errors='replace').strip()}")
    return result

def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise PatchError("duplicate payload field")
        result[key] = value
    return result

def safe_path(path):
    return (isinstance(path, str) and path.startswith(ROOTS) and path.endswith(".rs")
            and all(part not in ("", ".", "..") for part in path.split("/"))
            and not any(char in path for char in "\\\x00\r\n\t"))

def decode(raw, expected_digest):
    if not isinstance(expected_digest, str) or not HEX64.fullmatch(expected_digest):
        raise PatchError("an exact patch pin is required")
    if not raw or len(raw) > LIMIT:
        raise PatchError("payload byte bound")
    payload = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(payload, dict) or set(payload) != {"schema", "ancestor", "sha256", "bytes", "files", "patch_zlib_base64"}:
        raise PatchError("payload shape")
    if payload["schema"] != "hepta.retrieval.authorized-patch.v1" or not HEX40.fullmatch(payload["ancestor"]):
        raise PatchError("payload identity")
    if type(payload["bytes"]) is not int or not 0 < payload["bytes"] <= LIMIT:
        raise PatchError("patch byte bound")
    compressed = base64.b64decode(payload["patch_zlib_base64"], validate=True)
    decoder = zlib.decompressobj()
    patch = decoder.decompress(compressed, LIMIT + 1)
    if len(patch) > LIMIT or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise PatchError("compressed patch bound or trailing data")
    if len(patch) != payload["bytes"] or hashlib.sha256(patch).hexdigest() != expected_digest or payload["sha256"] != expected_digest:
        raise PatchError("patch digest/size mismatch")
    patch.decode("utf-8", errors="strict")
    files = payload["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= 64:
        raise PatchError("file count")
    seen = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "before", "after"} or not safe_path(item["path"]):
            raise PatchError("unsafe source path or file shape")
        if item["path"] in seen:
            raise PatchError("duplicate source path")
        seen.add(item["path"])
        if item["before"] is not None and (not isinstance(item["before"], str) or not HEX40.fullmatch(item["before"])):
            raise PatchError("invalid preimage")
        if not isinstance(item["after"], str) or not HEX40.fullmatch(item["after"]):
            raise PatchError("invalid postimage")
    return payload, patch

def apply(root, head, raw, pin):
    root = Path(root).resolve()
    payload, patch = decode(raw, pin)
    if not HEX40.fullmatch(head) or git(root, "rev-parse", "HEAD").stdout.strip().decode() != head:
        raise PatchError("checkout is not requested head")
    if git(root, "status", "--porcelain", "--untracked-files=normal").stdout:
        raise PatchError("dirty checkout")
    git(root, "merge-base", "--is-ancestor", payload["ancestor"], head)
    expected = {item["path"] for item in payload["files"]}
    actual = set()
    for row in git(root, "apply", "--numstat", "-z", "-", data=patch).stdout.split(b"\0"):
        if row:
            fields = row.decode().split("\t")
            if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
                raise PatchError("binary or renamed patch")
            actual.add(fields[2])
    if actual != expected:
        raise PatchError("patch path inventory differs from manifest")
    for item in payload["files"]:
        path = root / item["path"]
        if path.resolve() != path or path.is_symlink():
            raise PatchError("redirected source")
        entry = git(root, "ls-tree", "HEAD", "--", item["path"]).stdout.decode().strip()
        if item["before"] is None:
            if entry or path.exists():
                raise PatchError("new source already exists")
        elif not path.is_file() or entry != f"100644 blob {item['before']}\t{item['path']}":
            raise PatchError("source preimage or mode drift")
    git(root, "apply", "--index", "--check", "-", data=patch)
    git(root, "apply", "--index", "-", data=patch)
    for item in payload["files"]:
        path = root / item["path"]
        entry = git(root, "ls-files", "-s", "--", item["path"]).stdout.decode().strip()
        actual_blob = git(root, "hash-object", "--", item["path"]).stdout.decode().strip()
        if not path.is_file() or path.is_symlink() or path.resolve() != path or actual_blob != item["after"] or entry != f"100644 {item['after']} 0\t{item['path']}":
            raise PatchError("source postimage or mode mismatch; do not publish")
    staged = set(git(root, "diff", "--cached", "--name-only", "-z").stdout.decode().strip("\0").split("\0"))
    if staged != expected or git(root, "diff", "--name-only").stdout:
        raise PatchError("unexpected source changes")
    git(root, "diff", "--cached", "--check")
    return {"schema": "hepta.retrieval.patch-application.v1", "input_head": head, "patch_sha256": pin,
            "result_tree": git(root, "write-tree").stdout.decode().strip(), "paths": sorted(expected),
            "native_execution_proved": False, "production_activation": False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--head")
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--extract", type=Path)
    args = parser.parse_args()
    try:
        raw = args.payload.read_bytes()
        if args.extract is not None:
            _, patch = decode(raw, args.sha256)
            with args.extract.open("xb") as output:
                output.write(patch)
        else:
            if args.head is None:
                raise PatchError("exact head required for application")
            print(json.dumps(apply(args.root, args.head, raw, args.sha256), sort_keys=True))
        return 0
    except (PatchError, ValueError, TypeError, OSError, subprocess.SubprocessError, zlib.error) as error:
        print(f"retrieval source application refused: {error}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
