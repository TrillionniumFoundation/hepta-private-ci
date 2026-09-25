"""Negative evidence-parser checks; no benchmark or provider invocation."""

import argparse
import copy
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "kg_target", Path(__file__).with_name("hepta-knowledge-graph-target-measure.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    latency = {"p50": 1, "p95": 2, "p99": 3}
    return {
        "schema": module.BENCHMARK_SCHEMA,
        "hostProfileId": "host-a",
        "writes": 256,
        "querySamples": 20,
        "reopenSamples": 5,
        "mutationNs": dict(latency),
        "queryNs": dict(latency),
        "reopenNs": dict(latency),
        "contention": {
            "rounds": 10,
            "readersPerRound": 4,
            "writerNs": dict(latency),
            "readerNs": dict(latency),
            "roundNs": dict(latency),
        },
        "boundedQueryWork": {
            "returnedEdges": 1,
            "omittedEdges": 2,
            "matchingEdges": 3,
            "selectedEdgesCloned": 1,
            "relationEdgesScanned": 4,
        },
        "storage": {"databaseBytes": 4096, "walBytes": 0},
        "process": {"peakRssKiB": 1024},
    }


class TargetMeasurementTest(unittest.TestCase):
    def parse(self, receipt):
        return module.parse_receipt(module.PREFIX + json.dumps(receipt), "host-a")

    def test_valid_nextest_indented_receipt(self):
        receipt = fixture()
        self.assertEqual(
            module.parse_receipt(
                "PASS\n    " + module.PREFIX + json.dumps(receipt), "host-a"
            ),
            receipt,
        )

    def test_absent_duplicate_and_truncated_receipts_rejected(self):
        valid = module.PREFIX + json.dumps(fixture())
        for text in ("0 tests run", valid + "\n" + valid, module.PREFIX + "{"):
            with self.subTest(text=text), self.assertRaises(SystemExit):
                module.parse_receipt(text, "host-a")

    def test_nonobject_and_wrong_host_rejected(self):
        for receipt in ([], None, {**fixture(), "hostProfileId": "other"}):
            with self.subTest(receipt=receipt), self.assertRaises(SystemExit):
                self.parse(receipt)

    def test_boolean_and_missing_counts_rejected(self):
        for value in (True, False, None, -1, 0, 1.5):
            receipt = fixture()
            receipt["writes"] = value
            with self.subTest(value=value), self.assertRaises(SystemExit):
                self.parse(receipt)

    def test_reversed_percentiles_rejected(self):
        receipt = fixture()
        receipt["queryNs"]["p95"] = 100
        with self.assertRaises(SystemExit):
            self.parse(receipt)

    def test_omitted_and_clone_accounting_rejected(self):
        for field, value in (
            ("matchingEdges", 1),
            ("relationEdgesScanned", 2),
            ("selectedEdgesCloned", 3),
            ("returnedEdges", 2),
        ):
            receipt = fixture()
            receipt["boundedQueryWork"][field] = value
            with self.subTest(field=field), self.assertRaises(SystemExit):
                self.parse(receipt)

    def test_unmeasured_database_rejected(self):
        receipt = fixture()
        receipt["storage"]["databaseBytes"] = 0
        with self.assertRaises(SystemExit):
            self.parse(receipt)

    def test_workload_must_match_requested_values(self):
        args = argparse.Namespace(
            writes=256,
            query_samples=20,
            reopen_samples=5,
            contention_rounds=10,
            contention_readers=4,
        )
        receipt = self.parse(fixture())
        module.check_parameters(receipt, args)
        for key in ("writes", "querySamples", "reopenSamples"):
            wrong = copy.deepcopy(receipt)
            wrong[key] -= 1
            with self.subTest(key=key), self.assertRaises(SystemExit):
                module.check_parameters(wrong, args)
        wrong = copy.deepcopy(receipt)
        wrong["contention"]["rounds"] = 1
        with self.assertRaises(SystemExit):
            module.check_parameters(wrong, args)


if __name__ == "__main__":
    unittest.main()
