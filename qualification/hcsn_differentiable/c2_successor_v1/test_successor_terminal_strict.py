"""Adversarial real successor terminal-result ingestion; no C2 training is launched."""
import json
from pathlib import Path
import tempfile
import unittest

from c2_controller import terminal_result_gate
from c2_io import identity


class StrictTerminalJSONTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.parent = {
            "name": "hcsn-s101-lr0.001",
            "seed": 101,
            "learning_rate": 0.001,
        }
        self.parent_dir = self.root / "parents" / self.parent["name"]
        self.parent_dir.mkdir(parents=True)
        self.parent_path = self.parent_dir / "result.json"
        self.parent_path.write_text(json.dumps({"model_configuration": {"width": 8}}))
        self.parent["result_sha256"] = identity(self.parent_path)["sha256"]
        self.contract = {"parent_campaign": str(self.parent_dir.parent)}
        self.result_path = self.root / "new" / "result.json"
        self.result_path.parent.mkdir()
        self.row = {"returncode": 2, "hard_timeout_sent": False}
        self.write_valid()

    def write_valid(self):
        parent_model = json.loads(self.parent_path.read_text())["model_configuration"]
        report = {
            "schema": "hcsn-c2-soft-wall-continuation-v1",
            "production_execution": True,
            "confirmation_access": False,
            "arm": "hcsn",
            "seed": self.parent["seed"],
            "learning_rate": self.parent["learning_rate"],
            "parent": str(self.parent_dir),
            "parent_outer": self.parent,
            "parent_report": identity(self.parent_path),
            "model_configuration": parent_model,
            "status": "failed",
            "training_adequacy_established": False,
        }
        self.result_path.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")))

    def check(self):
        return terminal_result_gate(self.row, self.result_path, self.parent, self.contract)

    def assert_rejected(self):
        row = self.check()
        self.assertFalse(row["terminal_evidence_complete"], row)
        self.assertEqual(row["status"], "failed_terminal_evidence")

    def test_valid_failure_is_still_a_terminal_report(self):
        row = self.check()
        self.assertTrue(row["terminal_evidence_complete"], row)
        self.assertEqual(row["status"], "failed")
        self.assertFalse(row["adequate"])

    def test_duplicate_result_field_rejected_even_when_hash_is_current(self):
        raw = self.result_path.read_text()
        self.result_path.write_text(raw.replace('"status":"failed"',
            '"status":"completed_development","status":"failed"'))
        self.assert_rejected()

    def test_nested_duplicate_result_field_rejected(self):
        raw = self.result_path.read_text()
        self.result_path.write_text(raw.replace('"model_configuration":{"width":8}',
            '"model_configuration":{"width":8,"width":8}'))
        self.assert_rejected()

    def test_result_nan_rejected_even_when_extra(self):
        raw = self.result_path.read_text()
        self.result_path.write_text(raw[:-1] + ',"unused":NaN}')
        self.assert_rejected()

    def test_result_overflow_number_rejected(self):
        raw = self.result_path.read_text()
        self.result_path.write_text(raw[:-1] + ',"unused":1e999}')
        self.assert_rejected()

    def test_duplicate_frozen_parent_field_rejected(self):
        self.parent_path.write_text(
            '{"model_configuration":{"width":8},"model_configuration":{"width":8}}')
        self.parent["result_sha256"] = identity(self.parent_path)["sha256"]
        self.write_valid()
        self.assert_rejected()

    def test_parent_nan_rejected_even_with_matching_parent_sha(self):
        self.parent_path.write_text('{"model_configuration":{"width":8},"ignored":NaN}')
        self.parent["result_sha256"] = identity(self.parent_path)["sha256"]
        self.write_valid()
        self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
