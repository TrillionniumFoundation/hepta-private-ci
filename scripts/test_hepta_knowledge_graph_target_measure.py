"""Negative evidence-parser checks; no benchmark or provider invocation."""

import argparse
import copy
import importlib.util
import json
import subprocess
import tempfile
from unittest.mock import patch
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
        "currentGeneration": 256,
        "postContentionGeneration": 266,
        "logicalNodes": 4096,
        "logicalEdges": 32768,
        "revisionEntityRows": 4096,
        "revisionRelationRows": 32768,
        "compactGenerationWitnessRows": 256,
        "legacySnapshotNodeRows": 0,
        "legacySnapshotEdgeRows": 0,
        "querySamples": 20,
        "reopenSamples": 5,
        "mutationNs": {
            **latency,
            "total": 1000000,
            "throughputMilliOpsPerSecond": 256000000,
        },
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
            "validatedNodes": 4,
            "validatedEdges": 4,
            "validatedSupports": 20,
            "visibilityNodesScanned": 4,
            "visibilitySupportsInspected": 4,
            "relationSupportsInspected": 4,
            "selectedSupportsCloned": 2,
            "omittedEdges": 2,
            "matchingEdges": 3,
            "selectedEdgesCloned": 1,
            "relationEdgesScanned": 4,
        },
        "storage": {"databaseBytes": 4096, "walBytes": 0},
        "process": {
            "peakRssKiB": 1024,
            "rssKiBBefore": 512,
            "rssKiBAfter": 768,
            "linuxCpuTicksDelta": 10,
        },
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

    def test_incomplete_or_inconsistent_support_measurements_rejected(self):
        for field, value in (
            ("validatedSupports", None),
            ("selectedSupportsCloned", 0),
            ("selectedSupportsCloned", 5),
            ("relationSupportsInspected", 21),
            ("validatedEdges", 5),
            ("visibilityNodesScanned", 3),
            ("visibilitySupportsInspected", True),
        ):
            receipt = fixture()
            receipt["boundedQueryWork"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(SystemExit):
                self.parse(receipt)

    def test_incomplete_capacity_or_extra_generation_rejected(self):
        for field, value in (
            ("logicalNodes", 16),
            ("logicalEdges", 128),
            ("revisionEntityRows", None),
            ("legacySnapshotEdgeRows", 1),
            ("compactGenerationWitnessRows", 1),
            ("postContentionGeneration", 267),
        ):
            receipt = fixture()
            receipt[field] = value
            with self.subTest(field=field), self.assertRaises(SystemExit):
                self.parse(receipt)

    def test_throughput_must_match_observed_total(self):
        receipt = fixture()
        receipt["mutationNs"]["throughputMilliOpsPerSecond"] += 1
        with self.assertRaises(SystemExit):
            self.parse(receipt)

    def test_linux_process_measurements_are_complete(self):
        for field, value in (
            ("rssKiBBefore", None),
            ("rssKiBAfter", 2048),
            ("linuxCpuTicksDelta", None),
        ):
            receipt = fixture()
            receipt["process"][field] = value
            with (
                self.subTest(field=field),
                patch.object(module.platform, "system", return_value="Linux"),
                self.assertRaises(SystemExit),
            ):
                self.parse(receipt)

    def test_failed_process_cannot_publish_receipt_and_preserves_raw_log(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "measurement.log"
            args = argparse.Namespace(
                host_profile_id="host-a",
                writes=256,
                query_samples=20,
                reopen_samples=5,
                contention_readers=4,
                contention_rounds=10,
                target_dir=None,
                output=str(Path(directory) / "evidence.json"),
                raw_output=str(raw),
            )
            output = module.PREFIX + json.dumps(fixture())
            result = subprocess.CompletedProcess([], 100, stdout=output)
            with (
                patch.object(module.subprocess, "run", return_value=result) as run,
                self.assertRaises(SystemExit),
            ):
                module.run_benchmark(args)
            self.assertEqual(raw.read_text(), output)
            self.assertFalse(Path(args.output).exists())
            invocation = run.call_args.args[0]
            self.assertEqual(invocation[invocation.index("--retries") + 1], "0")
            self.assertEqual(
                invocation[invocation.index("--profile") + 1],
                "knowledge-graph-measurement",
            )


if __name__ == "__main__":
    unittest.main()
