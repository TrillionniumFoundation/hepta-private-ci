import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from growth_test_support import growth_setup, run_growth
from matrix_export import export_observed, read_sealed
from matrix_growth import GrowthNotAdmitted
from matrix_materials import file_sha256, freeze_config
from matrix_runtime import publish_prediction_bundle, run_bound, write_json_exclusive
from next_round_matrix import _digest
from paired_execution import audit_pair, freeze_contract, validate_contract
import test_paired_execution as paired_fixtures


class GrowthExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def bundle(self, arm, folder):
        parts = growth_setup(arm)
        bank, manifest, rows = run_growth(parts)
        manifest["predictions_complete_at_ns"] = 26
        root = self.root / folder; root.mkdir()
        seal = publish_prediction_bundle(root, bank, manifest, rows, clock=lambda: 27)
        p,c,_,_ = parts
        labels = dict(schema="hepta.stem.independent-labels.v1", seal_id=seal["seal_id"],
                      contract_id=c["contract_id"], observer_id=c["observer_id"], created_at_ns=31,
                      rows=[dict(task_id=r["task_id"], input_digest=r["input_digest"], label=i, observed_at_ns=30)
                            for i,r in enumerate(rows)])
        obs = root / "labels.json"; write_json_exclusive(obs,labels)
        exported, summary = export_observed(p,c,root,expected_seal_id=seal["seal_id"],
                                            observer_path=obs,expected_observer_sha256=file_sha256(obs))
        return parts, root, seal, exported, summary

    def test_executed_split_and_direct_seals_reach_existing_audit(self):
        parts,_,_,left,_ = self.bundle("shared_421m_sparse_direct32_no_ndu","direct")
        _,_,_,right,summary = self.bundle("shared_421m_sparse_split_no_ndu","split")
        p,c,_,_ = parts
        self.assertEqual(left["schema"],"hepta.stem.paired-run-export.v2")
        self.assertEqual((left["trainable_params"],right["trainable_params"]),(896,896))
        self.assertEqual((left["peak_trainable_params"],right["peak_trainable_params"]),(896,1344))
        self.assertEqual(left["training_protocol_sha256"],right["training_protocol_sha256"])
        self.assertTrue(summary["growth_receipt"]["split_performed"])
        self.assertGreater(right["phase_flops"]["migration"],0)
        result = audit_pair(p,c,"adaptive_split",left,right)
        self.assertEqual(result["status"],"blocked")
        self.assertIn("candidate:not_pretrained_model_execution",result["blockers"])
        self.assertIn("candidate:missing_evaluation_flops",result["blockers"])
        self.assertNotIn("unmatched_actual_peak_trainable_params",result["blockers"])
        self.assertNotIn("missing_bound_training_protocol",result["blockers"])
        self.assertFalse(result["statistical_superiority_established"])

    def test_changed_training_schedule_cannot_masquerade_as_matched_pair(self):
        parts,_,_,left,_ = self.bundle("shared_421m_sparse_direct32_no_ndu","direct")
        _,_,_,right,_ = self.bundle("shared_421m_sparse_split_no_ndu","split")
        right["training_protocol_sha256"] = "e" * 64
        self.assertIn("unmatched_training_protocol",audit_pair(parts[0],parts[1],"adaptive_split",left,right)["blockers"])
        right["training_protocol_sha256"] = True
        with self.assertRaises(ValueError): audit_pair(parts[0],parts[1],"adaptive_split",left,right)

    def test_failed_growth_retains_diagnostic_but_no_predictions_seal(self):
        from matrix_test_support import FixtureEncoder
        p,c,cfg,w = growth_setup(threshold=100.)
        work = self.root / "work.json"; write_json_exclusive(work,w)
        names = ("source_sha", "task_ids", "device_id", "observer_id", "train_cutoff_ns", "eval_start_ns", "eval_end_ns", "flops_caps", "max_peak_trainable_params")
        c = freeze_contract(p,**{k:c[k] for k in names},workload_sha256=file_sha256(work))
        cfg = freeze_config(p,c,**{k:v for k,v in cfg.items() if k not in ("schema","config_id","contract_id")})
        output = self.root / "failed"
        with patch("matrix_runtime.verify_source",return_value={}), patch("matrix_runtime.LocalHFEncoder",return_value=FixtureEncoder()):
            with self.assertRaises(GrowthNotAdmitted): run_bound(p,c,cfg,work,self.root/"unused",output)
        report = json.loads((output/"FAILED.json").read_text())
        self.assertEqual(report["growth_disposition"]["disposition"],"growth_not_triggered")
        self.assertEqual(report["expected_task_ids"],c["task_ids"])
        self.assertGreater(report["work_observation"]["phase_flops"]["train"],0)
        self.assertFalse((output/"COMMITTED.json").exists())
        with self.assertRaises(ValueError): read_sealed(output,"a"*64)

    def test_forged_growth_lineage_or_peak_fails_after_a_new_seal(self):
        parts,root,seal,_,_ = self.bundle("shared_421m_sparse_split_no_ndu","split")
        p,c,_,_ = parts
        original=json.loads((root/"execution.json").read_text())
        labels=json.loads((root/"labels.json").read_text())
        for how in ("peak","lineage","reset","schema","performed","boolean_reset","residual","groups"):
            record=copy.deepcopy(original)
            if how=="peak": record["peak_trainable_params"]=896
            if how=="lineage": record["growth_receipt"]["parent_for_child"]=[0]*32
            if how=="reset": record["growth_receipt"]["optimizer_reset_count"]=0
            if how=="schema": record["schema"]="hepta.stem.bound-execution.v1"
            if how=="performed": record["growth_receipt"]["split_performed"]=False
            if how=="boolean_reset": record["growth_receipt"]["optimizer_reset_count"]=True
            if how=="residual": record["growth_receipt"]["training_residual"]=0.
            if how=="groups": record["growth_receipt"]["source_group_count"]=1
            record["training"]["growth"]=copy.deepcopy(record["growth_receipt"])
            (root/"execution.json").write_text(json.dumps(record))
            marker={k:v for k,v in seal.items() if k!="seal_id"}
            marker["files"]={name:file_sha256(root/name) for name in marker["files"]}
            marker["seal_id"]=_digest(marker)
            (root/"COMMITTED.json").write_text(json.dumps(marker))
            labels["seal_id"]=marker["seal_id"]
            (root/"labels.json").write_text(json.dumps(labels))
            with self.subTest(how=how),self.assertRaises(ValueError):
                export_observed(p,c,root,expected_seal_id=marker["seal_id"],observer_path=root/"labels.json",
                                expected_observer_sha256=file_sha256(root/"labels.json"))


