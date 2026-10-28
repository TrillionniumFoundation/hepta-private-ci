"""Real optimizer/process checks on new development facts, never frozen held data."""

from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fresh_reader import canonical, decode, digest
from fresh_reader_support import development_export, process, run_qualification, save


class FreshReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hm9-fresh-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.export = development_export()
        v6_root = Path(os.environ.get("MEMORY_CELL_FRESH_V6_ROOT", str(HERE.parents[1] / "memory-cell-v6")))
        cls.output = cls.root / "qualification"
        cls.result = run_qualification(cls.export, cls.output, v6_root.resolve(), "synthetic-development-test")
        if not cls.result["passed"]:
            raise AssertionError(f"real fresh-reader qualification failed: {cls.result.get('failure', cls.result['comparisons'])}")
        cls.rows = {row["name"]: row for row in cls.result["reads"]}

    def request(self, name):
        return decode((self.output / "readers" / name / "request.json").read_bytes())

    def test_actual_optimizer_exit_precedes_fresh_readers_without_training_imports(self):
        trainer = self.result["training_process"]
        self.assertEqual(trainer["exit_code"], 0)
        for item in self.result["training"]["artifacts"]:
            if item["variant"] == "trained":
                report = item["report"]["training"]
                self.assertGreater(report["steps"], 0)
                self.assertNotEqual(report["initial_parameters"], item["report"]["parameter_digest"])
        for row in self.rows.values():
            reader = row["read"]
            self.assertNotEqual(reader["pid"], trainer["pid"])
            self.assertGreaterEqual(row["process"]["started_monotonic_ns"], trainer["reaped_monotonic_ns"])
            self.assertFalse(reader["training_modules_loaded"])
            self.assertFalse(reader["native_runtime_executed"])
            self.assertEqual(reader["data_files_read"], [self.request(row["name"])["artifact_path"]])

    def test_trained_parameters_recall_original_values_and_sources_for_both_types(self):
        expected = {(row["record"]["kind"], row["record"]["entity"]):
                    (row["record"]["value"], [row["source_id"]]) for row in self.export["records"]}
        for representation in ("catalog", "byte"):
            for kind in ("semantic", "procedure"):
                trained = self.rows[f"{representation}-{kind}-trained"]["read"]["readouts"]
                zero = self.rows[f"{representation}-{kind}-zero"]["read"]["readouts"]
                for row in trained[:-1]:
                    self.assertIsNone(row["abstain"])
                    self.assertEqual((row["value"], row["support_ids"]), expected[kind, row["key"]])
                self.assertTrue(any(row["abstain"] is not None or row["value"] != expected[kind, row["key"]][0]
                                    for row in zero[:-1]))
                self.assertEqual((trained[-1]["value"], trained[-1]["support_ids"], trained[-1]["abstain"]),
                                 (None, [], "outside-written-support"))

    def test_catalog_removal_refuses_values_while_byte_artifact_needs_no_catalog(self):
        for kind in ("semantic", "procedure"):
            removed = self.rows[f"catalog-{kind}-catalog-removed"]
            self.assertEqual(removed["process"]["exit_code"], 2)
            self.assertEqual(removed["read"]["rejection"], "value-catalog-required")
            self.assertEqual(removed["read"]["readouts"], [])
            original = decode((self.output / "artifacts" / f"catalog-{kind}-trained.json").read_bytes())
            stripped = decode((self.output / "artifacts" / f"catalog-{kind}-catalog-removed.json").read_bytes())
            self.assertEqual(stripped, {key: value for key, value in original.items() if key != "catalog"})
            byte = decode((self.output / "artifacts" / f"byte-{kind}-trained.json").read_bytes())
            self.assertFalse({"catalog", "targets", "values", "lengths", "labels"} & set(byte))

    def test_reader_rejects_answers_in_top_level_or_query_before_opening_artifact(self):
        base = self.request("byte-semantic-trained")
        for index, request in enumerate((deepcopy(base), deepcopy(base))):
            if index == 0:
                request["targets"] = ["forbidden"]
            else:
                request["queries"][0]["expected"] = "forbidden"
            read, cost = process("read", request, self.root / f"injected-{index}")
            self.assertEqual(cost["exit_code"], 2)
            self.assertEqual(read["data_files_read"], [])
            self.assertEqual(read["readouts"], [])

    def test_parameter_support_and_artifact_tampering_fail_in_new_processes(self):
        base = self.request("byte-semantic-trained")
        changed = decode(Path(base["artifact_path"]).read_bytes())
        changed["arrays"]["input_weights"][0] += 0.5
        path = self.root / "changed-parameters.json"
        save(path, changed)
        interventions = (
            ({**base, "artifact_sha256": digest(b"different artifact")}, "artifact-digest-mismatch"),
            ({**base, "support_sha256": digest(b"different support")}, "support-digest-mismatch"),
            ({**base, "artifact_path": str(path), "artifact_sha256": digest(path.read_bytes())}, "parameter-digest-mismatch"),
        )
        for index, (request, reason) in enumerate(interventions):
            read, cost = process("read", request, self.root / f"tampered-{index}")
            self.assertEqual(cost["exit_code"], 2)
            self.assertEqual(read["rejection"], reason)
            self.assertEqual(read["readouts"], [])
            self.assertEqual(read["request_sha256"], digest(canonical(request)))


if __name__ == "__main__":
    unittest.main()
