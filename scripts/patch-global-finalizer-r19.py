#!/usr/bin/env python3
"""Patch r7 with fixed-point projections, overlays, and exact Rust repairs."""
from __future__ import annotations

import re
from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")

INSERTED_FUNCTIONS = r'''
def repair_repository_lints() -> dict[str, Any]:
    """Apply exact, behavior-preserving repairs for strict Rust 1.98 Clippy."""

    repairs: tuple[tuple[Path, str, str, int], ...] = (
        (
            Path("codex-rs/hepta-prompt-registry/src/v2_tests.rs"),
            "let mut wrong_tuple = tuple.clone();",
            "let mut wrong_tuple = tuple;",
            1,
        ),
        (
            Path("codex-rs/hepta-runtime/src/lib.rs"),
            "for (index, pair) in encoded.chunks_exact(2).enumerate() {",
            "for (index, pair) in encoded.as_chunks::<2>().0.iter().enumerate() {",
            1,
        ),
        (
            Path("codex-rs/hepta-runtime/src/lib.rs"),
            "for (index, pair) in encoded.as_bytes().chunks_exact(2).enumerate() {",
            "for (index, pair) in encoded.as_bytes().as_chunks::<2>().0.iter().enumerate() {",
            1,
        ),
        (
            Path("codex-rs/hepta-kg/src/generation.rs"),
            "fn canonicalize_supports(\n    supports: &mut Vec<KnowledgeSupportV2>,\n) -> Result<(), KnowledgeGenerationErrorV2> {",
            "fn canonicalize_supports(\n    supports: &mut [KnowledgeSupportV2],\n) -> Result<(), KnowledgeGenerationErrorV2> {",
            1,
        ),
        (
            Path("codex-rs/ext/hepta-memory/src/extension_tests.rs"),
            "assert!(!crate::LOCAL_REHYDRATION_REPLAY_LIFECYCLE_REGISTERED);",
            "const _: () = assert!(!crate::LOCAL_REHYDRATION_REPLAY_LIFECYCLE_REGISTERED);",
            1,
        ),
        (
            Path("codex-rs/ext/hepta-memory/src/local_replay.rs"),
            "assert!(!LOCAL_REHYDRATION_REPLAY_LIFECYCLE_REGISTERED);",
            "const _: () = assert!(!LOCAL_REHYDRATION_REPLAY_LIFECYCLE_REGISTERED);",
            1,
        ),
        (
            Path("codex-rs/ext/hepta-memory/src/local_turn_writer.rs"),
            "assert!(!QUALIFICATION_TURN_WRITER_EXTERNAL_EFFECTS);",
            "const _: () = assert!(!QUALIFICATION_TURN_WRITER_EXTERNAL_EFFECTS);",
            1,
        ),
        (
            Path("codex-rs/ext/hepta-memory/src/local_turn_writer.rs"),
            "assert!(!QUALIFICATION_TURN_WRITER_KG_WRITE_AUTHORITY);",
            "const _: () = assert!(!QUALIFICATION_TURN_WRITER_KG_WRITE_AUTHORITY);",
            1,
        ),
        (
            Path("codex-rs/ext/hepta-memory/src/local_turn_writer.rs"),
            "assert!(!QUALIFICATION_TURN_WRITER_PRODUCTION_CALLER);",
            "const _: () = assert!(!QUALIFICATION_TURN_WRITER_PRODUCTION_CALLER);",
            1,
        ),
        (
            Path("codex-rs/ext/hepta-memory/src/local_lifecycle.rs"),
            """        let guard = restarted_state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        assert!(guard.active.is_none());
        assert!(guard.terminal_started);
        drop(guard);
""",
            """        {
            let guard = restarted_state
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            assert!(guard.active.is_none());
            assert!(guard.terminal_started);
        }
""",
            1,
        ),
        (
            Path("codex-rs/hepta-supervisor/src/authority_signer.rs"),
            "for (index, pair) in text.as_bytes().chunks_exact(2).enumerate() {",
            "for (index, pair) in text.as_bytes().as_chunks::<2>().0.iter().enumerate() {",
            1,
        ),
        (
            Path("codex-rs/hepta-supervisor/src/daemon_protocol.rs"),
            "for (index, pair) in self.0.as_bytes().chunks_exact(2).enumerate() {",
            "for (index, pair) in self.0.as_bytes().as_chunks::<2>().0.iter().enumerate() {",
            1,
        ),
    )
    changed: list[str] = []
    applied: list[dict[str, Any]] = []
    for path, old, new, expected_count in repairs:
        source = path.read_text(encoding="utf-8")
        old_count = source.count(old)
        new_count = source.count(new)
        if old_count == expected_count and new_count == 0:
            path.write_text(source.replace(old, new), encoding="utf-8")
            changed.append(path.as_posix())
            applied.append(
                {
                    "path": path.as_posix(),
                    "replacementCount": expected_count,
                    "alreadyApplied": False,
                }
            )
            continue
        if old_count == 0 and new_count == expected_count:
            applied.append(
                {
                    "path": path.as_posix(),
                    "replacementCount": expected_count,
                    "alreadyApplied": True,
                }
            )
            continue
        raise RuntimeError(
            f"strict-Clippy repair drift for {path}: "
            f"old={old_count} new={new_count} expected={expected_count}"
        )
    return {
        "changed": sorted(set(changed)),
        "changedFileCount": len(set(changed)),
        "repairCount": len(repairs),
        "repairs": applied,
    }


def repair_repository_projections() -> dict[str, Any]:
    """Regenerate readiness sections and all 40 detailed-design digests."""

    changed: list[str] = []
    readiness_path = ROOT / "docs/readiness/READINESS.json"
    readiness = read_json(readiness_path)
    documents = readiness.get("documents")
    if not isinstance(documents, list):
        raise RuntimeError("readiness documents must be a list")
    objective_rows = [row for row in documents if row.get("id") == "RDY-OBJ"]
    if len(objective_rows) != 1:
        raise RuntimeError(
            f"expected exactly one RDY-OBJ document, observed {len(objective_rows)}"
        )
    objective_row = objective_rows[0]
    objective_path_value = objective_row.get("path")
    if not isinstance(objective_path_value, str) or not objective_path_value:
        raise RuntimeError("RDY-OBJ path must be a non-empty string")
    objective_path = ROOT / objective_path_value
    objective_text = objective_path.read_text(encoding="utf-8")
    numbered_sections: list[tuple[int, str]] = []
    for line in objective_text.splitlines():
        match = re.fullmatch(r"## ([1-9][0-9]*)\. (.+)", line)
        if match:
            numbered_sections.append(
                (int(match.group(1)), f"{match.group(1)}. {match.group(2)}")
            )
    if [number for number, _ in numbered_sections] != list(range(1, 12)):
        raise RuntimeError(
            "RDY-OBJ must contain exactly the contiguous numbered sections 1..11"
        )
    required_sections = [section for _, section in numbered_sections]
    if objective_row.get("requiredSections") != required_sections:
        objective_row["requiredSections"] = required_sections
        write_json(readiness_path, readiness)
        changed.append(readiness_path.relative_to(ROOT).as_posix())

    details_path = ROOT / "qualification/module-execution-dossiers/DETAILS.json"
    details = read_json(details_path)
    rows = details.get("rows")
    if (
        details.get("moduleCount") != 40
        or not isinstance(rows, list)
        or len(rows) != 40
    ):
        raise RuntimeError("detailed-design index must contain exactly 40 rows")
    modules = [row.get("module") for row in rows if isinstance(row, dict)]
    if len(modules) != 40 or len(set(modules)) != 40:
        raise RuntimeError("detailed-design index modules must be unique and complete")
    updated_designs: list[str] = []
    for row in rows:
        design_value = row.get("path")
        module = row.get("module")
        if not isinstance(design_value, str) or not design_value:
            raise RuntimeError(f"detailed-design path missing for {module}")
        design_path = ROOT / design_value
        if not design_path.is_file():
            raise RuntimeError(f"detailed-design file missing for {module}: {design_value}")
        actual = hashlib.sha256(design_path.read_bytes()).hexdigest()
        if row.get("sha256") != actual:
            row["sha256"] = actual
            updated_designs.append(str(module))
    if updated_designs:
        write_json(details_path, details)
        changed.append(details_path.relative_to(ROOT).as_posix())

    return {
        "changed": changed,
        "count": len(changed),
        "objectiveRequiredSections": required_sections,
        "updatedDesignModules": updated_designs,
        "updatedDesignCount": len(updated_designs),
    }


'''

