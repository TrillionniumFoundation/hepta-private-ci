#!/usr/bin/env python3
"""Deterministic repair replay over the newest global Hepta candidate.

The r8 prepare phase reuses one exact r7 convergence tree, normalizes local
workspace dependencies, lock state, formatting and fixable compiler/Clippy
diagnostics, then delegates immutable repository/package gates and receipt
binding to the r7 implementation under an isolated receipt namespace.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
SCRIPT_DIR = Path(__file__).resolve().parent
R7_PATH = SCRIPT_DIR / "hepta-global-finalizer-r7.py"
SPEC = importlib.util.spec_from_file_location("hepta_global_finalizer_r7", R7_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load r7 executor from {R7_PATH}")
r7 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = r7
SPEC.loader.exec_module(r7)

TARGET_BRANCH = os.environ.get(
    "HEPTA_FINAL_TARGET",
    "integration/hepta-all-gap-closure-20260910-r8",
)
OUT_ROOT = ROOT / os.environ.get(
    "HEPTA_FINAL_OUT_ROOT",
    "qualification/global-gap-closure-final-r8",
)
SOURCE_CANDIDATES = (
    "origin/integration/hepta-all-gap-closure-20260910-r7",
    "origin/integration/hepta-all-gap-closure-20260910-r6",
    "origin/integration/hepta-global-gap-closure-20260910-r5-local",
    "origin/integration/hepta-global-gap-closure-20260910-r4",
    "origin/integration/hepta-global-gap-closure-20260910-r3",
    "origin/integration/hepta-global-gap-closure-20260910",
)
PINNED_R7_SOURCE = "16dc9b1d74b669164860bf9e09d6c5f4c25b7bb0"


def bind_namespace() -> None:
    r7.TARGET_BRANCH = TARGET_BRANCH
    r7.OUT_ROOT = OUT_ROOT
    r7.PREPARE_RECEIPT = OUT_ROOT / "PREPARE.json"
    r7.REPOSITORY_RECEIPT = OUT_ROOT / "REPOSITORY_GATE.json"
    r7.FINAL_STATUS = OUT_ROOT / "STATUS.json"


def source_is_usable(ref: str) -> bool:
    required_status = os.environ.get("HEPTA_REQUIRED_SOURCE_STATUS", "").strip()
    if not required_status:
        return True

    shown = r7.git("show", f"{ref}:{required_status}", check=False)
    if not shown.passed:
        return False
    try:
        value = json.loads(shown.output)
    except json.JSONDecodeError:
        return False
    if not isinstance(value, dict):
        return False

    expected_target = ref.removeprefix("origin/")
    if value.get("targetBranch") != expected_target:
        return False
    if (
        value.get("repositoryInternalValidationPassed") is not True
        or value.get("repositoryInternalGapsClosed") is not True
        or value.get("externalAuthorityGatesRetained") is not True
        or value.get("allGapsClosed") is not False
        or value.get("authorityGranted") is not False
        or value.get("productionActivation") is not False
    ):
        return False

    qualified = value.get("qualifiedSourceCommit")
    if not isinstance(qualified, str) or len(qualified) != 40:
        return False
    return r7.git(
        "rev-parse",
        "--verify",
        f"{qualified}^{{commit}}",
        check=False,
    ).passed


def wait_for_source() -> tuple[str, str]:
    override = os.environ.get("HEPTA_REPAIR_SOURCE", "").strip()
    if not override:
        override = os.environ.get(
            "HEPTA_DEFAULT_REPAIR_SOURCE",
            PINNED_R7_SOURCE,
        ).strip()
    candidates = (override,) if override else SOURCE_CANDIDATES

    for _ in range(2160):
        r7.git(
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            timeout=1800,
        )
        for ref in candidates:
            probe = r7.git("rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
            if probe.passed and source_is_usable(ref):
                return ref, probe.output.strip()
        time.sleep(10)
    raise RuntimeError(
        "no usable exact convergence source appeared for "
        f"candidates={list(candidates)}"
    )


def combined_package_command(
    prefix: tuple[str, ...], packages: list[str]
) -> tuple[str, ...]:
    selectors: list[str] = []
    for package in packages:
        selectors.extend(("-p", package))
    return (*prefix, *selectors, "--all-targets")


def prepare_r8(args: argparse.Namespace) -> int:
    bind_namespace()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    r7.git("config", "user.name", "Hepta Deterministic Repair Finalizer")
    r7.git("config", "user.email", "noreply@openai.com")
    source_ref, source_commit = wait_for_source()
    r7.git("checkout", "-B", TARGET_BRANCH, source_ref)
    r7.git("reset", "--hard", source_ref)
    r7.git("clean", "-fd")

    generator_receipts = r7.run_generators()
    native_before = r7.repair_native_bindings()
    metadata, lock_receipts = r7.normalize_lockfile()
    if metadata is None:
        raise RuntimeError("workspace metadata could not be normalized")
    dependency_repair = r7.repair_missing_local_dependencies(metadata)
    if dependency_repair["count"]:
        metadata, additional = r7.normalize_lockfile()
        lock_receipts.extend(additional)
        if metadata is None:
            raise RuntimeError("workspace metadata failed after dependency repair")
    packages = r7.canonical_hepta_packages(metadata)

    cargo_fix = r7.run(
        combined_package_command(
            (
                "cargo",
                "fix",
                "--allow-dirty",
                "--allow-staged",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
            ),
            packages,
        ),
        timeout=18000,
    )
    clippy_fix = r7.run(
        (
            *combined_package_command(
                (
                    "cargo",
                    "clippy",
                    "--fix",
                    "--allow-dirty",
                    "--allow-staged",
                    "--manifest-path",
                    "codex-rs/Cargo.toml",
                    "--locked",
                ),
                packages,
            ),
            "--no-deps",
            "--",
            "-D",
            "warnings",
        ),
        timeout=18000,
    )
    format_result = r7.run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        timeout=2400,
    )
    native_after_repair = r7.repair_native_bindings()
    metadata, post_repair_lock = r7.normalize_lockfile()
    lock_receipts.extend(post_repair_lock)
    if metadata is None:
        raise RuntimeError("workspace metadata failed after deterministic repair")
    packages = r7.canonical_hepta_packages(metadata)
    check_result = r7.run(
        combined_package_command(
            (
                "cargo",
                "check",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
            ),
            packages,
        ),
        timeout=18000,
    )
    source_sha = r7.commit_if_dirty(
        "fix: apply deterministic all-Hepta convergence repairs r8"
    )
    r7.git(
        "push",
        "--force-with-lease",
        "origin",
        f"HEAD:refs/heads/{TARGET_BRANCH}",
    )

    matrix = r7.shard_matrix(packages, args.shards)
    prepared = (
        r7.command_receipts_pass(generator_receipts)
        and r7.lock_receipts_pass(lock_receipts)
        and format_result.passed
        and check_result.passed
        and native_after_repair.get("valid") is True
    )
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "runId": os.environ.get("GITHUB_RUN_ID", "local"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "sourceRef": source_ref,
        "sourceCommit": source_commit,
        "targetBranch": TARGET_BRANCH,
        "qualifiedSourceCommit": source_sha,
        "generatorReceipts": generator_receipts,
        "nativeBindingBefore": native_before,
        "nativeBindingAfterRepair": native_after_repair,
        "lockReceipts": lock_receipts,
        "dependencyRepair": dependency_repair,
        "cargoFix": cargo_fix.receipt(),
        "clippyFix": clippy_fix.receipt(),
        "formatReceipt": format_result.receipt(),
        "checkReceipt": check_result.receipt(),
        "canonicalHeptaPackageCount": len(packages),
        "canonicalHeptaPackages": packages,
        "matrix": matrix,
        "prepared": prepared,
        "authorityGranted": False,
    }
    r7.write_json(r7.PREPARE_RECEIPT, receipt)
    r7.set_output("candidate_sha", source_sha)
    r7.set_output("candidate_branch", TARGET_BRANCH)
    r7.set_output("matrix", json.dumps(matrix, separators=(",", ":")))
    r7.set_output("package_count", str(len(packages)))
    r7.set_output("prepared", "true" if prepared else "false")
    return 0 if prepared else 3


def main() -> int:
    bind_namespace()
    r7.prepare = prepare_r8
    parser = r7.build_parser()
    args = parser.parse_args()
    return int(args.function(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_GLOBAL_FINALIZER_R8_ERROR: {error}", file=sys.stderr)
        raise
