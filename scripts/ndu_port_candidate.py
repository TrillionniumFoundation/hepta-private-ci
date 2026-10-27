#!/usr/bin/env python3
"""Generate or qualify one source-bound dependency port without promotion."""

import argparse
import json
import os
from pathlib import Path
import shutil

from ndu_port_candidate_common import LOCKS
from ndu_port_candidate_common import POLICIES
from ndu_port_candidate_common import RECIPE
from ndu_port_candidate_common import Recorder
from ndu_port_candidate_common import changed_paths
from ndu_port_candidate_common import check_checkout
from ndu_port_candidate_common import check_toolchain
from ndu_port_candidate_common import checksum
from ndu_port_candidate_common import copy_files
from ndu_port_candidate_common import describe
from ndu_port_candidate_common import load_candidate
from ndu_port_candidate_common import load_recipe
from ndu_port_candidate_common import patch_paths
from ndu_port_candidate_common import restore_candidate
from ndu_port_candidate_common import validate_graph
from ndu_port_candidate_common import verify_tree
from ndu_port_candidate_common import verify_vendor


TEST_GROUPS = {
    "yaml": (
        "codex-utils-yaml",
        "codex-skills",
        "codex-skills-extension",
        "codex-core-plugins",
        "codex-external-agent-migration",
    ),
    "aws": ("codex-aws-auth", "codex-login", "codex-secrets"),
    "keyring": ("codex-keyring-store",),
    "execpolicy": ("codex-execpolicy",),
    "matrix": (
        "codex-hepta-matrix-protocol",
        "codex-hepta-matrix-store",
        "codex-hepta-matrix-sdk",
        "codex-hepta-matrixd",
    ),
}
BAZEL_TARGETS = (
    "//codex-rs/utils/yaml:yaml",
    "//codex-rs/aws-auth:aws-auth",
    "//codex-rs/keyring-store:keyring-store",
    "//codex-rs/execpolicy:execpolicy",
    "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk",
    "//codex-rs/third_party/serde-saphyr-2.0.0:serde-saphyr",
    "//codex-rs/third_party/aws-config-1.8.12:aws-config",
    "//codex-rs/third_party/keyring-3.6.3:keyring",
    "//codex-rs/third_party/secret-service-4.0.0:secret-service",
    "//codex-rs/third_party/matrix-sdk-0.19.1:matrix-sdk",
    "//codex-rs/third_party/matrix-sdk-sqlite-0.19.1:matrix-sdk-sqlite",
    "//codex-rs/third_party/starlark-0.14.2:starlark",
)


