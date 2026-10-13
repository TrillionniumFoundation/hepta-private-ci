import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from matrix_export import export_observed, read_sealed
from matrix_materials import file_sha256, freeze_config
from matrix_runtime import execute, publish_prediction_bundle, write_json_exclusive
from matrix_test_support import FixtureEncoder, setup
from next_round_matrix import _digest
from paired_execution import audit_pair


class MatrixExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan, self.contract, self.cfg, self.work = setup("shared_421m_head_no_ndu")
        self.bundle, self.seal, self.rows = self.build("dense", self.cfg, fail="e1")
        self.observer = self.labels(self.seal, self.rows)
        self.obs_path = self.root / "labels.json"
        self.write_observer()

    def build(self, name, cfg, fail=None):
        bank, execution, rows = execute(self.plan, self.contract, cfg, self.work,
                                        FixtureEncoder(fail_task=fail), clock=lambda: 25)
        execution["predictions_complete_at_ns"] = 26
        directory = self.root / name
        directory.mkdir()
        seal = publish_prediction_bundle(directory, bank, execution, rows, clock=lambda: 27)
        return directory, seal, rows

    def labels(self, seal, rows):
        return dict(schema="hepta.stem.independent-labels.v1", seal_id=seal["seal_id"],
                    contract_id=self.contract["contract_id"], observer_id=self.contract["observer_id"],
                    created_at_ns=31, rows=[dict(task_id=r["task_id"], input_digest=r["input_digest"],
                                                label=i, observed_at_ns=30) for i,r in enumerate(rows)])

    def write_observer(self):
        self.obs_path.write_text(json.dumps(self.observer))
        self.obs_sha = file_sha256(self.obs_path)

    def export(self):
        return export_observed(self.plan, self.contract, self.bundle,
                               expected_seal_id=self.seal["seal_id"], observer_path=self.obs_path,
                               expected_observer_sha256=self.obs_sha)

    def test_blind_execution_seal_observer_join_and_paired_audit(self):
        left, summary = self.export()
        self.assertEqual(len(left["requests"]), 2)
        self.assertEqual(left["requests"][1]["outcome"], 0)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["failed_or_unknown"], 1)
        self.assertGreaterEqual(summary["failure_penalized_brier"], 1.)
        self.assertFalse(summary["statistical_superiority_established"])
        _, _, cfg, _ = setup("shared_421m_sparse_fixed16_no_ndu")
        directory, seal, rows = self.build("sparse", cfg)
        observation = self.root / "sparse-labels.json"
        write_json_exclusive(observation, self.labels(seal, rows))
        right, _ = export_observed(self.plan, self.contract, directory,
                                  expected_seal_id=seal["seal_id"], observer_path=observation,
                                  expected_observer_sha256=file_sha256(observation))
        report = audit_pair(self.plan, self.contract, "sparse_routing", left, right)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("baseline:not_pretrained_model_execution", report["blockers"])
        self.assertIn("candidate:missing_inference_flops", report["blockers"])
        self.assertNotIn("unmatched_actual_trainable_params", report["blockers"])
        self.assertEqual(left["trainable_params"], right["trainable_params"])
        self.assertEqual(left["trainable_params"], 672)

    def test_prediction_weight_and_manifest_changes_reject(self):
        for name in ("execution.json", "predictions.json", "bank.safetensors"):
            target = self.bundle / name
            original = target.read_bytes()
            target.write_bytes(original + b" ")
            with self.subTest(name=name), self.assertRaises(ValueError): self.export()
            target.write_bytes(original)

    def test_rehashing_mutated_seal_does_not_change_retained_reference(self):
        marker = self.bundle / "COMMITTED.json"
        seal = json.loads(marker.read_text()); seal["sealed_at_ns"] += 1
        seal.pop("seal_id"); seal["seal_id"] = _digest(seal)
        marker.write_text(json.dumps(seal))
        with self.assertRaises(ValueError): self.export()

    def test_outcomes_before_seal_or_wrong_observer_reject(self):
        for key, value in (("observer_id", "self"), ("created_at_ns", 26),
                           ("seal_id", "a"*64), ("contract_id", "f"*64)):
            old = self.observer[key]; self.observer[key] = value; self.write_observer()
            with self.subTest(key=key), self.assertRaises(ValueError): self.export()
            self.observer[key] = old
        self.observer["rows"][0]["observed_at_ns"] = 26
        self.write_observer()
        with self.assertRaises(ValueError): self.export()

    def test_source_input_binding_and_denominator_reject(self):
        original = copy.deepcopy(self.observer)
        for how in ("drop", "reorder", "input", "label"):
            self.observer = copy.deepcopy(original)
            if how == "drop": self.observer["rows"].pop()
            if how == "reorder": self.observer["rows"].reverse()
            if how == "input": self.observer["rows"][0]["input_digest"] = "e"*64
            if how == "label": self.observer["rows"][0]["label"] = True
            self.write_observer()
            with self.subTest(how=how), self.assertRaises(ValueError): self.export()

    def test_observer_bytes_pinned_independently(self):
        self.obs_path.write_text(self.obs_path.read_text() + " ")
        with self.assertRaises(ValueError): self.export()

    def test_failed_partial_and_symlink_bundles_reject(self):
        (self.bundle / "FAILED.json").write_text('{}')
        with self.assertRaises(ValueError): self.export()
        (self.bundle / "FAILED.json").unlink()
        original = (self.bundle / "predictions.json").read_bytes()
        (self.bundle / "predictions.json").unlink()
        with self.assertRaises(ValueError): self.export()
        outside = self.root / "outside.json"; outside.write_bytes(original)
        (self.bundle / "predictions.json").symlink_to(outside)
        with self.assertRaises(ValueError): self.export()

    def test_cli_export_round_trip_and_exclusive_output(self):
        plan_file, contract_file = self.root / "plan.json", self.root / "contract.json"
        write_json_exclusive(plan_file, self.plan); write_json_exclusive(contract_file, self.contract)
        output = self.root / "export"
        cmd = [sys.executable, str(Path(__file__).with_name("matrix_export.py")),
               "--plan", str(plan_file), "--contract", str(contract_file),
               "--run-dir", str(self.bundle), "--seal-id", self.seal["seal_id"],
               "--observer", str(self.obs_path), "--observer-sha256", self.obs_sha,
               "--output", str(output)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = (output / "paired-run.json").read_bytes()
        self.assertNotEqual(subprocess.run(cmd, capture_output=True, timeout=10).returncode, 0)
        self.assertEqual(before, (output / "paired-run.json").read_bytes())
        self.assertTrue((output / "COMMITTED.json").is_file())


if __name__ == "__main__":
    unittest.main()
