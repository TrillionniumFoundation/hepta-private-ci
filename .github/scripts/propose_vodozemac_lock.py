#!/usr/bin/env python3
"""Build a review artifact with actual Cargo/Bazel locks; never commit or update a ref."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import urllib.request

from vodozemac_proposal_evidence import ProposalError, collect, identity, require
from vodozemac_lock_guards import (
    graph_guard,
    module_guard,
    verify_archives,
    feature_guard,
)

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "vodozemac-lock-spec.json").read_bytes())
ADDITIONS = {
    ".github/workflows/hepta-vodozemac-lock-proposal.yml",
    ".github/scripts/propose_vodozemac_lock.py",
    ".github/scripts/vodozemac_proposal_evidence.py",
    ".github/scripts/vodozemac-lock-spec.json",
    ".github/scripts/vodozemac_lock_guards.py",
}
CHANGED = {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}
CAPTURED = CHANGED | {"codex-rs/Cargo.toml"}
PROPOSAL_PARENT = {
    "head": "90b1c924f1ad7993a0b25f2d54749221f1045276",
    "tree": "73fd7bbfdeeded8700f6d2ca6ebc39dea5574df9",
    "ref": "research/ndu-vodozemac-repeatable-resolution-20261106",
    "inherited_files": {
        ".github/scripts/vodozemac_proposal_evidence.py": (
            "100644",
            "df92074358560c9d439323054cab12c2d0c9c7f6",
        ),
        ".github/scripts/vodozemac-lock-spec.json": (
            "100644",
            "74376db93a746fbdd359e217e2e38d8d50a8fde1",
        ),
        ".github/scripts/vodozemac_lock_guards.py": (
            "100644",
            "976dde7034708c37cb972e494640c9ea53afda33",
        ),
    },
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def git(root, *args, env=None):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def tree_hash(leaves):
    root = {}
    for path, (mode, sha) in leaves.items():
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (mode, sha)

    def tree(node):
        entries = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, sha = ("40000", tree(value)) if directory else value
            entries.append(
                (
                    (name + ("/" if directory else "")).encode(),
                    mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha),
                )
            )
        raw = b"".join(value for _, value in sorted(entries))
        return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

    return tree(root)


def source_guard(root):
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())[
        "pull_request"
    ]
    head = git(root, "rev-parse", "HEAD").decode().strip()
    require(os.environ.get("GITHUB_EVENT_NAME") == "pull_request", "WRONG_EVENT")
    require(
        event["head"]["repo"]["full_name"]
        == event["base"]["repo"]["full_name"]
        == "TrillionniumFoundation/hepta-private-ci",
        "WRONG_REPOSITORY",
    )
    require(
        event["base"]["sha"] == PROPOSAL_PARENT["head"]
        and event["base"]["ref"] == PROPOSAL_PARENT["ref"],
        "BASE_MOVED",
    )
    require(
        head == event["head"]["sha"] == os.environ["CANDIDATE_SHA"], "HEAD_MISMATCH"
    )
    require(
        git(root, "show", "-s", "--format=%P", "HEAD").decode().strip()
        == PROPOSAL_PARENT["head"],
        "PARENT_MISMATCH",
    )
    require(
        not git(root, "status", "--porcelain=v1", "--untracked-files=all"),
        "DIRTY_INITIAL_SOURCE",
    )
    leaves = {}
    for row in git(root, "ls-tree", "-rz", "--full-tree", "HEAD").split(b"\0"):
        if row:
            metadata, path = row.split(b"\t", 1)
            mode, kind, sha = metadata.decode().split()
            require(kind == "blob", "UNEXPECTED_GITLINK")
            leaves[path.decode()] = (mode, sha)
    require(ADDITIONS <= leaves.keys(), "MISSING_PROPOSAL_FILES")
    require(
        git(root, "rev-parse", "HEAD^1^{tree}").decode().strip()
        == PROPOSAL_PARENT["tree"],
        "REVIEW_STAGE_PARENT_TREE_MISMATCH",
    )
    require(
        all(
            leaves.get(path) == expected
            for path, expected in PROPOSAL_PARENT["inherited_files"].items()
        ),
        "REVIEW_STAGE_INPUT_CHANGED",
    )
    final_additions = ADDITIONS - PROPOSAL_PARENT["inherited_files"].keys()
    require(
        {
            path.decode()
            for path in git(root, "diff", "--name-only", "-z", "HEAD^1", "HEAD").split(
                b"\0"
            )
            if path
        }
        == final_additions,
        "FINAL_REVIEW_STAGE_PATH_DRIFT",
    )
    original = {p: v for p, v in leaves.items() if p not in ADDITIONS}
    require(
        len(original) == SPEC["original_product_leaves"]
        and tree_hash(original) == SPEC["base_tree"],
        "ORIGINAL_PRODUCT_TREE_CHANGED",
    )
    require(
        all(original[p][1] == sha for p, sha in SPEC["baseline_blobs"].items()),
        "PIN_MISMATCH",
    )
    require(all(leaves[p][0] == "100644" for p in ADDITIONS), "PROPOSAL_MODE_MISMATCH")
    return {
        "head": head,
        "tree": tree_hash(leaves),
        "base": SPEC["base_head"],
        "base_tree": SPEC["base_tree"],
        "proposal_parent": PROPOSAL_PARENT["head"],
        "proposal_parent_tree": PROPOSAL_PARENT["tree"],
        "inherited_review_stage_blobs_unchanged": {
            path: list(expected)
            for path, expected in PROPOSAL_PARENT["inherited_files"].items()
        },
        "original_leaves_unchanged": len(original),
        "added_paths": sorted(ADDITIONS),
        "clean": True,
    }


def private_dir():
    path = Path(os.environ["PRIVATE_EVIDENCE_DIR"])
    require(
        not path.is_symlink()
        and path.name.startswith("vodozemac-proposal.")
        and path.parent.resolve(strict=True)
        == Path(os.environ["RUNNER_TEMP"]).resolve(strict=True),
        "INVALID_PRIVATE_DIRECTORY",
    )
    return path.resolve(strict=True)


class CommandFailed(ProposalError):
    def __init__(self, code):
        self.code = code
        super().__init__("ORIGINAL_COMMAND_FAILED")


def generate(root, private):
    payload = private / "payload"
    commands = []
    result = {
        "schema": "vodozemac-lock-proposal-result-v1",
        "proposal_validated": False,
        "automatic_commit_or_ref_update": False,
        "command_exits": commands,
    }
    before_source = source_guard(root)
    require(
        before_source == json.loads((payload / "source-before.json").read_bytes()),
        "SOURCE_CHANGED",
    )

    def run(label, argv, cwd=root, must_succeed=True, env=None, separate_stderr=False):
        logfile = payload / "logs" / (label + ".log")
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("xb") as stream:
            if separate_stderr:
                with (payload / "logs" / (label + ".stderr.log")).open("xb") as stderr:
                    proc = subprocess.run(
                        argv,
                        cwd=cwd,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=stream,
                        stderr=stderr,
                        check=False,
                    )
            else:
                proc = subprocess.run(
                    argv,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
        commands.append(
            {
                "stage": label,
                "argv": argv,
                "cwd": str(cwd.relative_to(root)) or ".",
                "exit_code": proc.returncode,
            }
        )
        write_json(payload / "result.json", result)
        print(json.dumps({"stage": label, "exit_code": proc.returncode}), flush=True)
        if must_succeed and proc.returncode:
            raise CommandFailed(proc.returncode if 0 < proc.returncode < 256 else 1)
        return logfile.read_bytes()

    def resolve_existing_versions(stage):
        # Updating vodozemac unlocks its dependency closure. Resolve the two
        # already present alternatives again, then require the original graph.
        for package, version in (("itertools", "0.14.0"), ("getrandom", "0.3.4")):
            run(
                f"cargo-existing-{package}-{stage}",
                [
                    "cargo",
                    "+1.96.0",
                    "update",
                    "-p",
                    f"{package}@{version}",
                    "--precise",
                    version,
                ],
                root / "codex-rs",
            )

    try:
        for name, argv, expected in [
            ("cargo-version", ["cargo", "+1.96.0", "--version"], [b"cargo", b"1.96.0"]),
            ("rustc-version", ["rustc", "+1.96.0", "--version"], [b"rustc", b"1.96.0"]),
            (
                "deny-version",
                ["cargo", "+1.96.0", "deny", "--version"],
                [b"cargo-deny", b"0.19.0"],
            ),
            ("just-version", ["just", "--version"], [b"just", b"1.51.0"]),
            ("bazel-version", ["bazel", "--version"], [b"bazel", b"9.0.0"]),
        ]:
            require(
                run(name, argv, separate_stderr=True).strip().split()[:2] == expected,
                "TOOLCHAIN_VERSION_MISMATCH",
            )
        metadata_argv = [
            "cargo",
            "+1.96.0",
            "metadata",
            "--locked",
            "--no-deps",
            "--format-version",
            "1",
        ]
        before_members = json.loads(
            run(
                "workspace-before",
                metadata_argv,
                root / "codex-rs",
                separate_stderr=True,
            )
        )["workspace_members"]
        old_lock = (root / "codex-rs/Cargo.lock").read_bytes()
        for name in CAPTURED:
            target = payload / "before" / Path(name).name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / name).read_bytes())
        run(
            "baseline-bazel-lock-check",
            ["./scripts/check-module-bazel-lock.sh"],
            must_succeed=False,
        )
        receipts = []
        archives = {}
        for crate in SPEC["crates"]:
            with urllib.request.urlopen(crate["url"], timeout=60) as response:
                require(
                    response.status == 200 and response.geturl() == crate["url"],
                    "UNEXPECTED_ARCHIVE_RESPONSE",
                )
                raw = response.read(crate["archive_bytes"] + 1)
                require(
                    len(raw) == crate["archive_bytes"]
                    and identity(raw)["sha256"] == crate["checksum"],
                    "ARCHIVE_CHECKSUM_MISMATCH",
                )
            archives[crate["version"]] = raw
            target = (
                payload
                / "archives"
                / (crate["name"] + "-" + crate["version"] + ".crate")
            )
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(raw)
            receipts.append(
                {"url": crate["url"], "status": 200, "actual": identity(raw)}
            )
            write_json(payload / "archive-receipts.json", receipts)
        write_json(payload / "upstream-proof.json", verify_archives(archives, SPEC))
        manifest = root / "codex-rs/Cargo.toml"
        new_manifest = manifest.read_bytes()
        cargo = [
            "cargo",
            "+1.96.0",
            "update",
            "-p",
            "vodozemac@0.11.1",
            "--precise",
            "0.11.2",
        ]
        run("cargo-lock-update", cargo, root / "codex-rs")
        resolve_existing_versions("update")
        new_lock = (root / "codex-rs/Cargo.lock").read_bytes()
        write_json(
            payload / "lock-graph-proof.json", graph_guard(old_lock, new_lock, SPEC)
        )
        repeat = [
            "cargo",
            "+1.96.0",
            "update",
            "-p",
            "vodozemac@0.11.2",
            "--precise",
            "0.11.2",
        ]
        run("cargo-lock-repeat", repeat, root / "codex-rs")
        resolve_existing_versions("repeat")
        require(
            (root / "codex-rs/Cargo.lock").read_bytes() == new_lock,
            "CARGO_LOCK_NOT_REPEATABLE",
        )
        after_members = json.loads(
            run(
                "workspace-after",
                metadata_argv,
                root / "codex-rs",
                separate_stderr=True,
            )
        )["workspace_members"]
        require(before_members == after_members, "WORKSPACE_MEMBERS_CHANGED")
        feature_command = [
            "cargo",
            "+1.96.0",
            "tree",
            "--color",
            "never",
            "--locked",
            "--package",
            "vodozemac@0.11.2",
            "--target",
            "all",
            "--edges",
            "normal,build",
            "--prefix",
            "none",
            "--format",
            "{p}|{f}",
        ]
        feature_output = run(
            "features-after", feature_command, root / "codex-rs", separate_stderr=True
        )
        write_json(payload / "feature-proof.json", feature_guard(feature_output, SPEC))
        run("bazel-lock-update", ["just", "bazel-lock-update"])
        run("bazel-lock-check", ["./scripts/check-module-bazel-lock.sh"])
        module_lock = (root / "MODULE.bazel.lock").read_bytes()
        module_proof = module_guard(
            (payload / "before/MODULE.bazel.lock").read_bytes(), module_lock, SPEC
        )
        write_json(payload / "module-lock-proof.json", module_proof)
        run("bazel-lock-repeat", ["just", "bazel-lock-update"])
        run("bazel-lock-check-repeat", ["./scripts/check-module-bazel-lock.sh"])
        require(
            (root / "MODULE.bazel.lock").read_bytes() == module_lock,
            "BAZEL_LOCK_NOT_REPEATABLE",
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
            (root / "codex-rs/Cargo.lock").read_bytes() == new_lock,
            "CARGO_LOCK_CHANGED_AFTER_CHECKS",
        )
        require(
            (root / "MODULE.bazel.lock").read_bytes() == module_lock,
            "MODULE_LOCK_CHANGED_AFTER_CHECKS",
        )
        require(
            manifest.read_bytes() == new_manifest,
            "WORKSPACE_MANIFEST_CHANGED_AFTER_PATCH",
        )
        require(
            git(root, "rev-parse", "HEAD").decode().strip() == before_source["head"],
            "HEAD_CHANGED",
        )
        changed = {
            p.decode()
            for p in git(root, "diff", "--name-only", "-z", "HEAD").split(b"\0")
            if p
        }
        require(changed == CHANGED, "UNEXPECTED_TRACKED_CHANGE")
        untracked = {
            p.decode()
            for p in git(
                root, "ls-files", "--others", "--exclude-standard", "-z"
            ).split(b"\0")
            if p
        }
        require(not untracked, "UNEXPECTED_UNTRACKED_FILE")
        require(
            not git(root, "diff", "--summary", "HEAD"), "TRACKED_MODE_OR_TYPE_CHANGED"
        )
        env = {**os.environ, "GIT_INDEX_FILE": str(private / "proposal.index")}
        git(root, "read-tree", "HEAD", env=env)
        git(root, "add", "-f", "--", *sorted(CHANGED), env=env)
        patch = git(root, "diff", "--cached", "--binary", "HEAD", env=env)
        require(
            {
                p.decode()
                for p in git(
                    root, "diff", "--cached", "--name-only", "-z", "HEAD", env=env
                ).split(b"\0")
                if p
            }
            == changed,
            "PATCH_PATH_SET_MISMATCH",
        )
        for name, raw in [
            ("codex-rs/Cargo.toml", new_manifest),
            ("codex-rs/Cargo.lock", new_lock),
            ("MODULE.bazel.lock", module_lock),
        ]:
            require(
                git(root, "show", ":" + name, env=env) == raw,
                "INDEX_LOCK_CAPTURE_MISMATCH",
            )
        proposal_tree = git(root, "write-tree", env=env).decode().strip()
        replay_env = {**os.environ, "GIT_INDEX_FILE": str(private / "replay.index")}
        git(root, "read-tree", "HEAD", env=replay_env)
        patchpath = private / "checked.patch"
        patchpath.write_bytes(patch)
        git(root, "apply", "--cached", str(patchpath), env=replay_env)
        require(
            git(root, "write-tree", env=replay_env).decode().strip() == proposal_tree,
            "PATCH_FORWARD_MISMATCH",
        )
        git(root, "apply", "--cached", "--reverse", str(patchpath), env=replay_env)
        require(
            git(root, "write-tree", env=replay_env).decode().strip()
            == before_source["tree"],
            "PATCH_REVERSE_MISMATCH",
        )
        (payload / "proposal.patch").write_bytes(patch)
        result.update(
            proposal_validated=True,
            proposal_tree_including_only_the_original_proposal_tools=proposal_tree,
            two_actual_locks_repeat_byte_equal=True,
            original_cargo_deny_passed=True,
            forward_and_reverse_patch_replayed=True,
            workspace_members_not_expanded=True,
            exact_six_zeroize_features_verified_by_native_cargo_tree=True,
            validated_payload_identities={
                "proposal.patch": identity(patch),
                "after/Cargo.toml": identity(new_manifest),
                "after/Cargo.lock": identity(new_lock),
                "after/MODULE.bazel.lock": identity(module_lock),
            },
        )
    except CommandFailed as error:
        result["error_code"] = str(error)
        result["original_exit_code"] = error.code
        raise
    except Exception:
        result["error_code"] = "PROPOSAL_GENERATION_OR_GUARD_FAILED"
        failure = payload / "logs/proposal-failure.log"
        failure.parent.mkdir(parents=True, exist_ok=True)
        failure.write_text(traceback.format_exc())
        raise
    finally:
        for name in CAPTURED:
            target = payload / "after" / Path(name).name
            try:
                if (root / name).is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((root / name).read_bytes())
            except Exception:
                result["output_capture_failed"] = True
                result["proposal_validated"] = False
        try:
            write_json(
                payload / "source-after.json",
                {
                    "head": git(root, "rev-parse", "HEAD").decode().strip(),
                    "committed_tree": git(root, "rev-parse", "HEAD^{tree}")
                    .decode()
                    .strip(),
                    "tracked_changes": [
                        p.decode()
                        for p in git(root, "diff", "--name-only", "-z", "HEAD").split(
                            b"\0"
                        )
                        if p
                    ],
                    "proposal_generation_attempted": True,
                    "proposal_validated": result["proposal_validated"],
                },
            )
        except Exception:
            result["source_after_capture_failed"] = True
            result["proposal_validated"] = False
        if not result["proposal_validated"] and (payload / "proposal.patch").exists():
            # Preserve raw logs even when final source custody prevents publishing a proposal.
            try:
                (payload / "proposal.patch").replace(
                    private / "unvalidated-proposal.patch"
                )
                result["unvalidated_patch_withheld_from_upload"] = True
            except Exception:
                result["unvalidated_patch_withhold_failed"] = True
        try:
            write_json(payload / "result.json", result)
        except Exception:
            result["proposal_validated"] = False
            print(json.dumps({"error_code": "FINAL_RECEIPT_WRITE_FAILED"}), flush=True)
    require(result["proposal_validated"], "FINAL_CAPTURE_FAILED")


def main():
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    phase = sys.argv[1]
    if phase == "preflight":
        source = source_guard(root)
        private = Path(
            tempfile.mkdtemp(
                prefix="vodozemac-proposal.", dir=os.environ["RUNNER_TEMP"]
            )
        )
        write_json(private / "payload/source-before.json", source)
        write_json(private / "payload/upgrade-spec.json", SPEC)
        write_json(
            private / "payload/result.json",
            {"proposal_validated": False, "error_code": "GENERATION_NOT_STARTED"},
        )
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("private_dir=" + str(private) + "\n")
        print(json.dumps(source))
    elif phase == "generate":
        generate(root, private_dir())
    elif phase == "collect":
        original = git(root, "show", SPEC["base_head"] + ":codex-rs/Cargo.toml")
        collect(private_dir(), SPEC, original)
    else:
        raise ProposalError("INVALID_PHASE")


if __name__ == "__main__":
    try:
        main()
    except CommandFailed as error:
        print(
            json.dumps(
                {
                    "proposal_validated": False,
                    "error_code": "ORIGINAL_COMMAND_FAILED",
                    "exit_code": error.code,
                }
            )
        )
        raise SystemExit(error.code) from None
    except ProposalError as error:
        print(json.dumps({"proposal_validated": False, "error_code": str(error)}))
        raise SystemExit(1) from None
    except Exception:
        print(
            json.dumps({"proposal_validated": False, "error_code": "PROPOSAL_FAILURE"})
        )
        raise SystemExit(1) from None
