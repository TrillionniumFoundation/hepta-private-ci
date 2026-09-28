from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta_kg_contract_evidence.py")
SPEC = importlib.util.spec_from_file_location("hepta_kg_contract_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeliveryEvidenceTests(unittest.TestCase):
    def test_strict_object_rejects_duplicate_keys(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.strict_object('{"a":1,"a":2}')

    def test_result_inventory_rejects_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.tsv"
            path.write_text("kg-kernel\t0\nkg-kernel\t0\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.read_results(path)

    def test_operation_metrics_require_positive_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operation-metrics.log"
            payload = {
                "schema": "hepta.knowledge-graph-operation-metrics.v1",
                "inputCloneNs": 1,
                "buildValidateSealNs": 2,
                "verifiedViewBuildNs": 3,
                "hotQueryTotalNs": 4,
                "publicationReceiptNs": 5,
                "iterations": 128,
            }
            path.write_text(
                MODULE.OPERATION_PREFIX + json.dumps(payload) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(MODULE.parse_operation_metrics(path), payload)


if __name__ == "__main__":
    unittest.main()
