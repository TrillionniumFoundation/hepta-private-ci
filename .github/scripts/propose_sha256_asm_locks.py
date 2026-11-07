#!/usr/bin/env python3
"""Generate a three-file proposal under the original commands and strict guards."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

from sha256_asm_lock_guards import (
    cargo_guard,
    canonical_metadata,
    metadata_guard,
    module_guard,
)
from sha256_asm_platform_guards import TRIPLES, aquery_command, platform_guard
from sha256_asm_proposal_evidence import (
    collect,
    identity,
    metadata_projection,
    require,
    scanner,
)
from sha256_asm_source_guard import (
    ADDITIONS,
    HERE,
    LOCKS,
    SPEC,
    git,
    git_environment,
    private_directory,
    require_index_flags,
    source_guard,
    write_json,
)
from sha256_asm_worktree_guard import verify_worktree


STAGES = (
    "cargo-version",
    "rustc-version",
    "deny-version",
    "just-version",
    "bazel-version",
    "metadata-before",
    "baseline-module-check",
    *("aquery-before-" + triple for triple in TRIPLES),
    "source-patch-check",
    "source-patch-apply",
    "metadata-generate",
    "metadata-repeat",
    "bazel-update",
    "bazel-check",
    "bazel-repeat",
    "bazel-check-repeat",
    *("aquery-after-" + triple for triple in TRIPLES),
    "cargo-deny-original",
    "proposal-failure",
)


def validated_output_identity(raw, expected):
    digest = identity(raw)
    require(
        {key: digest[key] for key in ("bytes", "git_blob")}
        == {key: expected[key] for key in ("bytes", "git_blob")},
        "STAGED_OR_PROPOSED_OUTPUT_NOT_VALIDATED",
    )
    return digest


def expected_commands(root):
    metadata = [
        "cargo",
        "+1.96.0",
        "metadata",
        "--all-features",
        "--format-version",
        "1",
    ]
    patch = str(HERE / "sha256-asm-source.patch")
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
    rows[7:7] = [
        ("aquery-before-" + triple, aquery_command(triple), ".", None)
        for triple in TRIPLES
    ]
    rows[-1:-1] = [
        ("aquery-after-" + triple, aquery_command(triple), ".", None)
        for triple in TRIPLES
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
                argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=git_environment() if argv[0] == "git" else None,
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
        for triple in TRIPLES:
            run("aquery-before-" + triple, aquery_command(triple))
        for path in outputs:
            original = payload / "before" / path
            if original.exists():
                require(
                    (root / path).read_bytes() == original.read_bytes(),
                    "BASELINE_CHANGED_BEFORE_PATCH",
                )
        run(
            "source-patch-check",
            ["git", "apply", "--check", str(HERE / "sha256-asm-source.patch")],
        )
        run(
            "source-patch-apply",
            ["git", "apply", str(HERE / "sha256-asm-source.patch")],
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
        for triple in TRIPLES:
            run("aquery-after-" + triple, aquery_command(triple))
        platform_files = {
            "logs/aquery-" + phase + "-" + triple + ".log": (
                payload / ("logs/aquery-" + phase + "-" + triple + ".log")
            ).read_bytes()
            for phase in ("before", "after")
            for triple in TRIPLES
        }
        write_json(payload / "platform-proof.json", platform_guard(platform_files))
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
        validated_after = {
            "codex-rs/Cargo.lock": {
                "mode": "100644",
                **{k: v for k, v in identity(cargo_lock).items() if k != "sha256"},
            },
            "MODULE.bazel.lock": {
                "mode": "100644",
                **{k: v for k, v in identity(module_lock).items() if k != "sha256"},
            },
            **{
                path: {
                    "mode": item["mode"],
                    "git_blob": item["after_blob"],
                    "bytes": item["after_bytes"],
                }
                for path, item in sources.items()
            },
        }
        result["complete_final_worktree_verification"] = verify_worktree(
            root, git, SPEC["base_tree"], initial["tree"], ADDITIONS, validated_after
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
            staged = git(root, "show", ":" + path, env=index)
            require(staged == (root / path).read_bytes(), "INDEX_OUTPUT_MISMATCH")
            validated_output_identity(staged, validated_after[path])
        patch = git(root, "diff", "--cached", "--binary", "HEAD", env=index)
        proposed = git(root, "write-tree", env=index).decode().strip()
        proposed_identities = {}
        for path in outputs:
            entry = git(root, "ls-tree", proposed, "--", path)
            require(
                entry.startswith(
                    b"100644 blob " + validated_after[path]["git_blob"].encode() + b"\t"
                ),
                "PROPOSED_TREE_MODE_OR_BLOB_MISMATCH",
            )
            proposed_identities["after/" + path] = validated_output_identity(
                git(root, "show", proposed + ":" + path), validated_after[path]
            )
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
            all_four_configured_platforms_verified=True,
            original_cargo_deny_passed=True,
            patch_replayed_both_directions=True,
            validated_payload_identities={
                "proposal.patch": identity(patch),
                **proposed_identities,
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
                prefix="sha256-asm-proposal.", dir=os.environ["RUNNER_TEMP"]
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
