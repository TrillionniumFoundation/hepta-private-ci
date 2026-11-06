#!/usr/bin/env python3
"""Produce a source-bound review artifact; never commit, push or change a ref."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
import traceback

from sdk_durable_lock_guards import (
    cargo_guard,
    canonical_metadata,
    metadata_guard,
    module_guard,
)
from sdk_durable_proposal_evidence import (
    collect,
    identity,
    metadata_projection,
    require,
    scanner,
)


HERE = Path(__file__).resolve().parent
SPEC_RAW = (HERE / "sdk-durable-proposal-spec.json").read_bytes()
SPEC = json.loads(SPEC_RAW)
GUARD_PATHS = {
    ".github/scripts/sdk_durable_lock_guards.py",
    ".github/scripts/sdk_durable_proposal_evidence.py",
}
SPEC_PATH = ".github/scripts/sdk-durable-proposal-spec.json"
INPUT_PATHS = {SPEC_PATH, ".github/scripts/sdk-durable-source.patch"}
EXECUTOR_PATHS = {
    ".github/workflows/hepta-sdk-durable-lock-proposal.yml",
    ".github/scripts/propose_sdk_durable_locks.py",
}
ADDITIONS = GUARD_PATHS | INPUT_PATHS | EXECUTOR_PATHS
STAGES = (
    "cargo-version",
    "rustc-version",
    "deny-version",
    "just-version",
    "bazel-version",
    "metadata-before",
    "baseline-module-check",
    "source-patch-check",
    "source-patch-apply",
    "metadata-generate",
    "metadata-repeat",
    "bazel-update",
    "bazel-check",
    "bazel-repeat",
    "bazel-check-repeat",
    "cargo-deny-original",
    "proposal-failure",
)
LOCKS = {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}
SOURCE_PATHS = {
    "codex-rs/utils/path-utils/src/lib.rs",
    "codex-rs/utils/path-utils/Cargo.toml",
    "codex-rs/utils/path-utils/src/durable_publish.rs",
    "codex-rs/utils/path-utils/src/durable_publish_tests.rs",
    "codex-rs/hepta-matrix-sdk/src/sdk.rs",
    "codex-rs/hepta-matrix-sdk/Cargo.toml",
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def git(root, *args, env=None):
    isolated = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    isolated.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    if env:
        require(set(env) == {"GIT_INDEX_FILE"}, "UNEXPECTED_GIT_ENV_OVERRIDE")
        isolated.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=root,
        env=isolated,
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
    for name in (
        "base_head",
        "base_tree",
        "guards_head",
        "guards_tree",
        "inputs_head",
        "inputs_tree",
    ):
        require(
            isinstance(SPEC[name], str) and re.fullmatch(r"[0-9a-f]{40}", SPEC[name]),
            "INVALID_CHAIN_BINDING",
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
        event["base"]["sha"] == SPEC["inputs_head"]
        and event["base"]["ref"] == SPEC["inputs_ref"]
        and event["head"]["ref"] == SPEC["proposal_ref"],
        "WRONG_STAGE_EVENT",
    )
    head = git(root, "rev-parse", "HEAD").decode().strip()
    require(
        head == event["head"]["sha"] == os.environ["CANDIDATE_SHA"], "HEAD_MISMATCH"
    )
    for child, parent in (
        (head, SPEC["inputs_head"]),
        (SPEC["inputs_head"], SPEC["guards_head"]),
        (SPEC["guards_head"], SPEC["base_head"]),
    ):
        require(
            git(root, "show", "-s", "--format=%P", child).decode().strip() == parent,
            "PARENT_MISMATCH",
        )
    require_index_flags(root)
    for layer in ("base", "guards", "inputs"):
        require(
            git(root, "rev-parse", SPEC[layer + "_head"] + "^{tree}").decode().strip()
            == SPEC[layer + "_tree"],
            "CHAIN_TREE_MISMATCH",
        )
    require(
        not git(root, "status", "--porcelain=v1", "--untracked-files=all"),
        "DIRTY_INITIAL_SOURCE",
    )
    tree_delta(
        root, SPEC["base_head"], SPEC["guards_head"], {p: "A" for p in GUARD_PATHS}
    )
    tree_delta(
        root, SPEC["guards_head"], SPEC["inputs_head"], {p: "A" for p in INPUT_PATHS}
    )
    tree_delta(
        root,
        SPEC["inputs_head"],
        head,
        {**{p: "A" for p in EXECUTOR_PATHS}, SPEC_PATH: "M"},
    )
    old_spec = git(root, "show", SPEC["inputs_head"] + ":" + SPEC_PATH)
    for name in ("inputs_head", "inputs_tree"):
        needle = ('"' + name + '": null').encode()
        require(old_spec.count(needle) == 1, "INPUTS_ALREADY_BOUND")
        old_spec = old_spec.replace(
            needle, ('"' + name + '": "' + SPEC[name] + '"').encode()
        )
    require(old_spec == SPEC_RAW, "UNRELATED_SPEC_CHANGE")
    leaves = [
        p
        for p in git(root, "ls-tree", "-rz", "--name-only", SPEC["base_head"]).split(
            b"\0"
        )
        if p
    ]
    require(len(leaves) == SPEC["original_product_leaves"], "BASE_LEAF_COUNT_MISMATCH")
    for path in ADDITIONS:
        require(
            git(root, "ls-tree", "HEAD", "--", path).startswith(b"100644 blob "),
            "PROPOSAL_MODE_CHANGED",
        )
    require(
        set(SPEC["passive_input_blobs"]) == GUARD_PATHS | (INPUT_PATHS - {SPEC_PATH}),
        "PASSIVE_INPUT_ROSTER_MISMATCH",
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
        set(SPEC["locks"]) == LOCKS
        and SPEC["vodozemac_native_artifact_approval"] is not None,
        "MISSING_FIXED_BASE_APPROVAL",
    )
    require(LOCKS <= SPEC["baseline_blobs"].keys(), "MISSING_LOCK_AUTHORITY")
    require(
        len(SPEC["source_files"]) == 6
        and {item["path"] for item in SPEC["source_files"]} == SOURCE_PATHS,
        "SOURCE_ROSTER_MISMATCH",
    )
    lock = tomllib.loads((root / "codex-rs/Cargo.lock").read_text())
    require(
        [p["version"] for p in lock["package"] if p["name"] == "vodozemac"]
        == ["0.11.2"],
        "VODOZEMAC_PRODUCT_NOT_INTEGRATED",
    )
    patch = HERE / "sdk-durable-source.patch"
    require(
        identity(patch.read_bytes())["sha256"] == SPEC["source_patch_sha256"],
        "SOURCE_PATCH_CHANGED",
    )
    for item in SPEC["source_files"]:
        path = root / item["path"]
        require(not path.is_symlink(), "SOURCE_SYMLINK")
        if item["before_blob"] is None:
            require(not path.exists(), "NEW_SOURCE_ALREADY_EXISTS")
        else:
            require(
                identity(path.read_bytes())["git_blob"] == item["before_blob"],
                "SOURCE_PREIMAGE_MISMATCH",
            )
    return {
        "head": head,
        "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
        "base_head": SPEC["base_head"],
        "base_tree": SPEC["base_tree"],
        "guards_head": SPEC["guards_head"],
        "guards_tree": SPEC["guards_tree"],
        "inputs_head": SPEC["inputs_head"],
        "inputs_tree": SPEC["inputs_tree"],
        "only_added_paths": sorted(ADDITIONS),
        "original_product_unchanged": True,
        "original_product_leaves": len(leaves),
    }


def private_directory():
    path = Path(os.environ["PRIVATE_EVIDENCE_DIR"])
    require(
        not path.is_symlink()
        and path.name.startswith("sdk-durable-proposal.")
        and path.parent.resolve(strict=True)
        == Path(os.environ["RUNNER_TEMP"]).resolve(strict=True),
        "INVALID_PRIVATE_DIRECTORY",
    )
    return path.resolve(strict=True)


def expected_commands(root):
    metadata = [
        "cargo",
        "+1.96.0",
        "metadata",
        "--all-features",
        "--format-version",
        "1",
    ]
    patch = str(HERE / "sdk-durable-source.patch")
    rows = [
        ("cargo-version", ["cargo", "+1.96.0", "--version"], ".", None),
        ("rustc-version", ["rustc", "+1.96.0", "--version"], ".", None),
        ("deny-version", ["cargo-deny", "--version"], ".", None),
        ("just-version", ["just", "--version"], ".", None),
        ("bazel-version", ["bazel", "--version"], ".", None),
        ("metadata-before", metadata + ["--locked"], "codex-rs", "before"),
        ("baseline-module-check", ["./scripts/check-module-bazel-lock.sh"], ".", None),
        ("source-patch-check", ["git", "apply", "--check", patch], ".", None),
        ("source-patch-apply", ["git", "apply", patch], ".", None),
        ("metadata-generate", metadata, "codex-rs", "after"),
        ("metadata-repeat", metadata + ["--locked"], "codex-rs", "repeat"),
        ("bazel-update", ["just", "bazel-lock-update"], ".", None),
        ("bazel-check", ["./scripts/check-module-bazel-lock.sh"], ".", None),
        ("bazel-repeat", ["just", "bazel-lock-update"], ".", None),
        ("bazel-check-repeat", ["./scripts/check-module-bazel-lock.sh"], ".", None),
        (
            "cargo-deny-original",
            [
                "cargo-deny",
                "--log-level",
                "warn",
                "--manifest-path",
                "./codex-rs/Cargo.toml",
                "--all-features",
                "check",
            ],
            ".",
            None,
        ),
    ]
    require([row[0] for row in rows] == list(STAGES[:-1]), "COMMAND_CONTRACT_MISMATCH")
    require(root == HERE.parents[1], "COMMAND_ROOT_MISMATCH")
    return [
        {
            "stage": stage,
            "argv": argv,
            "cwd": cwd,
            "stdout_private_only": phase is not None,
            "metadata_phase": phase,
        }
        for stage, argv, cwd, phase in rows
    ]


def generate(root, private):
    payload = private / "payload"
    initial = source_guard(root)
    require(
        initial == json.loads((payload / "source-before.json").read_bytes()),
        "SOURCE_CHANGED",
    )
    require(
        json.loads((payload / "readiness.json").read_bytes()) == initial,
        "MISSING_OR_CHANGED_SCANNER_READINESS",
    )
    sources = {item["path"]: item for item in SPEC["source_files"]}
    outputs = set(sources) | LOCKS
    commands = []
    result = {
        "proposal_validated": False,
        "command_exits": commands,
        "automatic_commit_or_ref_update": False,
        "full_metadata_uploaded": False,
    }

    def run(label, argv, cwd=root, metadata=None):
        require(label in STAGES, "UNKNOWN_COMMAND_STAGE")
        stdout = (
            private / ("metadata-" + metadata + ".json")
            if metadata
            else payload / "logs" / (label + ".log")
        )
        stderr = payload / "logs" / (label + ".stderr.log")
        stdout.parent.mkdir(parents=True, exist_ok=True)
        stderr.parent.mkdir(parents=True, exist_ok=True)
        with stdout.open("xb") as out, stderr.open("xb") as err:
            proc = subprocess.run(
                argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err
            )
        entry = {
            "stage": label,
            "argv": argv,
            "cwd": str(cwd.relative_to(root)) or ".",
            "exit_code": proc.returncode,
            "stdout_identity": identity(stdout.read_bytes()),
            "stderr_identity": identity(stderr.read_bytes()),
            "stdout_private_only": bool(metadata),
        }
        commands.append(entry)
        write_json(payload / "result.json", result)
        print(json.dumps({"stage": label, "exit_code": proc.returncode}), flush=True)
        require(proc.returncode == 0, "ORIGINAL_COMMAND_FAILED")
        return stdout.read_bytes()

    try:
        for path in outputs:
            if (root / path).exists():
                target = payload / "before" / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / path).read_bytes())
        for label, argv, prefix in [
            ("cargo-version", ["cargo", "+1.96.0", "--version"], [b"cargo", b"1.96.0"]),
            ("rustc-version", ["rustc", "+1.96.0", "--version"], [b"rustc", b"1.96.0"]),
            ("deny-version", ["cargo-deny", "--version"], [b"cargo-deny", b"0.19.0"]),
            ("just-version", ["just", "--version"], [b"just", b"1.51.0"]),
            ("bazel-version", ["bazel", "--version"], [b"bazel", b"9.0.0"]),
        ]:
            require(
                run(label, argv).strip().split()[:2] == prefix, "TOOL_VERSION_MISMATCH"
            )
        metadata_command = [
            "cargo",
            "+1.96.0",
            "metadata",
            "--all-features",
            "--format-version",
            "1",
        ]
        before = run(
            "metadata-before",
            metadata_command + ["--locked"],
            root / "codex-rs",
            metadata="before",
        )
        run("baseline-module-check", ["./scripts/check-module-bazel-lock.sh"])
        for path in outputs:
            original = payload / "before" / path
            if original.exists():
                require(
                    (root / path).read_bytes() == original.read_bytes(),
                    "BASELINE_CHANGED_BEFORE_PATCH",
                )
        run(
            "source-patch-check",
            ["git", "apply", "--check", str(HERE / "sdk-durable-source.patch")],
        )
        run(
            "source-patch-apply",
            ["git", "apply", str(HERE / "sdk-durable-source.patch")],
        )
        for path, item in sources.items():
            require(
                identity((root / path).read_bytes())["git_blob"] == item["after_blob"],
                "SOURCE_POSTIMAGE_MISMATCH",
            )
        after = run(
            "metadata-generate", metadata_command, root / "codex-rs", metadata="after"
        )
        cargo_lock = (root / "codex-rs/Cargo.lock").read_bytes()
        cargo_proof = cargo_guard(
            (payload / "before/codex-rs/Cargo.lock").read_bytes(), cargo_lock
        )
        metadata_proof = metadata_guard(json.loads(before), json.loads(after))
        metadata_proof["raw_identities"] = {
            "before": identity(before),
            "after": identity(after),
        }
        write_json(payload / "cargo-proof.json", cargo_proof)
        write_json(payload / "metadata-proof.json", metadata_proof)
        for phase, raw in (("before", before), ("after", after)):
            write_json(
                payload / ("metadata-" + phase + "-projection.json"),
                metadata_projection(raw),
            )
        repeated = run(
            "metadata-repeat",
            metadata_command + ["--locked"],
            root / "codex-rs",
            metadata="repeat",
        )
        require(
            canonical_metadata(json.loads(repeated))
            == canonical_metadata(json.loads(after)),
            "METADATA_NOT_REPEATABLE",
        )
        require(
            (root / "codex-rs/Cargo.lock").read_bytes() == cargo_lock,
            "CARGO_LOCK_NOT_REPEATABLE",
        )
        run("bazel-update", ["just", "bazel-lock-update"])
        run("bazel-check", ["./scripts/check-module-bazel-lock.sh"])
        module_lock = (root / "MODULE.bazel.lock").read_bytes()
        write_json(
            payload / "module-proof.json",
            module_guard(
                (payload / "before/MODULE.bazel.lock").read_bytes(), module_lock
            ),
        )
        run("bazel-repeat", ["just", "bazel-lock-update"])
        run("bazel-check-repeat", ["./scripts/check-module-bazel-lock.sh"])
        require(
            (root / "MODULE.bazel.lock").read_bytes() == module_lock,
            "MODULE_LOCK_NOT_REPEATABLE",
        )
        run(
            "cargo-deny-original",
            [
                "cargo-deny",
                "--log-level",
                "warn",
                "--manifest-path",
                "./codex-rs/Cargo.toml",
                "--all-features",
                "check",
            ],
        )
        require(
            (root / "codex-rs/Cargo.lock").read_bytes() == cargo_lock
            and (root / "MODULE.bazel.lock").read_bytes() == module_lock,
            "LOCKS_CHANGED_AFTER_CHECKS",
        )
        for path, item in sources.items():
            require(
                not (root / path).is_symlink()
                and identity((root / path).read_bytes())["git_blob"]
                == item["after_blob"],
                "SOURCE_CHANGED_AFTER_CHECKS",
            )
            require(
                (root / path).stat().st_mode & 0o777 == 0o644, "SOURCE_MODE_CHANGED"
            )
        require(
            git(root, "rev-parse", "HEAD").decode().strip() == initial["head"],
            "HEAD_CHANGED",
        )
        require_index_flags(root)
        changed = {
            p.decode()
            for p in git(root, "diff", "--name-only", "-z", "HEAD").split(b"\0")
            if p
        }
        untracked = {
            p.decode()
            for p in git(
                root, "ls-files", "--others", "--exclude-standard", "-z"
            ).split(b"\0")
            if p
        }
        require(changed <= outputs, "UNRELATED_TRACKED_CHANGE")
        require(
            untracked
            == {path for path, item in sources.items() if item["before_blob"] is None},
            "UNEXPECTED_UNTRACKED_FILE",
        )
        index = {"GIT_INDEX_FILE": str(private / "proposal.index")}
        git(root, "read-tree", "HEAD", env=index)
        git(root, "add", "-f", "--", *sorted(outputs), env=index)
        staged_paths = {
            p.decode()
            for p in git(
                root, "diff", "--cached", "--name-only", "-z", "HEAD", env=index
            ).split(b"\0")
            if p
        }
        require(staged_paths == changed | untracked, "PATCH_PATH_SET_MISMATCH")
        for path in outputs:
            require(
                git(root, "show", ":" + path, env=index) == (root / path).read_bytes(),
                "INDEX_OUTPUT_MISMATCH",
            )
        patch = git(root, "diff", "--cached", "--binary", "HEAD", env=index)
        proposed = git(root, "write-tree", env=index).decode().strip()
        patch_path = private / "proposal.patch"
        patch_path.write_bytes(patch)
        replay = {"GIT_INDEX_FILE": str(private / "replay.index")}
        git(root, "read-tree", "HEAD", env=replay)
        git(root, "apply", "--cached", str(patch_path), env=replay)
        require(
            git(root, "write-tree", env=replay).decode().strip() == proposed,
            "PATCH_FORWARD_MISMATCH",
        )
        git(root, "apply", "--cached", "--reverse", str(patch_path), env=replay)
        require(
            git(root, "write-tree", env=replay).decode().strip() == initial["tree"],
            "PATCH_REVERSE_MISMATCH",
        )
        (payload / "proposal.patch").write_bytes(patch)
        result.update(
            proposal_validated=True,
            proposed_tree=proposed,
            repeated_locks_identical=True,
            original_cargo_deny_passed=True,
            patch_replayed_both_directions=True,
            validated_payload_identities={
                "proposal.patch": identity(patch),
                **{
                    "after/" + path: identity((root / path).read_bytes())
                    for path in outputs
                },
            },
        )
    except Exception:
        result["error_code"] = "GENERATION_OR_GUARD_FAILED"
        failure = payload / "logs/proposal-failure.log"
        failure.parent.mkdir(parents=True, exist_ok=True)
        failure.write_text(traceback.format_exc())
        raise
    finally:
        try:
            for path in outputs:
                if (root / path).is_file():
                    target = payload / "after" / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((root / path).read_bytes())
            write_json(
                payload / "source-after.json",
                {
                    "head": git(root, "rev-parse", "HEAD").decode().strip(),
                    "tracked_changes": [
                        p.decode()
                        for p in git(root, "diff", "--name-only", "-z", "HEAD").split(
                            b"\0"
                        )
                        if p
                    ],
                },
            )
        except Exception:
            result["proposal_validated"] = False
            result["output_capture_failed"] = True
        if not result["proposal_validated"] and (payload / "proposal.patch").exists():
            (payload / "proposal.patch").replace(private / "unvalidated-proposal.patch")
        write_json(payload / "result.json", result)
    require(result["proposal_validated"], "FINAL_CAPTURE_FAILED")


def main():
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    phase = sys.argv[1]
    if phase == "preflight":
        source = source_guard(root)
        private = Path(
            tempfile.mkdtemp(
                prefix="sdk-durable-proposal.", dir=os.environ["RUNNER_TEMP"]
            )
        )
        write_json(private / "payload/source-before.json", source)
        write_json(private / "payload/proposal-spec.json", SPEC)
        write_json(
            private / "payload/result.json",
            {"proposal_validated": False, "error_code": "NOT_STARTED"},
        )
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("private_dir=" + str(private) + "\n")
        print(json.dumps(source))
    elif phase == "ready":
        scanner(SPEC["fixed_bazel_source_uris"])
        private = private_directory()
        source = source_guard(root)
        require(
            source == json.loads((private / "payload/source-before.json").read_bytes()),
            "SOURCE_CHANGED_BEFORE_READINESS",
        )
        write_json(private / "payload/readiness.json", source)
        print(json.dumps({"stage": "scanner-ready", "success": True}))
    elif phase == "generate":
        generate(root, private_directory())
    elif phase == "collect":
        collect(private_directory(), SPEC, STAGES, expected_commands(root))
    else:
        raise ValueError("UNKNOWN_PHASE")


if __name__ == "__main__":
    main()
