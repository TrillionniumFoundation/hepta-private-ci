#!/usr/bin/env python3
"""Source identity and explicit original-library groups for the composed owner."""
import hashlib
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "codex-rs"
HERE = Path(__file__).resolve().parent

NATIVE_GROUPS = {
    "path-fleet": ("codex-utils-path", "codex-hepta-fleet"),
    "agentd": ("codex-hepta-agentd",),
    "retained-memory": ("codex-utils-path", "codex-state", "codex-hepta-memory"),
}

BAZEL_GROUPS = {
    "fleet-owner": {
        "path": "//codex-rs/utils/path-utils:path-utils-unit-tests",
        "fleet": "//codex-rs/hepta-fleet:hepta-fleet-unit-tests",
        "agentd": "//codex-rs/hepta-agentd:hepta-agentd-unit-tests",
    },
    "retained-memory": {
        "path": "//codex-rs/utils/path-utils:path-utils-unit-tests",
        "state": "//codex-rs/state:state-unit-tests",
        "memory": "//codex-rs/hepta-memory:hepta-memory-unit-tests",
    },
}

BAZEL_SHARDS = {
    "fleet-owner": {"path": 1, "fleet": 1, "agentd": 1},
    "retained-memory": {"path": 1, "state": 4, "memory": 1},
}

def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def snapshot(*, verify_index=False):
    result = {}
    records = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-files", "--stage", "-z"], cwd=ROOT
    )
    for record in filter(None, records.split(b"\0")):
        header, name_raw = record.split(b"\t", 1)
        mode, expected, stage = header.decode("ascii").split()
        require(stage == "0", "unresolved index stage")
        name = os.fsdecode(name_raw)
        require(name not in result, "duplicate tracked input")
        require(mode in {"100644", "100755", "120000"}, "unsupported tracked object mode")
        path = ROOT / name
        raw = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        row = {"mode": mode, **identity(raw)}
        if verify_index:
            require(row["git_blob"] == expected, "checkout differs from immutable Git input: " + name)
        result[name] = row
    return result


def digest(raw):
    return hashlib.sha256(raw).hexdigest()
