#!/usr/bin/env python3
"""Keep native operator verification separate from honest integration work."""

import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("hepta-lane-e-closure.py")
SPEC = importlib.util.spec_from_file_location("hepta_lane_e_closure", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LaneEClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = json.loads(MODULE.MATRIX_PATH.read_text(encoding="utf-8"))
        self.operator = next(
            row
            for row in self.matrix["modules"]
            if row["module"] == "learning.operator"
        )

    def test_truthful_integration_work_does_not_fail_native_mapping(self) -> None:
        gap = (
            "The default runtime still needs the complete independent operator handoff."
        )
        self.operator["remainingRepositoryGaps"] = [gap]
        findings = MODULE.Findings()
        MODULE.verify_matrix(self.matrix, findings)
        self.assertEqual(findings.integration_work["learning.operator"], [gap])
        self.assertFalse(
            any(
                finding.code in {"repository_gap_open", "repository_gap_shape"}
                or (
                    finding.code == "operation_closed_world"
                    and "learning.operator" in finding.message
                )
                for finding in findings.items
            ),
            findings.items,
        )

    def test_missing_operator_source_still_rejects_with_integration_work(self) -> None:
        self.operator["remainingRepositoryGaps"] = ["Runtime composition remains open."]
        self.operator["operations"] = [
            operation
            for operation in self.operator["operations"]
            if operation["operation"]
            != "validate_applicability_with_signed_evidence_v2"
        ]
        findings = MODULE.Findings()
        MODULE.verify_matrix(self.matrix, findings)
        self.assertTrue(
            any(
                finding.code == "operation_closed_world"
                and "learning.operator" in finding.message
                for finding in findings.items
            )
        )

    def test_integration_work_requires_bounded_nonempty_strings(self) -> None:
        for gaps in [None, [{}], [""], ["x" * 4097], ["open"] * 129]:
            with self.subTest(gaps=gaps):
                matrix = copy.deepcopy(self.matrix)
                operator = next(
                    row
                    for row in matrix["modules"]
                    if row["module"] == "learning.operator"
                )
                operator["remainingRepositoryGaps"] = gaps
                findings = MODULE.Findings()
                MODULE.verify_matrix(matrix, findings)
                self.assertTrue(
                    any(
                        finding.code == "repository_gap_shape"
                        and "learning.operator" in finding.message
                        for finding in findings.items
                    )
                )
                self.assertNotIn("learning.operator", findings.integration_work)

    def test_payload_owner_mapping_must_resolve_actual_source(self) -> None:
        operation = next(
            item
            for item in self.operator["supplementalOperations"]
            if item["operation"] == "fit_terminal_cell_from_owner_v1"
        )
        operation["nativeSymbol"] = (
            "codex_hepta_bellman_operator::missing_owner_handoff"
        )
        findings = MODULE.Findings()
        MODULE.verify_matrix(self.matrix, findings)
        self.assertTrue(
            any(
                finding.code == "native_symbol_unresolved"
                and "missing_owner_handoff" in finding.message
                for finding in findings.items
            )
        )

    def test_legacy_product_writer_remains_an_integration_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = root / "codex-rs/hepta-agentd/src/lib.rs"
            product.parent.mkdir(parents=True)
            product.write_text(
                "use codex_hepta_learning_ledger::DurableLearningJournal;\n",
                encoding="utf-8",
            )
            with mock.patch.object(MODULE, "ROOT", root):
                findings = MODULE.Findings()
                MODULE.verify_product_writer_exclusivity(findings)
                self.assertEqual(
                    [finding.code for finding in findings.items],
                    ["legacy_learning_writer_product_bypass"],
                )
                product.write_text(
                    "use codex_hepta_learning_ledger::LedgerWriter;\n", encoding="utf-8"
                )
                repaired = MODULE.Findings()
                MODULE.verify_product_writer_exclusivity(repaired)
                self.assertEqual(repaired.items, [])

    def test_source_success_does_not_report_open_integration_complete(self) -> None:
        result = MODULE.Findings()
        result.integration_work["learning.operator"] = [
            "Runtime composition remains open."
        ]
        output = io.StringIO()
        with (
            mock.patch.object(MODULE, "verify", return_value=result),
            mock.patch.object(sys, "argv", [str(SCRIPT), "verify"]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(MODULE.main(), 0)
        receipt = json.loads(output.getvalue())
        self.assertTrue(receipt["ok"])
        self.assertFalse(receipt["repositoryIntegrationComplete"])
        self.assertEqual(receipt["remainingIntegrationWork"], result.integration_work)


if __name__ == "__main__":
    unittest.main()
