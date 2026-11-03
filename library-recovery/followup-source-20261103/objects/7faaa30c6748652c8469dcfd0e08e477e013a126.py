#!/usr/bin/env python3
"""Guarded single-file application of the hosted Bazel lock evidence (NOT qualification)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCE_COMMIT = '1ead6fff98e7dc84674068203a3fc575538d88c4'
BASE_BLOB = '84505f4ada83dfc5a69c8a90b33b8f055ed768ce'
TARGET_SHA256 = 'b1faa4909507860f4420ea014fd8785d7c914b6089c7d4a483cfe7f28a75921b'


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, default=Path.cwd())
    ap.add_argument('--apply', action='store_true', help='After successful checks replace MODULE.bazel.lock')
    ns = ap.parse_args()
    repo = ns.repo.resolve()
    target = repo / 'MODULE.bazel.lock'
    evidence = Path(__file__).resolve().parent / 'MODULE.bazel.lock'
    if git('-C', str(repo), 'rev-parse', 'HEAD') != SOURCE_COMMIT:
        raise RuntimeError('refusing: HEAD differs from the exact hosted generation source commit')
    if git('-C', str(repo), 'status', '--porcelain'):
        raise RuntimeError('refusing: worktree is not clean')
    if git('-C', str(repo), 'hash-object', str(target)) != BASE_BLOB:
        raise RuntimeError('refusing: old Bazel lock blob mismatches qualified baseline')
    data = evidence.read_bytes()
    if hashlib.sha256(data).hexdigest() != TARGET_SHA256:
        raise RuntimeError('refusing: generated evidence sha256 mismatch')
    if not isinstance(json.loads(data), dict):
        raise RuntimeError('refusing: invalid lock file structure')
    if not ns.apply:
        print('Guard checks PASS. No files changed. --apply is required to replace lock.')
        return
    fd, temporary = tempfile.mkstemp(prefix='.MODULE.bazel.lock.', dir=repo)
    try:
        with os.fdopen(fd, 'wb') as dst:
            dst.write(data)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    if hashlib.sha256(target.read_bytes()).hexdigest() != TARGET_SHA256:
        raise RuntimeError('post-write lock digest mismatch')
    print('Lock evidence applied to exact source; Rust/Bazel/security CI remains REQUIRED.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        sys.exit(1)
