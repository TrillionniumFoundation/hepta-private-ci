#!/usr/bin/env python3
"""Patch r8 to normalize all document sections and preflight a committed tree."""
from __future__ import annotations

from pathlib import Path

TARGET = Path("scripts/hepta-global-finalizer-r8.py")


def replace_once_or_verify(text: str, old: str, new: str, marker: str) -> str:
    if marker in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"r20 patch precondition drift for {marker!r}: old-count={count}"
        )
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    function_marker = "def refresh_detailed_design_hashes() -> dict[str, Any]:\n"
    function_block = r'''DETAIL_DESIGN_HEADINGS = (
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


'''
    text = replace_once_or_verify(
        text,
        function_marker,
        function_block + function_marker,
        "def repair_readiness_closure_appendices()",
    )

    old_repair_sequence = '''    readiness_repair = refresh_readiness_required_sections()
    detail_repair = refresh_detailed_design_hashes()
    native_export_repair = refresh_native_export_bindings()
    native_after_source = r7.repair_native_bindings()
    generator_receipts.extend(r7.run_generators())

    detail_fixed_point = refresh_detailed_design_hashes()
    native_fixed_point = r7.repair_native_bindings()
    generator_receipts.extend(r7.run_generators())
    final_format = r7.run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        timeout=2400,
    )
    native_after_repair = r7.repair_native_bindings()
'''
    new_repair_sequence = '''    readiness_appendix_repair = repair_readiness_closure_appendices()
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
'''
    text = replace_once_or_verify(
        text,
        old_repair_sequence,
        new_repair_sequence,
        "readiness_appendix_fixed_point = repair_readiness_closure_appendices()",
    )

    old_preflight_sequence = '''    targeted_preflights = run_targeted_package_preflights()
    repository_preflights = run_commands(r7.REPOSITORY_COMMANDS, timeout=7200)
    diff_check = r7.run(("git", "diff", "--check"), timeout=600)

    source_sha = r7.commit_if_dirty(
        "fix: reach deterministic all-Hepta metadata and lint fixed point r8"
    )
    r7.git(
        "push",
        "--force-with-lease",
        "origin",
        f"HEAD:refs/heads/{TARGET_BRANCH}",
    )
'''
    new_preflight_sequence = '''    targeted_preflights = run_targeted_package_preflights()
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
'''
    text = replace_once_or_verify(
        text,
        old_preflight_sequence,
        new_preflight_sequence,
        'clean_before_repository = r7.git("status", "--porcelain", check=False)',
    )

    old_prepared = '''        and package_preflights_pass(targeted_preflights)
        and r7.command_receipts_pass(repository_preflights)
        and diff_check.passed
        and native_after_repair.get("valid") is True
'''
    new_prepared = '''        and package_preflights_pass(targeted_preflights)
        and precommit_diff_check.passed
        and clean_before_repository.passed
        and not clean_before_repository.output.strip()
        and r7.command_receipts_pass(repository_preflights)
        and diff_check.passed
        and clean_after_repository.passed
        and not clean_after_repository.output.strip()
        and native_after_repair.get("valid") is True
'''
    text = replace_once_or_verify(
        text,
        old_prepared,
        new_prepared,
        "and not clean_after_repository.output.strip()",
    )

    old_receipt_fields = '''        "readinessRequiredSectionRepair": readiness_repair,
        "detailedDesignHashRepair": detail_repair,
        "detailedDesignFixedPoint": detail_fixed_point,
        "nativeExportRepair": native_export_repair,
'''
    new_receipt_fields = '''        "readinessClosureAppendixRepair": readiness_appendix_repair,
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
'''
    text = replace_once_or_verify(
        text,
        old_receipt_fields,
        new_receipt_fields,
        '"readinessClosureAppendixFinal": readiness_appendix_final',
    )

    old_tail_fields = '''        "repositoryPreflights": repository_preflights,
        "diffCheck": diff_check.receipt(),
'''
    new_tail_fields = '''        "repositoryPreflights": repository_preflights,
        "precommitDiffCheck": precommit_diff_check.receipt(),
        "cleanBeforeRepository": clean_before_repository.receipt(),
        "diffCheck": diff_check.receipt(),
        "cleanAfterRepository": clean_after_repository.receipt(),
'''
    text = replace_once_or_verify(
        text,
        old_tail_fields,
        new_tail_fields,
        '"cleanAfterRepository": clean_after_repository.receipt()',
    )

    required = (
        "def repair_readiness_closure_appendices()",
        "def repair_detailed_design_sections()",
        'heading = "## Appendix A. Closed gap and protocol mapping"',
        "detailed_section_final = repair_detailed_design_sections()",
        'clean_before_repository = r7.git("status", "--porcelain", check=False)',
        "and not clean_after_repository.output.strip()",
        '"readinessClosureAppendixFinal": readiness_appendix_final',
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"r20 output missing required phrase: {phrase}")

    TARGET.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
