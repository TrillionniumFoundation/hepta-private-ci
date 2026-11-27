import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_retention_training as fixtures
from growth_test_support import run_growth
from matrix_export import export_observed, read_sealed
from matrix_materials import file_sha256, freeze_config
from matrix_runtime import publish_prediction_bundle, run_bound, write_json_exclusive
from matrix_test_support import FixtureEncoder
from next_round_matrix import _digest
from paired_execution import audit_pair, freeze_contract
from retention_training import RetentionRejected


class RetentionExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self, name, arm, *, temperature=None):
        parts = fixtures.retained_setup(arm)
        if temperature is not None:
            p, c, cfg, work = parts
            values = {k: v for k, v in cfg.items() if k not in ("schema", "contract_id", "config_id")}
            values["retention_policy"]["temperature"] = temperature
            parts = p, c, freeze_config(p, c, **values), work
        bank, m, rows = run_growth(parts); m["predictions_complete_at_ns"] = 26
        directory = self.root / name; directory.mkdir()
        seal = publish_prediction_bundle(directory, bank, m, rows, clock=lambda: 27)
        observer = {"schema": "hepta.stem.independent-labels.v1", "seal_id": seal["seal_id"],
                    "contract_id": parts[1]["contract_id"], "observer_id": parts[1]["observer_id"],
                    "created_at_ns": 31, "rows": [dict(task_id=r["task_id"], input_digest=r["input_digest"],
                                                       label=i, observed_at_ns=30) for i, r in enumerate(rows)]}
        write_json_exclusive(directory / "labels.json", observer)
        return parts, m, directory, seal

    def export(self, parts, directory, seal):
        return export_observed(parts[0], parts[1], directory, expected_seal_id=seal["seal_id"],
                               observer_path=directory / "labels.json", expected_observer_sha256=file_sha256(directory / "labels.json"))

    def reseal(self, directory, m, seal):
        (directory / "execution.json").write_text(json.dumps(m))
        marker = {k: v for k, v in seal.items() if k != "seal_id"}
        marker["files"] = {n: file_sha256(directory / n) for n in marker["files"]}
        marker["seal_id"] = _digest(marker)
        (directory / "COMMITTED.json").write_text(json.dumps(marker))
        labels = json.loads((directory / "labels.json").read_text()); labels["seal_id"] = marker["seal_id"]
        (directory / "labels.json").write_text(json.dumps(labels))
        return marker

    def test_execute_seal_observe_pair_preserves_retention_and_actual_work(self):
        a, am, ad, aseal = self.bundle("direct", "shared_421m_sparse_direct32_no_ndu")
        b, bm, bd, bseal = self.bundle("split", "shared_421m_sparse_split_no_ndu")
        left, ls = self.export(a, ad, aseal); right, rs = self.export(b, bd, bseal)
        self.assertEqual(left["training_protocol_sha256"], right["training_protocol_sha256"])
        self.assertEqual([r["trainable_params"] for r in (left, right)], [896, 896])
        self.assertEqual([r["peak_trainable_params"] for r in (left, right)], [896, 1344])
        self.assertTrue(rs["retention_receipt"]["passed"])
        self.assertFalse(rs["retention_established"])
        report = audit_pair(a[0], a[1], "adaptive_split", left, right)
        self.assertNotIn("unmatched_training_protocol", report["blockers"])
        self.assertIn("candidate:missing_evaluation_flops", report["blockers"])
        self.assertIn("candidate:not_pretrained_model_execution", report["blockers"])
        self.assertFalse(report["production_authorized"])

    def test_rehashed_forged_retention_and_auxiliary_counts_are_rejected(self):
        parts, original, directory, seal = self.bundle("split", "shared_421m_sparse_split_no_ndu")
        for mutation in ("decision", "teacher", "future", "group", "work", "probe", "missing"):
            m = copy.deepcopy(original); record = m["retention_receipt"]
            if mutation == "decision": record["passed"] = False
            if mutation == "teacher": record["reference_parameter_sha256"] = "invalid"
            if mutation == "future": record["independent_future_gain_established"] = True
            if mutation == "group": record["groups"].pop()
            if mutation == "work": m["training"]["retained_specialization"]["reference_bank_rows"] = 0
            if mutation == "probe": m["growth_receipt"]["residual_probe_examples"] += 1
            if mutation == "missing": m.pop("retention_receipt")
            m["training"]["retention"] = copy.deepcopy(m.get("retention_receipt"))
            m["training"]["growth"] = copy.deepcopy(m["growth_receipt"])
            newseal = self.reseal(directory, m, seal)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.export(parts, directory, newseal)

    def test_distinct_retention_protocols_cannot_be_claimed_as_matched(self):
        a, am, ad, aseal = self.bundle("direct", "shared_421m_sparse_direct32_no_ndu")
        b, bm, bd, bseal = self.bundle("split", "shared_421m_sparse_split_no_ndu", temperature=3.)
        left, _ = self.export(a, ad, aseal); right, _ = self.export(b, bd, bseal)
        self.assertNotEqual(left["training_protocol_sha256"], right["training_protocol_sha256"])
        report = audit_pair(a[0], a[1], "adaptive_split", left, right)
        self.assertIn("unmatched_training_protocol", report["blockers"])

    def test_internal_gate_failure_cannot_publish_success(self):
        p, c, cfg, work = fixtures.retained_setup()
        workload = self.root / "work.json"; write_json_exclusive(workload, work)
        names = ("source_sha", "task_ids", "device_id", "observer_id", "train_cutoff_ns", "eval_start_ns",
                 "eval_end_ns", "flops_caps", "max_peak_trainable_params")
        c = freeze_contract(p, **{k: c[k] for k in names}, workload_sha256=file_sha256(workload))
        cfg = freeze_config(p, c, **{k: v for k, v in cfg.items() if k not in ("schema", "contract_id", "config_id")})
        directory = self.root / "failed"
        # Real training/evaluation executes; force the internal decision to refuse
        # to test publication fencing, separately from the actual-regression unit test.
        with patch("matrix_runtime.verify_source", return_value={}), \
             patch("matrix_runtime.LocalHFEncoder", return_value=FixtureEncoder()), \
             patch("retention_training.gate_passes", return_value=False):
            with self.assertRaises(RetentionRejected): run_bound(p, c, cfg, workload, self.root / "unused", directory)
        failure = json.loads((directory / "FAILED.json").read_text())
        self.assertEqual(failure["expected_task_ids"], c["task_ids"])
        self.assertFalse(failure["retention_disposition"]["passed"])
        self.assertGreater(failure["work_observation"]["phase_flops"]["migration"], 0)
        self.assertFalse((directory / "COMMITTED.json").exists())
        with self.assertRaises(ValueError): read_sealed(directory, "a" * 64)

    def test_invalid_partitions_reject_before_weight_loading(self):
        p, c, cfg, work = fixtures.retained_setup()
        work["train"][4]["state"] = work["train"][0]["state"]
        workload = self.root / "work.json"; write_json_exclusive(workload, work)
        names = ("source_sha", "task_ids", "device_id", "observer_id", "train_cutoff_ns", "eval_start_ns",
                 "eval_end_ns", "flops_caps", "max_peak_trainable_params")
        c = freeze_contract(p, **{k: c[k] for k in names}, workload_sha256=file_sha256(workload))
        cfg = freeze_config(p, c, **{k: v for k, v in cfg.items() if k not in ("schema", "contract_id", "config_id")})
        with patch("matrix_runtime.LocalHFEncoder") as loader:
            with self.assertRaises(ValueError): run_bound(p, c, cfg, workload, self.root / "unused", self.root / "out")
        loader.assert_not_called()

    def test_strict_meter_and_observe_training_remain_identical(self):
        parts = fixtures.retained_setup(); bank, m, rows = run_growth(parts)
        p, c, cfg, work = copy.deepcopy(parts)
        args = {k: v for k, v in cfg.items() if k not in ("schema", "contract_id", "config_id")}
        args["measurement_policy"]["mode"] = "observe"
        cfg = freeze_config(p, c, **args)
        bank2, m2, rows2 = run_growth((p, c, cfg, work))
        self.assertEqual(m["trained_bank_sha256"], m2["trained_bank_sha256"])
        self.assertEqual([r["logits"] for r in rows], [r["logits"] for r in rows2])
        self.assertEqual(m["retention_receipt"], m2["retention_receipt"])

    def test_source_binding_detects_modified_retention_implementation(self):
        import shutil
        import subprocess
        import matrix_runtime
        local = self.root / "source"; local.mkdir()
        folder = local / "qualification" / "stem-cell-v1"; folder.mkdir(parents=True)
        for name in matrix_runtime.SOURCE_FILES:
            shutil.copyfile(Path(__file__).with_name(name), folder / name)
        commands = (["git", "init", "-q"], ["git", "add", "."],
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"])
        for command in commands:
            subprocess.run(command, cwd=local, check=True, capture_output=True)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=local, text=True).strip()
        with patch.object(matrix_runtime, "__file__", str(folder / "matrix_runtime.py")):
            before = matrix_runtime.verify_source(sha)
            self.assertIn("qualification/stem-cell-v1/retention_training.py", before)
            with (folder / "retention_training.py").open("a") as stream: stream.write("\n# changed\n")
            with self.assertRaisesRegex(ValueError, "retention_training"):
                matrix_runtime.verify_source(sha)

    def test_legacy_protocol_hash_is_not_redefined_by_absent_retention(self):
        import test_family_routing as family
        parts = family.family_setup(); bank, m, rows = run_growth(parts)
        m["predictions_complete_at_ns"] = 26; root = self.root / "old"; root.mkdir()
        seal = publish_prediction_bundle(root, bank, m, rows, clock=lambda: 27)
        observation = {"schema": "hepta.stem.independent-labels.v1", "seal_id": seal["seal_id"],
                       "contract_id": parts[1]["contract_id"], "observer_id": parts[1]["observer_id"],
                       "created_at_ns": 31, "rows": [dict(task_id=r["task_id"], input_digest=r["input_digest"],
                                                          label=i, observed_at_ns=30) for i, r in enumerate(rows)]}
        write_json_exclusive(root / "labels.json", observation)
        export, summary = self.export(parts, root, seal)
        cfg = parts[2]
        original = {k: cfg.get(k) for k in ("growth_policy", "train_steps", "batch_size", "width_units",
                    "context_tokens", "snapshot_sha256", "encoder_profile", "measurement_policy")}
        original.update(seed=parts[0]["seed"], workload_sha256=parts[1]["workload_sha256"])
        self.assertEqual(export["training_protocol_sha256"], _digest(original))
        self.assertNotIn("retention_receipt", summary)


if __name__ == "__main__":
    unittest.main()
