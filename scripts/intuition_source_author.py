#!/usr/bin/env python3
"""Recover the immutable reviewed intuition.policy patch and apply it to the index.

This is authoring scaffolding only.  The published source commit removes this file.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

REPOSITORY = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
EXPECTED_BASE = "696447e733e22e425cd05691d98f4fe0ef63f759"
EXPECTED_PATCH_SHA256 = "d9988033416a6bf64588b593c34496abba4d3f66a20df57d749a6308500ca3dc"
EXPECTED_BLOBS = (
    "ff90ec4b0bb594c6659c0805f7683e625f423d46",
    "8ef03a50ccef25591918ed67fb42506bcfdd21f1",
    "627e323cc4086e712a04ffa58b02e7723415e64c",
)


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def read_ready() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(".github/intuition-authoring-patch/READY").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip()
    expected = {
        "base": EXPECTED_BASE,
        "part-000": EXPECTED_BLOBS[0],
        "part-001": EXPECTED_BLOBS[1],
        "part-002": EXPECTED_BLOBS[2],
    }
    if any(values.get(key) != value for key, value in expected.items()):
        raise SystemExit("reviewed patch manifest does not match pinned identities")
    return values


def fetch_blob(sha: str) -> bytes:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/git/blobs/{sha}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "intuition-reviewed-source-author",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    return base64.b64decode(payload["content"])


def recover_patch() -> bytes:
    encoded_parts = [b"".join(fetch_blob(sha).split()) for sha in EXPECTED_BLOBS]
    # The immutable review package records a single transport byte at the start
    # of part 001.  Remove it, decode the combined envelope, and require the
    # independently recorded final digest before Git sees any bytes.
    candidates = [b"".join(encoded_parts)]
    candidates.extend(
        encoded_parts[0] + encoded_parts[1][:index] + encoded_parts[1][index + 1 :] + encoded_parts[2]
        for index in range(len(encoded_parts[1]))
    )
    matches: list[bytes] = []
    for candidate in candidates:
        try:
            patch = base64.b64decode(candidate, validate=True)
        except ValueError:
            continue
        if hashlib.sha256(patch).hexdigest() == EXPECTED_PATCH_SHA256:
            matches.append(patch)
    if len(matches) != 1:
        raise SystemExit(f"expected one exact patch reconstruction, found {len(matches)}")
    patch = matches[0]
    if not patch.startswith(b"diff --git a/"):
        raise SystemExit("reviewed object is not a Git patch")
    return patch


def main() -> None:
    read_ready()
    run("git", "cat-file", "-e", f"{EXPECTED_BASE}^{{commit}}")
    patch = recover_patch()
    target = Path(".git/intuition-source.patch")
    target.write_bytes(patch)
    Path(".git/intuition-source.patch.identity").write_text(
        f"sha256={EXPECTED_PATCH_SHA256}\nbytes={len(patch)}\n",
        encoding="utf-8",
    )
    run("git", "apply", "--check", str(target))
    run("git", "apply", "--index", str(target))

    cleanup = [
        ".github/intuition-authoring-patch",
        ".github/workflows/intuition-source-export.yml",
        ".github/workflows/intuition-source-author-arm.yml",
        ".github/workflows/intuition-source-author-macos.yml",
        ".github/workflows/intuition-source-author-v2.yml",
        ".github/workflows/intuition-source-author-rescue.yml",
        ".github/workflows/intuition-source-author-self-hosted.yml",
        ".github/workflows/intuition-source-author-pocket4.yml",
        ".github/workflows/intuition-reviewed-source-hosted.yml",
        "scripts/intuition_source_author.py",
    ]
    for raw in cleanup:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            path.rmdir()
        elif path.exists():
            path.unlink()
    print(
        "recovered and applied reviewed patch",
        EXPECTED_PATCH_SHA256,
        len(patch),
        repr(patch[-80:]),
    )


if __name__ == "__main__":
    main()