class LifecycleContractTests(unittest.TestCase):
    def setUp(self):
        # Explicit audit-only invented data from predecessor fixtures.
        old=paired_fixtures.PairedExecutionTests();old.setUp()
        self.plan,self.old,self.left,self.right=old.plan,old.contract,old.left,old.right
        names=("source_sha","workload_sha256","task_ids","device_id","observer_id","train_cutoff_ns","eval_start_ns","eval_end_ns","flops_caps")
        self.new=freeze_contract(self.plan,**{k:self.old[k] for k in names},max_peak_trainable_params=33_000_000)
        for r in (self.left,self.right):
            r.update(contract_id=self.new["contract_id"],schema="hepta.stem.paired-run-export.v2",training_protocol_sha256="c"*64)

    def audit(self):
        return audit_pair(self.plan,self.new,"adaptive_split",self.left,self.right)

    def test_common_peak_cap_permits_genuine_different_transients(self):
        self.right["peak_trainable_params"]=33_000_000
        self.assertEqual(self.audit()["blockers"],[])
        self.assertEqual(self.audit()["status"],"structurally_comparable_unattested")
        self.right["peak_trainable_params"]+=1
        self.assertIn("candidate:peak_trainable_budget_exceeded",self.audit()["blockers"])

    def test_final_capacity_still_must_match(self):
        self.right["trainable_params"]+=1
        self.right["peak_trainable_params"]+=1
        self.assertIn("unmatched_actual_trainable_params",self.audit()["blockers"])

    def test_legacy_contract_keeps_legacy_peak_equality(self):
        for r in (self.left,self.right):
            r.update(contract_id=self.old["contract_id"],schema="hepta.stem.paired-run-export.v1")
            del r["training_protocol_sha256"]
        self.right["peak_trainable_params"]+=1
        result=audit_pair(self.plan,self.old,"adaptive_split",self.left,self.right)
        self.assertIn("unmatched_actual_peak_trainable_params",result["blockers"])

    def test_cap_changes_or_omitted_new_contract_field_fail(self):
        for how in ("change","drop","boolean"):
            bad=dict(self.new)
            if how=="change": bad["max_peak_trainable_params"]+=1
            if how=="drop": del bad["max_peak_trainable_params"]
            if how=="boolean": bad["max_peak_trainable_params"]=True
            with self.subTest(how=how),self.assertRaises(ValueError): validate_contract(self.plan,bad)

    def test_contract_v2_cannot_launder_legacy_unbound_training(self):
        self.right["schema"]="hepta.stem.paired-run-export.v1"
        del self.right["training_protocol_sha256"]
        self.assertIn("missing_bound_training_protocol",self.audit()["blockers"])


if __name__=="__main__":
    unittest.main()
