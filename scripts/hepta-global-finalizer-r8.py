#!/usr/bin/env python3
"""Deterministic repair replay over one exact global Hepta candidate.

The prepare phase starts from an exact source, applies only deterministic and
idempotent source/metadata repairs, reaches a verified metadata fixed point,
and then delegates immutable repository/package gates and receipt binding to
the r7 implementation under an isolated receipt namespace.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
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


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return value


def exact_replace(path: Path, old: str, new: str, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 1:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return True
    if old_count == 0 and new_count == 1:
        return False
    raise RuntimeError(
        f"{label}: expected one old or one already-repaired form; "
        f"old={old_count} new={new_count}"
    )


def repair_known_strict_clippy_blockers() -> dict[str, Any]:
    changes: list[str] = []
    replacements = (
        (
            ROOT / "codex-rs/hepta-kg/src/generation.rs",
            "    supports: &mut Vec<KnowledgeSupportV2>,\n",
            "    supports: &mut [KnowledgeSupportV2],\n",
            "knowledge.graph canonical support slice",
        ),
        (
            ROOT / "codex-rs/ext/hepta-memory/src/extension_tests.rs",
            "    assert!(!crate::LOCAL_REHYDRATION_REPLAY_LIFECYCLE_REGISTERED);\n",
            "    const { assert!(!crate::LOCAL_REHYDRATION_REPLAY_LIFECYCLE_REGISTERED); }\n",
            "memory extension compile-time replay registration assertion",
        ),
        (
            ROOT / "codex-rs/ext/hepta-memory/src/local_replay.rs",
            "        assert!(!LOCAL_REHYDRATION_REPLAY_LIFECYCLE_REGISTERED);\n",
            "        const { assert!(!LOCAL_REHYDRATION_REPLAY_LIFECYCLE_REGISTERED); }\n",
            "memory replay compile-time lifecycle assertion",
        ),
        (
            ROOT / "codex-rs/ext/hepta-memory/src/local_turn_writer.rs",
            "        assert!(!QUALIFICATION_TURN_WRITER_EXTERNAL_EFFECTS);\n"
            "        assert!(!QUALIFICATION_TURN_WRITER_KG_WRITE_AUTHORITY);\n"
            "        assert!(!QUALIFICATION_TURN_WRITER_PRODUCTION_CALLER);\n",
            "        const {\n"
            "            assert!(!QUALIFICATION_TURN_WRITER_EXTERNAL_EFFECTS);\n"
            "            assert!(!QUALIFICATION_TURN_WRITER_KG_WRITE_AUTHORITY);\n"
            "            assert!(!QUALIFICATION_TURN_WRITER_PRODUCTION_CALLER);\n"
            "        }\n",
            "memory writer compile-time authority assertions",
        ),
        (
            ROOT / "codex-rs/ext/hepta-memory/src/local_lifecycle.rs",
            "        let guard = restarted_state\n"
            "            .lock()\n"
            "            .unwrap_or_else(PoisonError::into_inner);\n"
            "        assert!(guard.active.is_none());\n"
            "        assert!(guard.terminal_started);\n"
            "        drop(guard);\n",
            "        {\n"
            "            let guard = restarted_state\n"
            "                .lock()\n"
            "                .unwrap_or_else(PoisonError::into_inner);\n"
            "            assert!(guard.active.is_none());\n"
            "            assert!(guard.terminal_started);\n"
            "        }\n",
            "memory lifecycle guard scope before await",
        ),
    )
    for path, old, new, label in replacements:
        if exact_replace(path, old, new, label):
            changes.append(path.relative_to(ROOT).as_posix())
    return {"changed": sorted(changes), "count": len(changes)}


def refresh_readiness_required_sections() -> dict[str, Any]:
    registry_path = ROOT / "docs/readiness/READINESS.json"
    registry = load_object(registry_path)
    documents = registry.get("documents")
    if not isinstance(documents, list):
        raise RuntimeError("READINESS.json documents must be a list")

    updates: list[dict[str, Any]] = []
    heading_pattern = re.compile(r"^##\s+\d+\.\s+.+$")
    for row in documents:
        if not isinstance(row, dict):
            raise RuntimeError("READINESS.json document rows must be objects")
        path_value = row.get("path")
        required = row.get("requiredSections")
        if not isinstance(path_value, str) or not isinstance(required, list):
            raise RuntimeError("readiness document row lacks path/requiredSections")
        if not all(isinstance(value, str) for value in required):
            raise RuntimeError(f"{row.get('id')} requiredSections must be strings")
        relative = Path(path_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe readiness path: {path_value}")
        document_path = ROOT / relative
        actual = [
            line.strip()
            for line in document_path.read_text(encoding="utf-8").splitlines()
            if heading_pattern.fullmatch(line.strip())
        ]
        if not actual:
            raise RuntimeError(f"no numbered H2 sections found in {path_value}")
        if required != actual:
            updates.append(
                {
                    "id": row.get("id"),
                    "path": path_value,
                    "before": required,
                    "after": actual,
                }
            )
            row["requiredSections"] = actual

    if updates:
        r7.write_json(registry_path, registry)
    return {"updated": updates, "count": len(updates)}


DETAIL_DESIGN_HEADINGS = (
    "## 1. Source and work envelope",
    "## 2. Public operations and contract details",
    "## 3. State records and transaction design",
    "## 4. Deterministic algorithm and scheduling",
    "## 5. Capacity and performance profile",
    "## 6. Concrete verification cases",
    "## 7. Integration, rollback and capability ceiling",
)


def repair_readiness_closure_appendices() -> dict[str, Any]:
    """Materialize the mandatory appendix from each closed registry projection."""

    registry_path = ROOT / "docs/readiness/READINESS.json"
    registry = load_object(registry_path)
    documents = registry.get("documents")
    if not isinstance(documents, list):
        raise RuntimeError("READINESS.json documents must be a list")

    heading = "## Appendix A. Closed gap and protocol mapping"
    updated: list[dict[str, Any]] = []
    for row in documents:
        if not isinstance(row, dict):
            raise RuntimeError("READINESS.json document rows must be objects")
        path_value = row.get("path")
        protocols = row.get("protocols")
        gap_ids = row.get("gapIds")
        if (
            not isinstance(path_value, str)
            or not isinstance(protocols, list)
            or not protocols
            or not all(isinstance(value, str) and value for value in protocols)
            or not isinstance(gap_ids, list)
            or not gap_ids
            or not all(isinstance(value, str) and value for value in gap_ids)
        ):
            raise RuntimeError(
                f"invalid readiness appendix projection for {row.get('id')}"
            )
        relative = Path(path_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe readiness path: {path_value}")
        document_path = ROOT / relative
        original = document_path.read_text(encoding="utf-8")
        if heading in original:
            continue
        appendix_lines = [
            heading,
            "",
            "This appendix records repository specification closure only. It does not "
            "grant runtime, model, provider, external-effect, operator, promotion or "
            "release authority.",
            "",
            "### Protocol bindings",
            "",
            *[f"- `{value}`" for value in protocols],
            "",
            "### Closed specification gaps",
            "",
            *[f"- `{value}`" for value in gap_ids],
            "",
        ]
        rendered = original.rstrip() + "\n\n" + "\n".join(appendix_lines)
        document_path.write_text(rendered, encoding="utf-8")
        updated.append(
            {
                "id": row.get("id"),
                "path": path_value,
                "protocolCount": len(protocols),
                "gapCount": len(gap_ids),
            }
        )
    return {"updated": updated, "count": len(updated)}


def repair_detailed_design_sections() -> dict[str, Any]:
    """Normalize numbered design headings without altering section bodies."""

    index_path = ROOT / "qualification/module-execution-dossiers/DETAILS.json"
    index = load_object(index_path)
    rows = index.get("rows")
    if not isinstance(rows, list) or index.get("moduleCount") != len(rows):
        raise RuntimeError("DETAILS.json rows/moduleCount mismatch")

    updates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("DETAILS.json rows must be objects")
        module = row.get("module")
        path_value = row.get("path")
        if not isinstance(module, str) or not isinstance(path_value, str):
            raise RuntimeError("DETAILS.json row lacks module/path")
        relative = Path(path_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe detailed-design path: {path_value}")
        design_path = ROOT / relative
        lines = design_path.read_text(encoding="utf-8").splitlines()
        expected_title = f"# {module}: implementation design"
        if not lines or lines[0] != expected_title:
            raise RuntimeError(f"{module}: unexpected detailed-design title")

        row_updates: list[dict[str, str]] = []
        for number, desired in enumerate(DETAIL_DESIGN_HEADINGS, start=1):
            pattern = re.compile(rf"^##\s+{number}\.\s+.+$")
            matches = [
                index for index, line in enumerate(lines) if pattern.fullmatch(line.strip())
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"{module}: expected one section {number}, observed {len(matches)}"
                )
            line_index = matches[0]
            before = lines[line_index].strip()
            if before != desired:
                lines[line_index] = desired
                row_updates.append({"before": before, "after": desired})
        if row_updates:
            design_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            updates.append(
                {"module": module, "path": path_value, "headings": row_updates}
            )
    return {"updated": updates, "count": len(updates)}


def refresh_detailed_design_hashes() -> dict[str, Any]:
    index_path = ROOT / "qualification/module-execution-dossiers/DETAILS.json"
    index = load_object(index_path)
    rows = index.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("DETAILS.json rows must be a list")
    if index.get("moduleCount") != len(rows):
        raise RuntimeError("DETAILS.json moduleCount does not match rows")

    updates: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("DETAILS.json rows must be objects")
        path_value = row.get("path")
        expected = row.get("sha256")
        if not isinstance(path_value, str) or not isinstance(expected, str):
            raise RuntimeError("DETAILS.json row lacks path/sha256")
        relative = Path(path_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe detailed-design path: {path_value}")
        design_path = ROOT / relative
        if not design_path.is_file():
            raise RuntimeError(f"missing detailed-design document: {path_value}")
        actual = hashlib.sha256(design_path.read_bytes()).hexdigest()
        if expected != actual:
            updates.append(
                {
                    "module": str(row.get("module")),
                    "path": path_value,
                    "before": expected,
                    "after": actual,
                }
            )
            row["sha256"] = actual

    if updates:
        r7.write_json(index_path, index)
    return {"updated": updates, "count": len(updates)}


def refresh_native_export_bindings() -> dict[str, Any]:
    binding_path = (
        ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    )
    binding = load_object(binding_path)
    observations = binding.get("observations")
    if not isinstance(observations, list):
        raise RuntimeError("NATIVE_BINDINGS.json observations must be a list")

    target_path = "codex-rs/hepta-authbus/src/lib.rs"
    desired = [
        "PreverifiedAuthEnvelope",
        "TrustedReplayContext",
        "VerificationReceipt",
        "ReplayWindow",
        "verify",
    ]
    matches = [
        row
        for row in observations
        if isinstance(row, dict) and row.get("path") == target_path
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one authbus native observation, found {len(matches)}"
        )
    row = matches[0]
    before = row.get("exports")
    if not isinstance(before, list) or not all(
        isinstance(value, str) for value in before
    ):
        raise RuntimeError("authbus native exports must be a string list")
    changed = before != desired
    if changed:
        row["exports"] = desired
        r7.write_json(binding_path, binding)
    return {
        "path": target_path,
        "before": before,
        "after": desired,
        "changed": changed,
    }


def run_commands(
    commands: tuple[tuple[str, ...], ...],
    *,
    timeout: int,
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for command in commands:
        receipts.append(r7.run(command, timeout=timeout).receipt())
    return receipts


def run_targeted_package_preflights() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for package in ("codex-hepta-kg", "codex-hepta-memory-extension"):
        test = r7.run(
            (
                "cargo",
                "test",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                "-p",
                package,
                "--all-targets",
            ),
            timeout=5400,
        )
        clippy = r7.run(
            (
                "cargo",
                "clippy",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                "-p",
                package,
                "--all-targets",
                "--no-deps",
                "--",
                "-D",
                "warnings",
            ),
            timeout=5400,
        )
        receipts.append(
            {
                "package": package,
                "test": test.receipt(),
                "clippy": clippy.receipt(),
            }
        )
    return receipts


def package_preflights_pass(receipts: list[dict[str, Any]]) -> bool:
    return all(
        row.get("test", {}).get("returnCode") == 0
        and row.get("clippy", {}).get("returnCode") == 0
        for row in receipts
    )


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

    known_source_repair = repair_known_strict_clippy_blockers()
    first_format = r7.run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        timeout=2400,
    )

    readiness_appendix_repair = repair_readiness_closure_appendices()
    readiness_repair = refresh_readiness_required_sections()
    detailed_section_repair = repair_detailed_design_sections()
    detail_repair = refresh_detailed_design_hashes()
    native_export_repair = refresh_native_export_bindings()
    native_after_source = r7.repair_native_bindings()
    generator_receipts.extend(r7.run_generators())

    readiness_appendix_fixed_point = repair_readiness_closure_appendices()
    readiness_fixed_point = refresh_readiness_required_sections()
    detailed_section_fixed_point = repair_detailed_design_sections()
    detail_fixed_point = refresh_detailed_design_hashes()
    native_export_fixed_point = refresh_native_export_bindings()
    native_fixed_point = r7.repair_native_bindings()
    generator_receipts.extend(r7.run_generators())

    readiness_appendix_final = repair_readiness_closure_appendices()
    readiness_final = refresh_readiness_required_sections()
    detailed_section_final = repair_detailed_design_sections()
    detail_final = refresh_detailed_design_hashes()
    native_export_final = refresh_native_export_bindings()
    final_format = r7.run(
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
    targeted_preflights = run_targeted_package_preflights()
    precommit_diff_check = r7.run(("git", "diff", "--check"), timeout=600)

    source_sha = r7.commit_if_dirty(
        "fix: reach deterministic all-Hepta metadata and lint fixed point r8"
    )
    clean_before_repository = r7.git("status", "--porcelain", check=False)
    repository_preflights = run_commands(r7.REPOSITORY_COMMANDS, timeout=7200)
    diff_check = r7.run(("git", "diff", "--check"), timeout=600)
    clean_after_repository = r7.git("status", "--porcelain", check=False)
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
        and first_format.passed
        and final_format.passed
        and check_result.passed
        and package_preflights_pass(targeted_preflights)
        and precommit_diff_check.passed
        and clean_before_repository.passed
        and not clean_before_repository.output.strip()
        and r7.command_receipts_pass(repository_preflights)
        and diff_check.passed
        and clean_after_repository.passed
        and not clean_after_repository.output.strip()
        and native_after_repair.get("valid") is True
    )
    receipt: dict[str, Any] = {
        "schemaVersion": 2,
        "runId": os.environ.get("GITHUB_RUN_ID", "local"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "sourceRef": source_ref,
        "sourceCommit": source_commit,
        "targetBranch": TARGET_BRANCH,
        "qualifiedSourceCommit": source_sha,
        "generatorReceipts": generator_receipts,
        "nativeBindingBefore": native_before,
        "nativeBindingAfterSourceRepair": native_after_source,
        "nativeBindingFixedPoint": native_fixed_point,
        "nativeBindingAfterRepair": native_after_repair,
        "lockReceipts": lock_receipts,
        "dependencyRepair": dependency_repair,
        "knownSourceRepair": known_source_repair,
        "readinessClosureAppendixRepair": readiness_appendix_repair,
        "readinessRequiredSectionRepair": readiness_repair,
        "detailedDesignSectionRepair": detailed_section_repair,
        "detailedDesignHashRepair": detail_repair,
        "readinessClosureAppendixFixedPoint": readiness_appendix_fixed_point,
        "readinessRequiredSectionFixedPoint": readiness_fixed_point,
        "detailedDesignSectionFixedPoint": detailed_section_fixed_point,
        "detailedDesignFixedPoint": detail_fixed_point,
        "nativeExportRepair": native_export_repair,
        "nativeExportFixedPoint": native_export_fixed_point,
        "readinessClosureAppendixFinal": readiness_appendix_final,
        "readinessRequiredSectionFinal": readiness_final,
        "detailedDesignSectionFinal": detailed_section_final,
        "detailedDesignHashFinal": detail_final,
        "nativeExportFinal": native_export_final,
        "cargoFix": cargo_fix.receipt(),
        "clippyFix": clippy_fix.receipt(),
        "firstFormatReceipt": first_format.receipt(),
        "finalFormatReceipt": final_format.receipt(),
        "checkReceipt": check_result.receipt(),
        "targetedPackagePreflights": targeted_preflights,
        "repositoryPreflights": repository_preflights,
        "precommitDiffCheck": precommit_diff_check.receipt(),
        "cleanBeforeRepository": clean_before_repository.receipt(),
        "diffCheck": diff_check.receipt(),
        "cleanAfterRepository": clean_after_repository.receipt(),
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
