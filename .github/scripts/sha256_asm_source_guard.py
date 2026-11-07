"""Bind four reviewed tool stages to the unchanged fixed product tree."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from sha256_asm_proposal_evidence import identity, require
from sha256_asm_worktree_guard import verify_worktree


HERE = Path(__file__).resolve().parent
SPEC_PATH = ".github/scripts/sha256-asm-proposal-spec.json"
SPEC_RAW = (HERE / "sha256-asm-proposal-spec.json").read_bytes()
SPEC = json.loads(SPEC_RAW)
INPUT_PATHS = {
    SPEC_PATH,
    ".github/scripts/sha256-asm-source.patch",
    ".github/scripts/sha256-asm-metadata-shape.json",
    ".github/scripts/sha256_asm_lock_guards.py",
    ".github/scripts/sha256_asm_worktree_guard.py",
}
EVIDENCE_PATHS = {".github/scripts/sha256_asm_proposal_evidence.py"}
ANALYSIS_PATHS = {
    ".github/scripts/sha256_asm_source_guard.py",
    ".github/scripts/sha256_asm_platform_guards.py",
}
EXECUTOR_PATHS = {
    ".github/scripts/propose_sha256_asm_locks.py",
    ".github/workflows/hepta-sha256-asm-lock-proposal.yml",
}
ADDITIONS = INPUT_PATHS | EVIDENCE_PATHS | ANALYSIS_PATHS | EXECUTOR_PATHS
LOCKS = {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}
SOURCE_PATHS = {"codex-rs/hepta-contracts/Cargo.toml"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def git_environment(env=None):
    isolated = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    isolated.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    if env:
        require(set(env) == {"GIT_INDEX_FILE"}, "UNEXPECTED_GIT_ENV_OVERRIDE")
        isolated.update(env)
    return isolated


def git(root, *args, env=None):
    return subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=root,
        env=git_environment(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def require_index_flags(root):
    entries = git(root, "ls-files", "-v", "-z").split(b"\0")
    require(
        entries[-1] == b"" and all(entry.startswith(b"H ") for entry in entries[:-1]),
        "HIDDEN_INDEX_ENTRY",
    )


def tree_delta(root, before, after, expected):
    fields = git(
        root,
        "diff-tree",
        "--no-commit-id",
        "--no-renames",
        "--name-status",
        "-r",
        "-z",
        before,
        after,
    ).split(b"\0")
    require(fields[-1] == b"" and len(fields) % 2 == 1, "INVALID_TREE_DELTA")
    changed = {
        fields[i + 1].decode(): fields[i].decode() for i in range(0, len(fields) - 1, 2)
    }
    require(
        len(changed) * 2 + 1 == len(fields) and changed == expected,
        "STAGE_PATH_DELTA_MISMATCH",
    )


def source_guard(root):
    require(
        SPEC["binding_status"] == "BOUND_REVIEWED_PARENT", "PROPOSAL_PARENT_NOT_BOUND"
    )
    layers = ("base", "inputs", "evidence", "analysis")
    for layer in layers:
        for suffix in ("head", "tree"):
            value = SPEC[layer + "_" + suffix]
            require(
                isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value),
                "INVALID_CHAIN_BINDING",
            )
    require(
        sys.platform == "linux" and os.environ["RUNNER_OS"] == "Linux",
        "WRONG_NATIVE_PLATFORM",
    )
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())[
        "pull_request"
    ]
    require(os.environ["GITHUB_EVENT_NAME"] == "pull_request", "WRONG_EVENT")
    require(
        event["head"]["repo"]["full_name"]
        == event["base"]["repo"]["full_name"]
        == "TrillionniumFoundation/hepta-private-ci",
        "WRONG_REPOSITORY",
    )
    require(
        event["base"]["sha"] == SPEC["analysis_head"]
        and event["base"]["ref"] == SPEC["analysis_ref"]
        and event["head"]["ref"] == SPEC["proposal_ref"],
        "WRONG_STAGE_EVENT",
    )
    head = git(root, "rev-parse", "HEAD").decode().strip()
    require(
        head == event["head"]["sha"] == os.environ["CANDIDATE_SHA"], "HEAD_MISMATCH"
    )
    chain = [SPEC[layer + "_head"] for layer in layers] + [head]
    deltas = (INPUT_PATHS, EVIDENCE_PATHS, ANALYSIS_PATHS, EXECUTOR_PATHS)
    for index, (parent, child) in enumerate(zip(chain, chain[1:])):
        require(
            git(root, "show", "-s", "--format=%P", child).decode().strip() == parent,
            "PARENT_MISMATCH",
        )
        expected = {p: "A" for p in deltas[index]}
        if index:
            expected[SPEC_PATH] = "M"
        tree_delta(root, parent, child, expected)
        if index:
            old = git(root, "show", parent + ":" + SPEC_PATH)
            new = git(root, "show", child + ":" + SPEC_PATH)
            for suffix in ("head", "tree"):
                name = layers[index] + "_" + suffix
                needle = ('"' + name + '": null').encode()
                require(old.count(needle) == 1, "STAGE_ALREADY_BOUND")
                old = old.replace(
                    needle, ('"' + name + '": "' + SPEC[name] + '"').encode()
                )
            require(old == new, "UNRELATED_SPEC_CHANGE")
    require(git(root, "show", "HEAD:" + SPEC_PATH) == SPEC_RAW, "WORKTREE_SPEC_CHANGED")
    require_index_flags(root)
    for layer in layers:
        require(
            git(root, "rev-parse", SPEC[layer + "_head"] + "^{tree}").decode().strip()
            == SPEC[layer + "_tree"],
            "CHAIN_TREE_MISMATCH",
        )
    require(
        not git(root, "status", "--porcelain=v1", "--untracked-files=all"),
        "DIRTY_INITIAL_SOURCE",
    )
    head_tree = git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    worktree = verify_worktree(root, git, SPEC["base_tree"], head_tree, ADDITIONS)
    require(
        worktree["base_leaves"] == SPEC["original_product_leaves"],
        "BASE_LEAF_COUNT_MISMATCH",
    )
    require(
        set(SPEC["passive_input_blobs"]) == ADDITIONS - {SPEC_PATH},
        "PASSIVE_INPUT_ROSTER_MISMATCH",
    )
    for path in ADDITIONS:
        body = root / path
        require(
            not body.is_symlink()
            and body.is_file()
            and body.stat().st_mode & 0o777 == 0o644,
            "PROPOSAL_WORKTREE_MODE_CHANGED",
        )
        item = git(root, "ls-tree", "HEAD", "--", path)
        require(item.startswith(b"100644 blob "), "PROPOSAL_MODE_CHANGED")
        require(
            git(root, "show", "HEAD:" + path) == body.read_bytes(),
            "PROPOSAL_WORKTREE_CHANGED",
        )
    for path, digest in SPEC["passive_input_blobs"].items():
        require(
            identity((root / path).read_bytes())["git_blob"] == digest,
            "PASSIVE_INPUT_CHANGED",
        )
    for path, digest in SPEC["baseline_blobs"].items():
        require(
            identity((root / path).read_bytes())["git_blob"] == digest,
            "BASELINE_BLOB_MISMATCH",
        )
    require(
        set(SPEC["locks"]) == LOCKS and LOCKS <= SPEC["baseline_blobs"].keys(),
        "MISSING_LOCK_AUTHORITY",
    )
    require(
        len(SPEC["source_files"]) == 1
        and {item["path"] for item in SPEC["source_files"]} == SOURCE_PATHS,
        "SOURCE_ROSTER_MISMATCH",
    )
    lock = tomllib.loads((root / "codex-rs/Cargo.lock").read_text())
    require(
        [p["version"] for p in lock["package"] if p["name"] == "vodozemac"]
        == ["0.11.2"],
        "VODOZEMAC_PRODUCT_NOT_INTEGRATED",
    )
    require(
        identity((HERE / "sha256-asm-source.patch").read_bytes())["sha256"]
        == SPEC["source_patch_sha256"],
        "SOURCE_PATCH_CHANGED",
    )
    for item in SPEC["source_files"]:
        body = root / item["path"]
        require(
            not body.is_symlink()
            and body.is_file()
            and body.stat().st_mode & 0o777 == 0o644,
            "SOURCE_MODE_CHANGED",
        )
        require(
            identity(body.read_bytes())["git_blob"] == item["before_blob"],
            "SOURCE_PREIMAGE_MISMATCH",
        )
    return {
        "head": head,
        "tree": head_tree,
        **{
            layer + "_" + suffix: SPEC[layer + "_" + suffix]
            for layer in layers
            for suffix in ("head", "tree")
        },
        "only_added_paths": sorted(ADDITIONS),
        "original_product_unchanged": True,
        "original_product_leaves": worktree["base_leaves"],
        "complete_worktree_verification": worktree,
    }


def private_directory():
    path = Path(os.environ["PRIVATE_EVIDENCE_DIR"])
    require(
        not path.is_symlink()
        and path.name.startswith("sha256-asm-proposal.")
        and path.parent.resolve(strict=True)
        == Path(os.environ["RUNNER_TEMP"]).resolve(strict=True),
        "INVALID_PRIVATE_DIRECTORY",
    )
    return path.resolve(strict=True)