REPLACEMENT_NATIVE = r'''def repair_native_bindings() -> dict[str, Any]:
    """Rebind the main native index and every lane overlay to frozen sources."""

    base = ROOT / "qualification/module-execution-dossiers"
    main_path = base / "NATIVE_BINDINGS.json"
    paths = [main_path, *sorted(base.glob("NATIVE_BINDINGS_LANE_*.json"))]
    if not main_path.is_file():
        return {
            "present": False,
            "valid": False,
            "updated": 0,
            "files": [],
            "failures": [{"path": main_path.as_posix(), "reason": "missing"}],
        }

    total_updated = 0
    all_failures: list[dict[str, Any]] = []
    file_receipts: list[dict[str, Any]] = []
    main_observation_count = 0
    main_coverage: Any = None
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        document = read_json(path)
        observations = document.get("observations")
        file_failures: list[dict[str, Any]] = []
        updated = 0
        if not isinstance(observations, list):
            file_failures.append(
                {"index": relative, "reason": "observations must be a list"}
            )
            observations = []
        modules = [
            row.get("module") if isinstance(row, dict) else None
            for row in observations
        ]
        duplicates = sorted(
            str(module)
            for module in set(modules)
            if modules.count(module) > 1
        )
        if duplicates:
            file_failures.append(
                {"index": relative, "reason": "duplicate modules", "modules": duplicates}
            )
        for row in observations:
            if not isinstance(row, dict):
                file_failures.append(
                    {"index": relative, "reason": "observation must be an object"}
                )
                continue
            module = row.get("module")
            source = row.get("path")
            exports = row.get("exports")
            if (
                not isinstance(module, str)
                or not module
                or not isinstance(source, str)
                or not source
                or not isinstance(exports, list)
                or not exports
            ):
                file_failures.append(
                    {
                        "index": relative,
                        "module": module,
                        "path": source,
                        "reason": "invalid observation shape",
                    }
                )
                continue
            source_path = ROOT / source
            if not source_path.is_file():
                file_failures.append(
                    {
                        "index": relative,
                        "module": module,
                        "path": source,
                        "reason": "source missing",
                    }
                )
                continue
            source_text = source_path.read_text(encoding="utf-8", errors="replace")
            missing_exports = [
                value
                for value in exports
                if not isinstance(value, str) or not value or value not in source_text
            ]
            if missing_exports:
                file_failures.append(
                    {
                        "index": relative,
                        "module": module,
                        "path": source,
                        "reason": "export missing",
                        "exports": missing_exports,
                    }
                )
            actual = git_text("hash-object", "--", source)
            if row.get("blobSha") != actual:
                row["blobSha"] = actual
                updated += 1
        coverage = document.get("moduleCoverage")
        is_main = path == main_path
        coverage_valid = (
            coverage == 40 and len(observations) == 40
            if is_main
            else isinstance(coverage, int)
            and not isinstance(coverage, bool)
            and coverage == len(observations)
            and coverage > 0
        )
        if not coverage_valid:
            file_failures.append(
                {
                    "index": relative,
                    "reason": "coverage mismatch",
                    "moduleCoverage": coverage,
                    "observationCount": len(observations),
                }
            )
        if updated:
            write_json(path, document)
        if is_main:
            main_observation_count = len(observations)
            main_coverage = coverage
        total_updated += updated
        all_failures.extend(file_failures)
        file_receipts.append(
            {
                "path": relative,
                "main": is_main,
                "moduleCoverage": coverage,
                "observationCount": len(observations),
                "updated": updated,
                "failures": file_failures,
                "valid": not file_failures,
            }
        )

    return {
        "present": True,
        "moduleCoverage": main_coverage,
        "observationCount": main_observation_count,
        "updated": total_updated,
        "files": file_receipts,
        "failures": all_failures,
        "valid": bool(file_receipts) and not all_failures,
    }
'''


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if marker in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r19 patch precondition drift for {marker!r}: count={count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")

    if "def repair_repository_lints()" not in text:
        marker = "def repair_argument_comment_blockers() -> dict[str, Any]:\n"
        if text.count(marker) != 1:
            raise SystemExit("r19 insertion marker drifted")
        text = text.replace(marker, INSERTED_FUNCTIONS + marker, 1)

    native_pattern = re.compile(
        r"def repair_native_bindings\(\) -> dict\[str, Any\]:\n.*?\n\ndef cargo_metadata\(",
        re.DOTALL,
    )
    native_matches = list(native_pattern.finditer(text))
    if "Rebind the main native index and every lane overlay" not in text:
        if len(native_matches) != 1:
            raise SystemExit(
                f"r19 native function drifted: expected 1, observed {len(native_matches)}"
            )
        text = native_pattern.sub(
            lambda _: REPLACEMENT_NATIVE + "\n\ndef cargo_metadata(",
            text,
            count=1,
        )

    old_prepare = '''    argument_comment_repair = repair_argument_comment_blockers()
    generator_receipts = run_generators()
    lane_g_artifact_repair = repair_lane_g_shared_artifacts(selected)
    native_before = repair_native_bindings()
    metadata, lock_receipts = normalize_lockfile()
    if metadata is None:
        raise RuntimeError("workspace metadata could not be normalized")
    dependency_repair = repair_missing_local_dependencies(metadata)
    if dependency_repair["count"]:
        metadata, extra_lock_receipts = normalize_lockfile()
        lock_receipts.extend(extra_lock_receipts)
        if metadata is None:
            raise RuntimeError("workspace metadata failed after dependency repair")
    packages = canonical_hepta_packages(metadata)
    compile_receipts = run_prepare_compile_checks(packages)
    format_result = run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        timeout=2400,
    )
    native_after_format = repair_native_bindings()
'''
    new_prepare = '''    argument_comment_repair = repair_argument_comment_blockers()
    generator_receipts = run_generators()
    lane_g_artifact_repair = repair_lane_g_shared_artifacts(selected)
    native_before = repair_native_bindings()
    repository_lint_repair = repair_repository_lints()
    metadata, lock_receipts = normalize_lockfile()
    if metadata is None:
        raise RuntimeError("workspace metadata could not be normalized")
    dependency_repair = repair_missing_local_dependencies(metadata)
    if dependency_repair["count"]:
        metadata, extra_lock_receipts = normalize_lockfile()
        lock_receipts.extend(extra_lock_receipts)
        if metadata is None:
            raise RuntimeError("workspace metadata failed after dependency repair")
    packages = canonical_hepta_packages(metadata)
    compile_receipts = run_prepare_compile_checks(packages)
    format_result = run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        timeout=2400,
    )
    projection_after_format = repair_repository_projections()
    final_generator_receipts = run_generators()
    projection_after_generators = repair_repository_projections()
    native_after_format = repair_native_bindings()
    projection_fixed_point = repair_repository_projections()
    native_fixed_point = repair_native_bindings()
    projection_preflight_receipts = [
        run(command, timeout=1800).receipt()
        for command in (
            ("python3", "scripts/hepta-readiness.py", "verify"),
            ("python3", "scripts/hepta-technical-closure.py", "verify"),
            (
                "python3",
                "qualification/module-execution-dossiers/implementation_contracts.py",
                "self-test",
            ),
            (
                "python3",
                "qualification/module-execution-dossiers/implementation_contracts.py",
                "verify-repository",
            ),
        )
    ]
'''
    text = replace_once(
        text,
        old_prepare,
        new_prepare,
        "repository_lint_repair = repair_repository_lints()",
    )

    old_prepared = '''        command_receipts_pass(generator_receipts)
        and lock_receipts_pass(lock_receipts)
        and command_receipts_pass(compile_receipts)
        and format_result.passed
        and native_after_format.get("valid") is True
'''
    new_prepared = '''        command_receipts_pass(generator_receipts)
        and command_receipts_pass(final_generator_receipts)
        and lock_receipts_pass(lock_receipts)
        and command_receipts_pass(compile_receipts)
        and format_result.passed
        and projection_fixed_point.get("count") == 0
        and native_after_format.get("valid") is True
        and native_fixed_point.get("valid") is True
        and native_fixed_point.get("updated") == 0
        and command_receipts_pass(projection_preflight_receipts)
'''
    text = replace_once(
        text,
        old_prepared,
        new_prepared,
        "and projection_fixed_point.get(\"count\") == 0",
    )

    text = replace_once(
        text,
        '''        "argumentCommentRepair": argument_comment_repair,
        "generatorReceipts": generator_receipts,
        "laneGArtifactRepair": lane_g_artifact_repair,
        "nativeBindingBefore": native_before,
''',
        '''        "argumentCommentRepair": argument_comment_repair,
        "repositoryLintRepair": repository_lint_repair,
        "generatorReceipts": generator_receipts,
        "finalGeneratorReceipts": final_generator_receipts,
        "laneGArtifactRepair": lane_g_artifact_repair,
        "projectionAfterFormat": projection_after_format,
        "projectionAfterGenerators": projection_after_generators,
        "projectionFixedPoint": projection_fixed_point,
        "projectionPreflightReceipts": projection_preflight_receipts,
        "nativeBindingBefore": native_before,
''',
        '"repositoryLintRepair": repository_lint_repair',
    )
    text = replace_once(
        text,
        '''        "nativeBindingAfterFormat": native_after_format,
        "lockReceipts": lock_receipts,
''',
        '''        "nativeBindingAfterFormat": native_after_format,
        "nativeBindingFixedPoint": native_fixed_point,
        "lockReceipts": lock_receipts,
''',
        '"nativeBindingFixedPoint": native_fixed_point',
    )

    required = (
        "def repair_repository_lints()",
        "def repair_repository_projections()",
        "Rebind the main native index and every lane overlay",
        'base.glob("NATIVE_BINDINGS_LANE_*.json")',
        "repository_lint_repair = repair_repository_lints()",
        "projection_after_format = repair_repository_projections()",
        "projection_fixed_point = repair_repository_projections()",
        "native_fixed_point = repair_native_bindings()",
        '"projectionPreflightReceipts": projection_preflight_receipts',
        '"nativeBindingFixedPoint": native_fixed_point',
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"r19 patched finalizer missing: {phrase}")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