def generate(runner, expected_source):
    check_checkout(runner, expected_source)
    recipe = load_recipe(runner.root)
    runner.record.update(
        recipe_sha256=checksum(runner.root / RECIPE),
        policy_inputs=describe(runner.root, POLICIES),
        lock_inputs=describe(runner.root, LOCKS),
    )
    shutil.copyfile(runner.root / RECIPE, runner.output / "recipe.json")
    shutil.copyfile(runner.root / recipe["patch_path"], runner.output / "source.patch")
    patch = runner.output / "source.patch"
    if patch_paths(runner, patch) != set(recipe["allowed_paths"]):
        raise ValueError(
            "Source patch path set differs from the exact recipe allowlist"
        )
    runner.run("check-source-patch", ["git", "apply", "--check", "--index", str(patch)])
    runner.run("apply-source-patch", ["git", "apply", "--index", str(patch)])
    fixed_source = describe(runner.root, recipe["allowed_paths"], allow_missing=True)
    verify_vendor(runner.root, recipe)
    check_toolchain(runner, "1.96.0")
    runner.run("bazel-version", ["bazel", "--version"])
    manifest = str(runner.root / "codex-rs/Cargo.toml")
    for index, update in enumerate(recipe["cargo_updates"]):
        command = [
            "cargo",
            "update",
            "--manifest-path",
            manifest,
            "--package",
            update["package"],
        ]
        if "precise" in update:
            command.extend(["--precise", update["precise"]])
        runner.run(f"cargo-update-{index}", command)
    metadata_command = [
        "cargo",
        "metadata",
        "--manifest-path",
        manifest,
        "--locked",
        "--format-version",
        "1",
    ]
    metadata = runner.json_command("metadata-before-bazel", metadata_command)
    validate_graph(runner.root, recipe, metadata)
    runner.run("bazel-lock-update", ["just", "bazel-lock-update"])
    runner.run("bazel-lock-check", ["just", "bazel-lock-check"])
    metadata = runner.json_command("metadata", metadata_command)
    runner.run("diff-check", ["git", "diff", "--check", "HEAD"])
    if (
        describe(runner.root, recipe["allowed_paths"], allow_missing=True)
        != fixed_source
    ):
        raise ValueError("A resolver modified the reviewed source patch")
    validate_graph(runner.root, recipe, metadata)
    changed = changed_paths(runner)
    if not set(recipe["allowed_paths"]) <= changed or not changed <= set(
        (*recipe["allowed_paths"], *LOCKS)
    ):
        raise ValueError(
            "Resolved candidate differs from the approved source/lock scope"
        )
    inventory = describe(
        runner.root, (*recipe["allowed_paths"], *LOCKS), allow_missing=True
    )
    copy_files(runner.root, runner.output / "files", inventory)
    runner.record.update(files=inventory, changed_paths=sorted(changed))
    verify_tree(runner, runner.record, recipe)
    complete_patch = runner.output / "candidate.patch"
    runner.run(
        "export-candidate-patch",
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            "--no-renames",
            f"--output={complete_patch}",
            "HEAD",
        ],
    )
    if patch_paths(runner, complete_patch) != changed:
        raise ValueError("Exported complete binary patch has a different file set")
    runner.record.update(
        artifacts=describe(
            runner.output,
            (
                "recipe.json",
                "source.patch",
                "candidate.patch",
                "metadata-before-bazel.json",
                "metadata.json",
            ),
        ),
        status="candidate_generated",
        qualification="Only source/graph/Cargo/Bazel lock generation. Tests, unchanged cargo-deny and platform gates remain separate.",
    )


def junit_inventory(runner):
    directory = Path(
        os.environ.get("CARGO_TARGET_DIR", runner.root / "codex-rs/target")
    )
    if not directory.is_absolute():
        directory = runner.root / "codex-rs" / directory
    return {
        path: (path.stat().st_mtime_ns, checksum(path))
        for path in directory.glob("nextest/*/junit.xml")
    }


