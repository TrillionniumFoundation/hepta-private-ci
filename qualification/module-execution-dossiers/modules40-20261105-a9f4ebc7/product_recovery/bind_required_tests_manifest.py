#!/usr/bin/env python3
"""Bind the unchanged required-test list to a frozen, committed source tree.

This reads Git and source bytes and writes an evidence manifest. It never builds,
runs, formats, fixes or changes tests, budgets, profiles or source files.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def identities(manifest):
    keys = ["package", "binary", "binary_kind", "target_aliases", "test", "source_path", "required"]
    return [{key: row.get(key) for key in keys} for row in manifest["required_tests"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--review-manifest", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--candidate-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for value in [args.candidate_commit, args.candidate_tree]:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            parser.error("candidate commit and tree must be full 40-character SHAs")
    repo = args.repo.resolve()
    # Match the repository's strict verifier: read this checkout without ambient
    # Git redirection, replacements, lazy network fetches or fsmonitor hooks.
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    git_env.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
    )

    def git(*argv, check=True):
        result = subprocess.run(
            ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", "-C", str(repo), *argv],
            env=git_env, capture_output=True,
        )
        if check and result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace").strip())
        return result

    def ensure_frozen():
        hidden = [
            record[2:]
            for record in git("ls-files", "-v", "-z").stdout.decode().split("\0")
            if record and (record[0] == "S" or record[0].islower())
        ]
        if hidden:
            raise RuntimeError(
                "candidate index hides tracked paths (assume-unchanged/skip-worktree): "
                + ", ".join(repr(path) for path in hidden[:5])
                + "; verify a full checkout without hidden index entries"
            )
        if git("rev-parse", "HEAD").stdout.decode().strip() != args.candidate_commit:
            raise RuntimeError("HEAD is not the supplied frozen candidate")
        if git("rev-parse", args.candidate_commit + "^{tree}").stdout.decode().strip() != args.candidate_tree:
            raise RuntimeError("supplied tree does not belong to the candidate commit")
        diff_options = ["--no-ext-diff", "--no-textconv", "--ignore-submodules=none"]
        if git("diff", *diff_options, "--quiet", args.candidate_commit, "--", check=False).returncode:
            raise RuntimeError("tracked working-tree content differs from the candidate")
        if git("diff", *diff_options, "--cached", "--quiet", args.candidate_commit, "--", check=False).returncode:
            raise RuntimeError("tracked index content differs from the candidate")

    ensure_frozen()
    review_bytes = args.review_manifest.read_bytes()
    review = json.loads(review_bytes)
    if review.get("schema_version") != 1:
        raise RuntimeError("input must be the immutable reviewed schema-v1 manifest")
    before = identities(review)
    result = copy.deepcopy(review)
    result["schema_version"] = 2
    result["manifest_stage"] = "candidate_source_bound_not_tested"
    result["review_manifest"] = {
        "path": str(args.review_manifest.resolve()), "sha256": sha256(review_bytes),
    }
    result["candidate"] = {"commit": args.candidate_commit, "tree": args.candidate_tree}
    result["requirements_identity_sha256"] = sha256(
        json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
    )

    objects = {}

    def bind(path):
        if path in objects:
            return objects[path]
        logical = PurePosixPath(path)
        if logical.is_absolute() or ".." in logical.parts:
            raise RuntimeError(f"source path is not repository-relative: {path}")
        spec = args.candidate_commit + ":" + path
        content = git("show", spec).stdout
        worktree = (repo / path).read_bytes()
        if worktree != content:
            raise RuntimeError(f"checked-out source does not match candidate blob: {path}")
        objects[path] = {
            "path": path, "git_blob": git("rev-parse", spec).stdout.decode().strip(),
            "sha256": sha256(content), "bytes": len(content),
        }
        return objects[path]

    for row in result["required_tests"]:
        source = bind(row["source_path"])
        row["review_source_snapshot_sha256"] = row["source_snapshot_sha256"]
        row["source_snapshot_sha256"] = source["sha256"]
        row["source_git_blob"] = source["git_blob"]

    context = [
        "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/.config/nextest.toml",
        "codex-rs/hepta-agent-protocol/Cargo.toml", "codex-rs/hepta-agentd/Cargo.toml",
        "codex-rs/hepta-infer-worker-host/Cargo.toml", "codex-rs/hepta-runtime/Cargo.toml",
        "scripts/run-nextest.py", "scripts/just-shell.py",
    ]
    for optional in ["justfile", "codex-rs/justfile", "rust-toolchain.toml", "codex-rs/rust-toolchain.toml"]:
        if git("cat-file", "-e", args.candidate_commit + ":" + optional, check=False).returncode == 0:
            context.append(optional)
    result["runner_source_context"] = [bind(path) for path in context]
    result["reviewed_source_files"] = [objects[path] for path in sorted({row["source_path"] for row in result["required_tests"]})]
    result["untracked_paths_observed"] = git("ls-files", "--others", "--exclude-standard", "-z").stdout.decode().rstrip("\0").split("\0")
    if result["untracked_paths_observed"] == [""]:
        result["untracked_paths_observed"] = []
    result["source_binding"] = {
        "tracked_worktree_and_index_match_candidate": True,
        "hidden_index_entries_rejected": True,
        "ambient_git_variables_and_global_config_isolated": True,
        "all_selected_source_bytes_match_committed_blobs": True,
        "test_names_targets_and_requirements_unchanged": True,
        "production_source_pin": "The full candidate tree, not only the selected test-file hashes.",
        "runtime_toolchain": "Must be recorded by the real runner; a repository toolchain file is not proof of the invoked executable.",
        "scope": "A quiescent checkout check, not a concurrent runner or filesystem attestation.",
    }
    result["test_execution"] = "NOT_ESTABLISHED_BY_THIS_TOOL"
    result["evidence_limits"].append(
        "Schema v2 source_snapshot_sha256 fields name final committed bytes; review_source_snapshot_sha256 preserves the reviewed v1 bytes. Source binding is not build, lint or test execution evidence."
    )
    result["evidence_limits"].append(
        "Default nextest JUnit can omit skipped tests. The required-name gate catches missing required cases, but the original runner summary remains necessary for whole-suite skipped counts."
    )
    if identities(result) != before:
        raise RuntimeError("test names, targets or requirements changed during binding")
    ensure_frozen()
    encoded = (json.dumps(result, indent=2) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and args.output.read_bytes() != encoded:
        raise RuntimeError("refusing to overwrite a different execution manifest; use a new versioned path")
    args.output.write_bytes(encoded)
    print(json.dumps({
        "manifest": str(args.output), "manifest_sha256": sha256(encoded),
        "candidate": result["candidate"], "required_count": len(result["required_tests"]),
        "requirements_identity_sha256": result["requirements_identity_sha256"],
        "untracked_paths_observed": result["untracked_paths_observed"],
        "test_execution": result["test_execution"],
    }, indent=2))


if __name__ == "__main__":
    main()
