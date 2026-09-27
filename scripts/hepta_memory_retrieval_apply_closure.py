#!/usr/bin/env python3
"""Apply the exact reviewed memory.retrieval assertion/delivery patch.

This helper is a transport verifier, not a qualification result. It accepts one
pinned multipart payload, validates its decompressed bytes and path inventory,
and stages only the reviewed source changes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zlib

PART_COUNT = 17
EXPECTED_BYTES = 40174
EXPECTED_SHA256 = "62a9878fbb406ab6683669391fb81bca6a8e47cd3aa559e5f05c11c7da17e868"
EXPECTED_PATHS = {
    "codex-rs/hepta-agentd/src/lib.rs",
    "codex-rs/hepta-agentd/src/production_writer_host.rs",
    "codex-rs/hepta-agentd/src/retrieval_delivery.rs",
    "codex-rs/hepta-agentd/src/retrieval_delivery_tests.rs",
    "codex-rs/hepta-memory/src/cognitive_proposition_writer.rs",
    "codex-rs/hepta-memory/src/production_writer.rs",
}


def object_pairs(rows: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in rows:
        if key in result:
            raise ValueError(f"duplicate payload field: {key}")
        result[key] = value
    return result


def run_git(root: Path, *args: str, data: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=data,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"git {args[0]} failed: {result.stderr.decode(errors='replace').strip()}"
        )
    return result


def decode(root: Path) -> tuple[bytes, str]:
    parts = [
        root / f"scripts/patches/memory_retrieval_assertion_delivery_v2.part{index:02d}"
        for index in range(PART_COUNT)
    ]
    missing = [str(path.relative_to(root)) for path in parts if not path.is_file()]
    if missing:
        raise ValueError(f"missing patch transport parts: {missing}")
    payload_bytes = b"".join(path.read_bytes() for path in parts)
    payload = json.loads(
        base64.b64decode(payload_bytes, validate=True), object_pairs_hook=object_pairs
    )
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "sha256",
        "bytes",
        "patch_zlib_base64",
    }:
        raise ValueError("invalid closure payload fields")
    if payload["schema"] != "hepta.retrieval.closure-patch.v1":
        raise ValueError("invalid closure payload schema")
    compressed = base64.b64decode(str(payload["patch_zlib_base64"]), validate=True)
    decoder = zlib.decompressobj()
    patch = decoder.decompress(compressed, EXPECTED_BYTES + 1)
    patch += decoder.flush()
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("invalid compressed closure payload")
    digest = hashlib.sha256(patch).hexdigest()
    if (
        len(patch) != EXPECTED_BYTES
        or payload["bytes"] != EXPECTED_BYTES
        or payload["sha256"] != EXPECTED_SHA256
        or digest != EXPECTED_SHA256
    ):
        raise ValueError("closure patch identity mismatch")
    patch.decode("utf-8", errors="strict")
    return patch, digest


def patch_paths(root: Path, patch: bytes) -> set[str]:
    output = run_git(root, "apply", "--numstat", "-z", "-", data=patch).stdout
    paths: set[str] = set()
    for row in output.split(b"\0"):
        if not row:
            continue
        fields = row.decode().split("\t")
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            raise ValueError("closure patch contains binary, rename, or invalid numstat row")
        paths.add(fields[2])
    return paths


def apply(root: Path) -> dict[str, object]:
    root = root.resolve()
    if run_git(root, "status", "--porcelain", "--untracked-files=normal").stdout:
        raise ValueError("closure patch requires a clean checkout")
    patch, digest = decode(root)
    actual = patch_paths(root, patch)
    if actual != EXPECTED_PATHS:
        raise ValueError(
            f"closure patch paths differ: expected {sorted(EXPECTED_PATHS)}, got {sorted(actual)}"
        )
    run_git(root, "apply", "--index", "--check", "-", data=patch)
    run_git(root, "apply", "--index", "-", data=patch)
    staged = set(
        run_git(root, "diff", "--cached", "--name-only", "-z").stdout.decode().strip("\0").split("\0")
    )
    if staged != EXPECTED_PATHS:
        raise ValueError(f"staged closure paths differ: {sorted(staged)}")
    if run_git(root, "diff", "--name-only").stdout:
        raise ValueError("closure patch left unstaged source changes")
    run_git(root, "diff", "--cached", "--check")
    return {
        "schema": "hepta.memory-retrieval.closure-application.v1",
        "input_head": run_git(root, "rev-parse", "HEAD").stdout.decode().strip(),
        "patch_sha256": digest,
        "paths": sorted(EXPECTED_PATHS),
        "production_activation": False,
        "release": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = apply(args.root)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt is None:
        print(encoded, end="")
    else:
        args.receipt.write_text(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
