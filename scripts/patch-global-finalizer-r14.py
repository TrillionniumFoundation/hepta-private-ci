#!/usr/bin/env python3
"""Apply the exact, idempotent Lane F/G semantic convergence repair."""
from __future__ import annotations

from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")

    def replace_once_or_verify(old: str, new: str, marker: str) -> None:
        nonlocal text
        if marker in text:
            return
        count = text.count(old)
        if count != 1:
            raise SystemExit(
                f"r14 patch precondition drift for {marker!r}: old-count={count}"
            )
        text = text.replace(old, new, 1)

    replace_once_or_verify(
        "\n\n\ndef merge_lane(lane: str, branch: str) -> dict[str, Any]:\n",
        '''

LANE_G_SHARED_CONFLICTS = frozenset(
    {
        "qualification/module-execution-dossiers/NATIVE_BINDINGS.json",
        "qualification/module-execution-dossiers/test_implementation_contracts.py",
    }
)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
''',
        "LANE_G_SHARED_CONFLICTS = frozenset(",
    )
    replace_once_or_verify(
        "    lane_f_owner_conflict = False\n    if not result.passed:\n",
        "    lane_f_owner_conflict = False\n    lane_g_shared_conflict = False\n    if not result.passed:\n",
        "lane_g_shared_conflict = False",
    )
    replace_once_or_verify(
        '''        lane_f_owner_conflict = (
            lane == "F"
            and len(conflicts) == len(LANE_F_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_F_OWNER_CONFLICTS
        )
        if (
''',
        '''        lane_f_owner_conflict = (
            lane == "F"
            and len(conflicts) == len(LANE_F_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_F_OWNER_CONFLICTS
        )
        lane_g_shared_conflict = (
            lane == "G"
            and len(conflicts) == len(LANE_G_SHARED_CONFLICTS)
            and frozenset(conflicts) == LANE_G_SHARED_CONFLICTS
        )
        if (
''',
        "lane_g_shared_conflict = (",
    )
    replace_once_or_verify(
        '''            and not lane_f_owner_conflict
        ):
''',
        '''            and not lane_f_owner_conflict
            and not lane_g_shared_conflict
        ):
''',
        "and not lane_g_shared_conflict",
    )
    replace_once_or_verify(
        '''        checkout_side = (
            "--theirs"
            if lane_owner_conflict or lane_f_owner_conflict
            else "--ours"
        )
        for path in conflicts:
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
''',
        '''        for path in conflicts:
            if (
                lane_f_owner_conflict
                and path == ".github/workflows/lane-f-bootstrap.yml"
            ):
                git("rm", "--", path)
                continue
            checkout_side = (
                "--ours"
                if lane_g_shared_conflict
                else (
                    "--theirs"
                    if lane_owner_conflict or lane_f_owner_conflict
                    else "--ours"
                )
            )
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
''',
        "if lane_g_shared_conflict",
    )
    replace_once_or_verify(
        '''        elif lane_f_owner_conflict:
            resolution_class = "Lane F owner shadow qualification paths"
        else:
''',
        '''        elif lane_f_owner_conflict:
            resolution_class = "Lane F owner shadow qualification paths"
        elif lane_g_shared_conflict:
            resolution_class = "Lane G shared dossiers retained then semantically regenerated"
        else:
''',
        "Lane G shared dossiers retained then semantically regenerated",
    )
    replace_once_or_verify(
        '''            and not lane_f_owner_conflict
        ),
''',
        '''            and not lane_f_owner_conflict
            and not lane_g_shared_conflict
        ),
''',
        "and not lane_g_shared_conflict\n        ),",
    )
    replace_once_or_verify(
        '''        "autoResolvedLaneFOwnerOnly": lane_f_owner_conflict,
        "conflicts": conflicts,
''',
        '''        "autoResolvedLaneFOwnerOnly": lane_f_owner_conflict,
        "autoResolvedLaneGSharedOnly": lane_g_shared_conflict,
        "conflicts": conflicts,
''',
        "autoResolvedLaneGSharedOnly",
    )

    repair_marker = '''def repair_argument_comment_blockers() -> dict[str, Any]:
'''
    repair_function = '''def repair_lane_g_shared_artifacts() -> dict[str, Any]:
    """Regenerate Lane G's shared dossier projection without flattening A-F tests."""

    changed: list[str] = []
    native_path = ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    document = read_json(native_path)
    rows = [
        row
        for row in document.get("observations", [])
        if row.get("module") == "control.engineering"
    ]
    if len(rows) != 1:
        raise RuntimeError(
            f"expected one control.engineering native binding, observed {len(rows)}"
        )
    row = rows[0]
    desired_path = (
        "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
    )
    desired_exports = [
        "EngineeringStore",
        "WorkEnvelope",
        "WorkPackage",
        "Candidate",
        "SandboxReceipt",
        "EvidenceDecision",
        "AssimilationProposal",
        "issue_work_envelope",
        "schedule_ready_packages",
        "generate_candidate",
        "execute_candidate_sandbox",
        "verify_integration_evidence",
        "request_independent_review",
        "record_integration_decision",
        "publish_audit_projection",
        "prepare_assimilation_candidate",
    ]
    if row.get("path") != desired_path or row.get("exports") != desired_exports:
        row["path"] = desired_path
        row["exports"] = desired_exports
        write_json(native_path, document)
        changed.append(native_path.relative_to(ROOT).as_posix())

    native_tests_path = (
        ROOT
        / "qualification/module-execution-dossiers/implementation_contract_tests_native.py"
    )
    native_tests = """\"\"\"Native-source closed-world implementation contract tests.\"\"\"
import re
import unittest

import implementation_contracts as c

BASE = c.ROOT / "qualification/module-execution-dossiers"


class NativeBindingCoverageTests(unittest.TestCase):
    def test_native_binding_module_closed_world(self):
        profiles = c.read_json(BASE / "IMPLEMENTATION_PROFILES.json")
        native = c.read_json(BASE / "NATIVE_BINDINGS.json")
        self.assertEqual(native["moduleCoverage"], 40)
        self.assertFalse(native["consumerCallsitesProved"])
        self.assertFalse(native["productExecutionProved"])
        self.assertEqual(
            [row["module"] for row in native["observations"]],
            [row["module"] for row in profiles["modules"]],
        )

    def test_native_binding_blobs_and_exports_are_exact(self):
        native = c.read_json(BASE / "NATIVE_BINDINGS.json")
        for row in native["observations"]:
            source = c.ROOT / row["path"]
            data = source.read_bytes()
            self.assertEqual(c.blob(data), row["blobSha"], row["path"])
            source_text = data.decode("utf-8")
            for symbol in row["exports"]:
                self.assertRegex(
                    source_text,
                    r"\\b" + re.escape(symbol) + r"\\b",
                    row["path"] + ": " + symbol,
                )
"""
    if not native_tests_path.is_file() or native_tests_path.read_text(
        encoding="utf-8"
    ) != native_tests:
        native_tests_path.write_text(native_tests, encoding="utf-8")
        changed.append(native_tests_path.relative_to(ROOT).as_posix())

    harness_path = (
        ROOT / "qualification/module-execution-dossiers/test_implementation_contracts.py"
    )
    harness = """\"\"\"Qualification-only implementation contract test suite.\"\"\"
from implementation_contract_tests_core import *  # noqa: F403
from implementation_contract_tests_system import *  # noqa: F403
from implementation_contract_tests_native import *  # noqa: F403

if __name__ == "__main__":
    import unittest

    unittest.main()
"""
    if harness_path.read_text(encoding="utf-8") != harness:
        harness_path.write_text(harness, encoding="utf-8")
        changed.append(harness_path.relative_to(ROOT).as_posix())

    return {"changed": changed, "count": len(changed)}


def repair_argument_comment_blockers() -> dict[str, Any]:
'''
    replace_once_or_verify(
        repair_marker,
        repair_function,
        "def repair_lane_g_shared_artifacts()",
    )
    replace_once_or_verify(
        '''    generator_receipts = run_generators()
    native_before = repair_native_bindings()
''',
        '''    generator_receipts = run_generators()
    lane_g_artifact_repair = repair_lane_g_shared_artifacts()
    native_before = repair_native_bindings()
''',
        "lane_g_artifact_repair = repair_lane_g_shared_artifacts()",
    )
    replace_once_or_verify(
        '''        "generatorReceipts": generator_receipts,
        "nativeBindingBefore": native_before,
''',
        '''        "generatorReceipts": generator_receipts,
        "laneGArtifactRepair": lane_g_artifact_repair,
        "nativeBindingBefore": native_before,
''',
        '"laneGArtifactRepair": lane_g_artifact_repair',
    )

    required_cycle_safety = (
        "def workspace_dependency_graph(",
        "def dependency_cycle_path(",
        '"skippedCycleCount": len(skipped_cycles)',
    )
    for phrase in required_cycle_safety:
        if phrase not in text:
            raise SystemExit(f"cycle-safe dependency repair missing: {phrase}")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
