#!/usr/bin/env python3
"""Synthetic validator tests; these are not native/product execution evidence."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from hepta_kg_contract_evidence import OPERATION_PREFIX
from hepta_kg_contract_evidence import contract
from hepta_kg_contract_evidence import file_receipt
from hepta_kg_contract_evidence import parse_operation_metrics
from hepta_kg_contract_evidence import parse_release_measurement
from hepta_kg_contract_evidence import read_results
from hepta_kg_contract_evidence import require_exact_test_summary
from hepta_kg_contract_evidence import require_identity
from hepta_kg_contract_evidence import strict_object

SHA1 = "1" * 40
SHA2 = "2" * 40
SHA3 = "3" * 40
SHA4 = "4" * 40
SUMMARY = "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n"


def operation_metrics() -> dict[str, int | str]:
    return {
        "schema": "hepta.knowledge-graph-operation-metrics.v2",
        "inputCloneNs": 1,
        "buildValidateSealNs": 2,
        "generationUpdateNs": 3,
        "verifiedViewBuildNs": 4,
        "coldBoundedQueryNs": 5,
        "hotBoundedQueryTotalNs": 6,
        "unboundedReferenceQueryNs": 7,
        "publicationReceiptNs": 8,
        "iterations": 128,
        "defaultSupportWork": 100,
        "maximumSupportWork": 100,
    }


class ContractEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_operation_metrics_require_executed_v2_receipt(self) -> None:
        path = self.write(
            "operation.log",
            SUMMARY + OPERATION_PREFIX + json.dumps(operation_metrics()) + "\n",
        )
        parsed = parse_operation_metrics(path)
        self.assertEqual(parsed["generationUpdateNs"], 3)
        self.assertEqual(parsed["coldBoundedQueryNs"], 5)

    def test_operation_metrics_reject_build_only_old_or_invalid_budget(self) -> None:
        fixtures = []
        old = operation_metrics()
        old["schema"] = "hepta.knowledge-graph-operation-metrics.v1"
        fixtures.append(OPERATION_PREFIX + json.dumps(old) + "\n")
        reversed_budget = operation_metrics()
        reversed_budget["defaultSupportWork"] = 101
        fixtures.append(
            SUMMARY + OPERATION_PREFIX + json.dumps(reversed_budget) + "\n"
        )
        fixtures.append(
            "test result: ok. 0 passed; 0 failed; 1 ignored;\n"
            + OPERATION_PREFIX
            + json.dumps(operation_metrics())
            + "\n"
        )
        for index, text in enumerate(fixtures):
            with self.subTest(index=index):
                path = self.write(f"invalid-{index}.log", text)
                with self.assertRaises(SystemExit):
                    parse_operation_metrics(path)

    def test_exact_summary_rejects_skipped_multiple_and_wrong_count(self) -> None:
        valid = self.write(
            "valid.log",
            "test result: ok. 2 passed; 0 failed; 0 ignored;\n",
        )
        require_exact_test_summary(valid, passed=2)
        invalid = [
            "test result: ok. 1 passed; 0 failed; 1 ignored;\n",
            SUMMARY + SUMMARY,
            SUMMARY,
        ]
        for index, text in enumerate(invalid):
            with self.subTest(index=index):
                path = self.write(f"summary-{index}.log", text)
                with self.assertRaises(SystemExit):
                    require_exact_test_summary(path, passed=2)

    def test_identity_binds_source_base_tested_commit_and_tree(self) -> None:
        path = self.write(
            "identity.txt",
            f"source={SHA1}\nbase={SHA2}\n{SHA3}\n{SHA4}\n",
        )
        require_identity(path, SHA1, SHA2, SHA3, SHA4)
        path.write_text(path.read_text().replace(SHA4, SHA1), encoding="utf-8")
        with self.assertRaises(SystemExit):
            require_identity(path, SHA1, SHA2, SHA3, SHA4)

    def test_results_reject_duplicate_and_malformed_rows(self) -> None:
        path = self.write("results.tsv", "one\t0\ntwo\t17\n")
        self.assertEqual(read_results(path), {"one": 0, "two": 17})
        for index, text in enumerate(
            (
                "one\t0\none\t0\n",
                "one\tbad\n",
                "one\t0\textra\n",
            )
        ):
            with self.subTest(index=index):
                path = self.write(f"results-{index}.tsv", text)
                with self.assertRaises(SystemExit):
                    read_results(path)

    def test_release_measurement_retains_commit_tree_and_separate_phases(self) -> None:
        distribution = {"p50": 1, "p95": 2, "p99": 3}
        document = {
            "sourceCommit": SHA3,
            "sourceTree": SHA4,
            "hostProfileId": "hosted",
            "benchmark": {
                "mutationNs": distribution,
                "queryNs": distribution,
                "reopenNs": distribution,
                "contention": {
                    "writerNs": distribution,
                    "readerNs": distribution,
                    "roundNs": distribution,
                },
                "boundedQueryWork": {"returnedEdges": 1},
            },
        }
        path = self.write("release.json", json.dumps(document))
        parsed = parse_release_measurement(path)
        self.assertEqual(parsed["sourceCommit"], SHA3)
        self.assertEqual(parsed["sourceTree"], SHA4)
        self.assertIn("recoveryReopen", parsed["phases"])
        self.assertIn("contentionRound", parsed["phases"])

    def test_evidence_file_receipt_is_content_addressed(self) -> None:
        path = self.write("evidence.log", "bound evidence\n")
        receipt = file_receipt(path, self.root)
        self.assertEqual(receipt["path"], "evidence.log")
        self.assertEqual(receipt["bytes"], len(b"bound evidence\n"))
        self.assertEqual(len(receipt["sha256"]), 64)

    def test_contract_row_binds_symbol_test_commit_tree_environment_and_evidence(self) -> None:
        row = contract(
            "contract",
            "Symbol::method",
            ["test_name"],
            ["test.log"],
            SHA3,
            SHA4,
            "sha256:" + "5" * 64,
        )
        self.assertEqual(row["testedCommit"], SHA3)
        self.assertEqual(row["testedTree"], SHA4)
        self.assertEqual(row["state"], "scenario_executed")
        self.assertIsNone(row["openReason"])

    def test_strict_json_rejects_duplicate_keys(self) -> None:
        with self.assertRaises(ValueError):
            strict_object('{"a": 1, "a": 2}')


if __name__ == "__main__":
    unittest.main()
