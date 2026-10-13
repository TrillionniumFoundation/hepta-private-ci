import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_consolidation_export as consolidation_fixtures
from consolidation_training import ConsolidationRejected
from final_campaign import audit_campaign, _cost_record
from final_panels import LABEL_SCHEMA, create_registry, freeze_protocol
from matrix_materials import file_sha256, freeze_config, public_row
from matrix_runtime import run_bound, write_json_exclusive
from matrix_test_support import FixtureEncoder
from next_round_matrix import _digest
from paired_execution import freeze_contract


def build_campaign(root, *, compressed=True):
    """Actually run the prior compression fixture twice, retaining its rejection."""
    root = Path(root)
    from matrix_test_support import setup as simple_setup
    make = consolidation_fixtures.setup if compressed else simple_setup
    p, old, cfg, work = make()
    wp = root / "workload.json"; write_json_exclusive(wp, work)
    fields = ("source_sha", "task_ids", "device_id", "observer_id", "train_cutoff_ns",
              "eval_start_ns", "eval_end_ns", "flops_caps", "tolerance_ppm", "max_peak_trainable_params")
    c = freeze_contract(p, **{k: old[k] for k in fields if k in old}, workload_sha256=file_sha256(wp))
    slots = []
    arms = (("baseline", "shared_421m_sparse_direct32_no_ndu"), ("candidate", "shared_421m_sparse_split_no_ndu")) if compressed else (
        ("baseline", "shared_421m_head_no_ndu"), ("candidate", "shared_421m_sparse_fixed16_no_ndu"))
    for role, arm in arms:
        config = make(arm)[2]
        config = freeze_config(p, c, **{k: v for k, v in config.items() if k not in ("schema", "contract_id", "config_id")})
        slots.append(dict(attempt_id=role, role=role, config=config))
    protocol = freeze_protocol(p, c, work, contrast_id="adaptive_split" if compressed else "sparse_routing", slots=slots,
                               panels={"e0": "old", "e1": "new"}, registered_at_ns=12,
                               alpha=.05, max_old_accuracy_drop=.1, min_new_accuracy_gain=.01)
    create_registry(root / "registry", protocol)
    terminals = {}
    for slot in slots:
        out = root / slot["attempt_id"]
        with patch("matrix_runtime.verify_source", return_value={}), \
             patch("matrix_runtime.LocalHFEncoder", return_value=FixtureEncoder()):
            try:
                seal = run_bound(p, c, slot["config"], wp, root / "unused", out,
                                 final_registry=root / "registry", final_protocol_id=protocol["protocol_id"],
                                 attempt_id=slot["attempt_id"], clock=lambda: 25)
                terminals[slot["attempt_id"]] = {"kind": "completed", "id": seal["seal_id"]}
            except ConsolidationRejected:
                terminals[slot["attempt_id"]] = {"kind": "failed", "id": file_sha256(out / "FAILED.json")}
    assert terminals["baseline"]["kind"] == ("failed" if compressed else "completed"), "retain real outcomes"
    assert terminals["candidate"]["kind"] == "completed"
    labels = dict(schema=LABEL_SCHEMA, protocol_id=protocol["protocol_id"], contract_id=c["contract_id"],
                  observer_id=c["observer_id"], created_at_ns=31, terminals=terminals,
                  rows=[dict(task_id=r["sample_id"], input_digest=_digest(public_row(r)), label=i, observed_at_ns=30)
                        for i, r in enumerate(work["eval"])])
    write_json_exclusive(root / "labels.json", labels)
    write_json_exclusive(root / "plan.json", p); write_json_exclusive(root / "contract.json", c)
    return p, c, protocol, labels


class FinalCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.reference.cleanup)
        cls.plan, cls.contract, cls.protocol, cls.labels = build_campaign(cls.reference.name)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "campaign"
        shutil.copytree(self.reference.name, self.root)
        self.label_path = self.root / "labels.json"
        self.labels = copy.deepcopy(type(self).labels)
        self.directories = {r: str(self.root / r) for r in ("baseline", "candidate")}
        self.label_sha = file_sha256(self.label_path)

    def audit(self):
        return audit_campaign(self.plan, self.contract, self.root / "workload.json", self.root / "registry",
                              expected_protocol_id=self.protocol["protocol_id"], directories=self.directories,
                              labels_path=self.label_path, expected_labels_sha256=self.label_sha)

    def update_labels(self):
        self.label_path.write_text(json.dumps(self.labels))
        self.label_sha = file_sha256(self.label_path)

    def test_actual_compression_and_rejection_are_both_in_final_denominator(self):
        result = self.audit()
        self.assertTrue(result["denominator_complete"])
        self.assertEqual([a["terminal"]["kind"] for a in result["attempts"]], ["failed", "completed"])
        self.assertEqual(result["totals"]["baseline"]["failed_attempts"], 1)
        self.assertEqual(result["totals"]["baseline"]["task_opportunities"], 2)
        self.assertGreater(result["totals"]["baseline"]["phases"]["train"]["known_formula_work"], 0)
        self.assertIsNone(result["totals"]["baseline"]["phases"]["evaluation"]["complete_formula_work"])
        self.assertEqual(result["statistics"]["panels"]["old"]["groups"][0]["baseline"], 0)
        self.assertFalse(result["statistics"]["conditional_gate_passed"])
        self.assertFalse(result["independent_future_retention_established"])
        self.assertEqual(result["paired_audits"][0]["audit"]["blockers"], ["registered_attempt_failed"])

    def test_two_actual_completed_runs_reuse_existing_paired_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, c, protocol, labels = build_campaign(tmp, compressed=False)
            root = Path(tmp)
            result = audit_campaign(p, c, root / "workload.json", root / "registry",
                                    expected_protocol_id=protocol["protocol_id"],
                                    directories={r: str(root/r) for r in ("baseline", "candidate")},
                                    labels_path=root/"labels.json", expected_labels_sha256=file_sha256(root/"labels.json"))
            self.assertEqual([a["terminal"]["kind"] for a in result["attempts"]], ["completed", "completed"])
            check = result["paired_audits"][0]["audit"]
            self.assertEqual(check["status"], "blocked")
            self.assertIn("candidate:not_pretrained_model_execution", check["blockers"])
            self.assertIn("candidate:missing_energy_joules", check["blockers"])
            self.assertFalse(result["full_cost_qualification"])

    def test_no_accepted_only_report_after_dropping_failed_attempt(self):
        self.directories.pop("baseline")
        with self.assertRaisesRegex(ValueError, "denominator"): self.audit()

    def test_missing_failure_record_is_unresolved_not_zero(self):
        (self.root / "baseline" / "FAILED.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"): self.audit()

    def test_rehashed_wrong_failure_identity_cannot_be_reassigned(self):
        path = self.root / "baseline" / "FAILED.json"
        original = json.loads(path.read_text())
        for key, value in (("config_id", "a"*64), ("arm_id", "other"), ("source_sha", "b"*40),
                           ("contract_id", "c"*64), ("expected_task_ids", ["e0"])):
            record = {**original, key: value}; path.write_text(json.dumps(record))
            self.labels["terminals"]["baseline"]["id"] = file_sha256(path); self.update_labels()
            with self.subTest(key=key), self.assertRaises(ValueError): self.audit()

    def test_different_input_or_boolean_labels_reject(self):
        for key, value in (("input_digest", "a"*64), ("task_id", "t0"), ("label", True)):
            original = self.labels["rows"][0][key]
            self.labels["rows"][0][key] = value; self.update_labels()
            with self.subTest(key=key), self.assertRaises(ValueError): self.audit()
            self.labels["rows"][0][key] = original

    def test_all_attempts_must_finish_before_common_labels(self):
        self.labels["rows"][0]["observed_at_ns"] = 24; self.update_labels()
        with self.assertRaises(ValueError): self.audit()

    def test_same_registry_slot_cannot_retry_even_after_real_rejection(self):
        config = self.protocol["slots"][0]["config"]
        with patch("matrix_runtime.verify_source", return_value={}), \
             patch("matrix_runtime.LocalHFEncoder") as loader:
            with self.assertRaises(FileExistsError):
                run_bound(self.plan, self.contract, config, self.root / "workload.json", self.root / "unused",
                          self.root / "retry", final_registry=self.root / "registry",
                          final_protocol_id=self.protocol["protocol_id"], attempt_id="baseline", clock=lambda: 25)
            loader.assert_not_called()

    def test_altered_claim_or_common_receipt_identity_reject(self):
        claim = self.root / "registry" / "claims" / "candidate.json"
        record = json.loads(claim.read_text()); record["attempt_id"] = "baseline"
        claim.write_text(json.dumps(record))
        with self.assertRaises(ValueError): self.audit()

    def test_label_bytes_are_pinned_not_just_semantic_values(self):
        self.label_path.write_text(self.label_path.read_text() + " ")
        with self.assertRaises(ValueError): self.audit()

    def test_unknown_unregistered_attempt_cannot_be_added(self):
        self.directories["retry"] = self.directories["candidate"]
        with self.assertRaises(ValueError): self.audit()

    def test_candidate_bytes_changed_after_seal_reject(self):
        path = self.root / "candidate" / "bank.safetensors"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ValueError): self.audit()

    def test_final_label_changes_do_not_trigger_any_training(self):
        import matrix_bank
        with patch.object(matrix_bank, "train_bank", side_effect=AssertionError("final evaluation cannot train")):
            first = self.audit()
            self.labels["rows"][0]["label"] = 1 - self.labels["rows"][0]["label"]; self.update_labels()
            second = self.audit()
        self.assertEqual(first["attempts"], second["attempts"])
        self.assertNotEqual(first["labels_sha256"], second["labels_sha256"])
        self.assertFalse(second["final_model_selected"])

    def test_cli_report_and_exclusive_repeated_output(self):
        paths = self.root / "directories.json"; write_json_exclusive(paths, self.directories)
        target = self.root / "report"
        cmd = [sys.executable, str(Path(__file__).with_name("final_campaign.py")),
               "--plan", str(self.root / "plan.json"), "--contract", str(self.root / "contract.json"),
               "--workload", str(self.root / "workload.json"), "--registry", str(self.root / "registry"),
               "--protocol-id", self.protocol["protocol_id"], "--directories", str(paths),
               "--labels", str(self.label_path), "--labels-sha256", self.label_sha, "--output", str(target)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = (target / "final-report.json").read_bytes()
        self.assertNotEqual(subprocess.run(cmd, capture_output=True, timeout=20).returncode, 0)
        self.assertEqual((target / "final-report.json").read_bytes(), before)

    def test_partial_unknown_counter_never_becomes_complete_zero(self):
        failure = json.loads((self.root / "baseline" / "FAILED.json").read_text())
        record = _cost_record(failure)
        self.assertGreater(record["phases"]["train"]["known_formula_work"], 0)
        self.assertIsNone(record["phases"]["evaluation"]["complete_count"])
        self.assertIsNone(_cost_record({})["phases"]["train"]["complete_count"])
        self.assertIsNone(record["energy_joules"])


if __name__ == "__main__":
    unittest.main()
