#!/usr/bin/env python3
"""Release-candidate cognitive.read evidence with witness integrity gates."""

from __future__ import annotations

from pathlib import Path

import cognitive_read_full_evidence as full

WITNESS_INTEGRITY_TESTS = (
    "lane_c_witness_guards_reject_drift_and_reopen_cleanly",
    "lane_c_witness_reopen_rejects_missing_and_weakened_schema",
    "lane_c_witness_reopen_audits_existing_v17_content",
    "unselected_head_rollback_cannot_restore_an_earlier_selection_witness",
    "lane_c_witness_migration_recomputes_nonempty_v16_store",
    "lane_c_witness_migration_rejects_preexisting_drift",
)

_original_commands = full.commands


def commands(candidate: str, evidence: Path) -> dict[str, list[str]]:
    result = _original_commands(candidate, evidence)
    tracked_clean = result.pop("tracked-clean")
    result["witness-integrity-tests"] = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-memory",
        "--test",
        "lane_c_witness_integrity",
        "--no-tests=fail",
        "--status-level",
        "pass",
        "-E",
        full.exact_filter(WITNESS_INTEGRITY_TESTS),
    ]
    result["tracked-clean"] = tracked_clean
    return result


def main() -> None:
    full.EXACT_CASES["witness-integrity-tests"] = WITNESS_INTEGRITY_TESTS
    full.EXACT_BINARIES["witness-integrity-tests"] = (
        "codex-hepta-memory::lane_c_witness_integrity"
    )
    full.install_base_overrides()
    full.base.commands = commands
    full.base.TEST_GATES = set(full.base.TEST_GATES) | {"witness-integrity-tests"}
    full.base.main()


if __name__ == "__main__":
    main()
