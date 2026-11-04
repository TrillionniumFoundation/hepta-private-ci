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


OBJECTIVE_SENDER_CHILD = "production_writer::objective_sender::crash_tests::objective_sender_subprocess_fixture"
OBJECTIVE_SENDER_PARENTS = {
    "production_writer::objective_sender::crash_tests::a_second_real_process_and_different_lease_still_cannot_send_retained_run",
    "production_writer::objective_sender::crash_tests::process_death_after_each_committed_cut_recovers_without_new_send_permission",
}


def memory_ignored_cases(config, system):
    require(system in {"Linux", "Darwin", "Windows"}, "unsupported memory inventory host")
    original = config["original_ignored_memory_cases"]
    require(len(original) == len(set(original)), "duplicate original ignored case")
    children = config["original_ignored_memory_unix_subprocess_cases"]
    require(children == [OBJECTIVE_SENDER_CHILD], "unexpected Unix subprocess fixture")
    require(set(config["original_memory_unix_process_parents"]) == OBJECTIVE_SENDER_PARENTS,
            "changed original subprocess parent contract")
    require(not (set(original) & (set(children) | OBJECTIVE_SENDER_PARENTS)),
            "subprocess case cannot replace an original ignored probe")
    return sorted([*original, *children] if system in {"Linux", "Darwin"} else original)


def require_memory_process_cases(all_cases, expected, system):
    require(system in {"Linux", "Darwin", "Windows"}, "unsupported memory inventory host")
    all_names, executed = set(all_cases), set(expected)
    if system == "Windows":
        require(not (({OBJECTIVE_SENDER_CHILD} | OBJECTIVE_SENDER_PARENTS) & all_names),
                "Unix subprocess cases unexpectedly compiled on Windows")
    else:
        require(OBJECTIVE_SENDER_CHILD in all_names and OBJECTIVE_SENDER_CHILD not in executed,
                "original Unix subprocess fixture inventory changed")
        require(OBJECTIVE_SENDER_PARENTS <= executed,
                "both original Unix subprocess parents must execute")
