#!/usr/bin/env python3
"""One-shot exact-tree bootstrap for the inference.control closure."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
PATCH_PAYLOAD = ROOT / ".github/inference-control-closure.patch.gz.b64"
VERIFIER_PAYLOAD = ROOT / ".github/inference-control-actor-verifier.py.gz.b64"
EXPECTED_PARENT = "c5bf1fb779537e1285cc6fda8b69f05381589872"
PATCH_SHA256 = "f5a28e5845bcb80797add43c89770733efcf0ca0106b7f6e47a64eefc5632b08"
FINAL_SHA256 = "649e67017c21faf9e3055b354bb88b7dd314427d0969c0e06a7c4706d33b5b45"


def run(*args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args, cwd=ROOT, input=input_bytes, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )


def checked_payload(path: Path, expected: str, label: str) -> bytes:
    try:
        encoded = b"".join(path.read_bytes().split())
        value = gzip.decompress(base64.b64decode(encoded, validate=True))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{label} decode failed: {exc}") from exc
    observed = hashlib.sha256(value).hexdigest()
    if observed != expected:
        raise SystemExit(f"{label} digest mismatch: {observed} != {expected}")
    return value


def apply() -> None:
    status = run("git", "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0 or status.stdout:
        raise SystemExit("bootstrap requires an exact clean checkout")
    parent = run("git", "rev-parse", "HEAD^")
    observed_parent = parent.stdout.decode().strip()
    if parent.returncode != 0 or observed_parent != EXPECTED_PARENT:
        raise SystemExit(
            f"bootstrap parent drift: {observed_parent} != {EXPECTED_PARENT}"
        )

    patch = checked_payload(PATCH_PAYLOAD, PATCH_SHA256, "closure patch")
    final = checked_payload(VERIFIER_PAYLOAD, FINAL_SHA256, "permanent verifier")
    check = run("git", "apply", "--check", "--whitespace=nowarn", "-", input_bytes=patch)
    if check.returncode != 0:
        raise SystemExit(check.stderr.decode(errors="replace"))
    applied = run("git", "apply", "--whitespace=nowarn", "-", input_bytes=patch)
    if applied.returncode != 0:
        raise SystemExit(applied.stderr.decode(errors="replace"))

    fd, temporary = tempfile.mkstemp(prefix=SELF.name + ".", dir=SELF.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(final)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o755)
        os.replace(temporary, SELF)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    PATCH_PAYLOAD.unlink()
    VERIFIER_PAYLOAD.unlink()

    verification = run(sys.executable, str(SELF), "check")
    if verification.returncode != 0:
        raise SystemExit(
            verification.stdout.decode(errors="replace")
            + verification.stderr.decode(errors="replace")
        )
    print(json.dumps({
        "applied_parent": EXPECTED_PARENT,
        "patch_sha256": PATCH_SHA256,
        "verifier_sha256": FINAL_SHA256,
    }, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("apply", "check"))
    args = parser.parse_args()
    if args.command == "apply":
        apply()
    else:
        raise SystemExit("one-shot bootstrap has not yet been applied")


if __name__ == "__main__":
    main()