def workspace_tests(runner, record, recipe, group):
    runner.run("nextest-version", ["cargo", "nextest", "--version"])
    runner.record.update(test_group=group, test_results=[])
    failures = []
    for package in TEST_GROUPS[group]:
        before = junit_inventory(runner)
        status = runner.run(
            f"test-{package}",
            ["just", "test", "--locked", "--cargo-profile", "ci-test", "-p", package],
            required=False,
        )
        outcome = {
            "package": package,
            "exit_code": status,
            "command_index": len(runner.record["commands"]) - 1,
            "junit": [],
        }
        for path, description in junit_inventory(runner).items():
            if before.get(path) != description:
                target = runner.output / f"{package}-{path.parent.name}-junit.xml"
                shutil.copyfile(path, target)
                outcome["junit"].append(
                    {"file": target.name, "sha256": checksum(target)}
                )
        runner.record["test_results"].append(outcome)
        if status:
            failures.append(package)
        verify_tree(runner, record, recipe)
        runner.save()
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("generate", "test", "restore", "verify", "bazel", "upstream-aws"),
        required=True,
    )
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--expected-result-sha256")
    parser.add_argument("--group", choices=TEST_GROUPS)
    parser.add_argument("--old-fixture", type=Path)
    parser.add_argument("--expected-old-result-sha256")
    args = parser.parse_args()
    runner = Recorder(args.repository, args.output, args.mode)
    success = False
    try:
        if args.mode == "generate":
            generate(runner, args.expected_source)
            success = True
        else:
            if not args.candidate or not args.expected_result_sha256:
                raise ValueError(
                    "Consumer requires the bound producer artifact and result SHA"
                )
            if args.mode == "verify":
                record, recipe = load_candidate(
                    runner,
                    args.candidate,
                    args.expected_result_sha256,
                    args.expected_source,
                )
                verify_tree(runner, record, recipe)
                runner.record.update(
                    source_commit=args.expected_source,
                    candidate_result_sha256=args.expected_result_sha256,
                    recipe_sha256=record["recipe_sha256"],
                )
            else:
                record, recipe = restore_candidate(
                    runner,
                    args.candidate,
                    args.expected_result_sha256,
                    args.expected_source,
                )
            check_toolchain(runner, "1.96.0")
            if args.mode == "upstream-aws":
                from ndu_port_aws_upstream import qualify_aws

                try:
                    success = qualify_aws(runner, recipe)
                finally:
                    verify_tree(runner, record, recipe)
                runner.record["status"] = (
                    "full_upstream_aws_passed"
                    if success
                    else "full_upstream_aws_failed"
                )
            elif args.mode == "bazel":
                runner.run("bazel-version", ["bazel", "--version"])
                status = runner.run(
                    "bazel-candidate-libraries",
                    [
                        "bazel",
                        "build",
                        "--config=ci-bazel",
                        "--platforms=//:local_linux",
                        "--lockfile_mode=error",
                        *BAZEL_TARGETS,
                    ],
                    required=False,
                )
                verify_tree(runner, record, recipe)
                runner.record.update(
                    status="bazel_build_failed" if status else "bazel_libraries_built",
                    bazel_targets=BAZEL_TARGETS,
                    bazel_exit_code=status,
                    qualification="Linux library and first-party consumer builds only; not all-platform or full-workspace tests.",
                )
                success = status == 0
            elif args.mode == "test":
                if not args.group:
                    raise ValueError("A test group is required")
                failures = workspace_tests(runner, record, recipe, args.group)
                if args.group == "matrix":
                    if not args.old_fixture or not args.expected_old_result_sha256:
                        raise ValueError(
                            "Matrix tests also require the independent old-version artifact"
                        )
                    from ndu_port_matrix_fixture import consume_old_fixture

                    try:
                        consume_old_fixture(
                            runner,
                            recipe,
                            args.old_fixture,
                            args.expected_old_result_sha256,
                            args.expected_source,
                        )
                    except Exception as error:
                        runner.record["matrix_migration_error"] = {
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                        failures.append("old-version-fixture-reopen")
                    verify_tree(runner, record, recipe)
                runner.record.update(
                    status="tests_failed" if failures else "targeted_tests_passed",
                    failed_tests=failures,
                )
                success = not failures
            else:
                runner.record["status"] = (
                    "candidate_restored"
                    if args.mode == "restore"
                    else "candidate_verified_unchanged"
                )
                success = True
    except Exception as error:
        runner.record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        if args.mode == "generate":
            try:
                recipe = load_recipe(runner.root)
                partial = describe(
                    runner.root, (*recipe["allowed_paths"], *LOCKS), allow_missing=True
                )
                copy_files(runner.root, runner.output / "partial-files", partial)
                runner.record["partial_files"] = partial
                runner.record["original_dependency_policy_unchanged"] = describe(
                    runner.root, POLICIES
                ) == runner.record.get("policy_inputs")
            except Exception as snapshot_error:
                runner.record["partial_snapshot_error"] = str(snapshot_error)
    finally:
        runner.save()
    if success and args.mode == "generate" and os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write(f"source_commit={runner.record['source_commit']}\n")
            stream.write(f"result_sha256={checksum(runner.output / 'RESULT.json')}\n")
    print(
        json.dumps(
            {
                "status": runner.record["status"],
                "result": str(runner.output / "RESULT.json"),
            }
        ),
        flush=True,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
