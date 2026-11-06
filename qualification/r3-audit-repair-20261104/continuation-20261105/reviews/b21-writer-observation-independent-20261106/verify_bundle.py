#!/usr/bin/env python3
"""Replay only the two fixed Python evidence verifiers in fresh storage."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def identity(b):
    return {"bytes": len(b), "git_blob": hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest(), "sha256": hashlib.sha256(b).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    r = args.root.resolve()
    out = args.output.resolve() if args.output else r / "new-offline-replay"
    assert not out.exists()
    a = r / "frozen-author"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    author = subprocess.run([sys.executable, str(a / "verify_candidate.py"), "--root", str(a), "--output", str(out)], capture_output=True, env=env)
    assert author.returncode == 0 and author.stderr == b"", author.stderr
    assert author.stdout == (r / "replay-01.stdout.json").read_bytes()
    for name in ("VERIFICATION.json", "candidate.patch", "intended-full-tree.json"):
        assert (out / name).read_bytes() == (r / "replay-01" / name).read_bytes()
    independent = subprocess.run([sys.executable, str(r / "verify_independent.py"), "--root", str(r)], capture_output=True, env=env)
    assert independent.returncode == 0 and independent.stderr == b"", independent.stderr
    assert independent.stdout == (r / "INDEPENDENT_VERIFICATION.stdout.json").read_bytes()
    print(json.dumps({"author_exit": 0, "author_stderr_bytes": 0, "author_stdout": identity(author.stdout), "independent_exit": 0, "independent_stderr_bytes": 0, "independent_stdout": identity(independent.stdout), "three_replayed_products_equal": True, "network_or_Rust_or_native_operations": 0, "qualification": "Test-observation source review only; B21 remains OPEN."}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
