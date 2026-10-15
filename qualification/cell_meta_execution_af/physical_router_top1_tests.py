"""Native FP32 Top-1 dispatch plus independent replay and adversarial controls.

Fixtures use explicitly synthetic source rows: no pretrained or future-task claim.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qualification.cell_meta_execution_af import physical_router_trial as trial
from qualification.cell_meta_execution_af import physical_router_audit as original
from qualification.cell_meta_execution_af import physical_router_top1 as top
from qualification.cell_meta_execution_af import physical_router_top1_review as reviewer


class Top1PhysicalRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stable = trial.synthetic_panel(seed=41, rule="stable", rows=40)
        cls.conditional = trial.synthetic_panel(seed=41, rule="conditional", rows=40)
        cls.stable_original = trial.run(cls.stable, steps=8)
        cls.conditional_original = trial.run(cls.conditional, steps=8)
        cls.stable_result = top.create_report(cls.stable, cls.stable_original)
        cls.conditional_result = top.create_report(cls.conditional, cls.conditional_original)

    def test_full_actual_cpu_roundtrip_with_independent_stdlib(self):
        report = reviewer.replay(self.conditional, self.conditional_original, self.conditional_result)
        self.assertEqual(report["outcome"], "NUMERIC_TOP1_REPLAY_NO_AUTHORITY")
        self.assertFalse(report["actual_cpu_execution_independently_attested"])

    def test_stable_no_split_replay_and_production_denial(self):
        report = reviewer.replay(self.stable, self.stable_original, self.stable_result)
        self.assertEqual(report["contrasts"][3]["soft_original_eval_head_rows"], 160)
        self.assertEqual(report["authority_posture"], "DENY_ALL")
        self.assertFalse(report["production_selection_authorized"])

    def test_every_active_row_gets_exactly_one_head_matmul(self):
        for x in self.conditional_result["results"]:
            self.assertEqual(x["metrics"]["executed_head_rows"], 160)
            self.assertEqual(x["metrics"]["head_0_rows"]+x["metrics"]["head_1_rows"], 160)
        self.assertTrue(self.conditional_result["results"][-1]["split_proposed"])

    def test_soft_mixture_remains_more_expensive_in_head_rows(self):
        report = reviewer.replay(self.conditional, self.conditional_original, self.conditional_result)
        contrasts = {x["arm"]: x for x in report["contrasts"]}
        self.assertEqual(contrasts["fixed_router"]["soft_original_eval_head_rows"], 320)
        self.assertEqual(contrasts["fixed_router"]["top1_executed_head_rows"], 160)
        self.assertFalse(report["compute_matched_training"])

    def test_unsplit_cell_preserves_soft_predictions_and_skips_router(self):
        for original_report, top_report in ((self.stable_original, self.stable_result),
                                            (self.conditional_original, self.conditional_result)):
            unsplit = top_report["results"][0]
            source = original_report["results"][0]["predictions"]
            self.assertEqual(unsplit["metrics"]["router_rows"], 0)
            self.assertEqual(unsplit["metrics"]["head_1_rows"], 0)
            for part in trial.EVAL_PARTITIONS:
                self.assertEqual([x["selected_head"] for x in unsplit["top1_predictions"][part]],
                                 [0]*len(source[part]))
                for x, y in zip(source[part], unsplit["top1_predictions"][part], strict=True):
                    self.assertAlmostEqual(x["probability"], y["probability"], places=6)

    def test_fixed_router_hard_and_soft_are_same_model_decision(self):
        for old, new in ((self.stable_original, self.stable_result),
                         (self.conditional_original, self.conditional_result)):
            for part in trial.EVAL_PARTITIONS:
                a=old["results"][1]["predictions"][part]
                b=new["results"][1]["top1_predictions"][part]
                self.assertEqual(len(a),len(b))
                self.assertTrue(all(abs(x["probability"]-y["probability"]) < 3e-6
                                    for x,y in zip(a,b,strict=True)))
            self.assertEqual(new["results"][1]["metrics"]["router_rows"], 0)

    def test_learned_route_has_actual_gating_work(self):
        rows = self.conditional_result["results"][2]
        self.assertEqual(rows["metrics"]["router_rows"], 160)
        self.assertEqual(rows["metrics"]["executed_head_rows"], 160)

    def test_numerical_negative_gain_is_not_hidden(self):
        result = reviewer.replay(self.conditional, self.conditional_original, self.conditional_result)
        entry = result["contrasts"][2]["retrospective_brier_delta_top1_minus_soft"]
        self.assertIn("future_1", entry)
        self.assertTrue(math.isfinite(entry["future_1"]))
        # Toy negative or positive deltas do not authorize structural changes.
        self.assertFalse(result["production_selection_authorized"])

    def test_no_retraining_and_selected_weight_hash_unchanged(self):
        for old,new in zip(self.conditional_original["results"],
                           self.conditional_result["results"],strict=True):
            self.assertEqual(old["weights_sha256"],new["weights_sha256"])
        self.assertFalse(self.conditional_result["training_weights_updated"])

    def test_repeat_dispatch_same_output_bytes_excluding_performance_meter(self):
        clone = top.create_report(self.stable,self.stable_original)
        for a,b in zip(self.stable_result["results"],clone["results"],strict=True):
            self.assertEqual(a["top1_predictions"],b["top1_predictions"])
            self.assertEqual(a["top1_prediction_sha256"],b["top1_prediction_sha256"])

    def test_wrong_expert_selection_rejected_even_if_seal_rehashed(self):
        data=copy.deepcopy(self.conditional_result)
        target=data["results"][3]
        target["top1_predictions"]["future_1"][0]["selected_head"] ^= 1
        target["top1_prediction_sha256"]=original.digest(target["top1_predictions"])
        with self.assertRaisesRegex(reviewer.Top1AuditError,"selection"):
            reviewer.replay(self.conditional,self.conditional_original,data)

    def test_fabricated_top1_probability_rejected_even_if_rehashed(self):
        data=copy.deepcopy(self.conditional_result)
        target=data["results"][2]
        target["top1_predictions"]["future_1"][0]["probability"]=0.9
        target["top1_prediction_sha256"]=original.digest(target["top1_predictions"])
        with self.assertRaisesRegex(reviewer.Top1AuditError,"logits"):
            reviewer.replay(self.conditional,self.conditional_original,data)

    def test_swapped_row_identity_rejected(self):
        data=copy.deepcopy(self.conditional_result)
        x=data["results"][2]
        a=x["top1_predictions"]["future_1"]
        a[0],a[1]=a[1],a[0]
        x["top1_prediction_sha256"]=original.digest(x["top1_predictions"])
        with self.assertRaises(reviewer.Top1AuditError):
            reviewer.replay(self.conditional,self.conditional_original,data)

    def test_forged_extra_head_rows_rejected(self):
        data=copy.deepcopy(self.conditional_result)
        data["results"][3]["metrics"]["executed_head_rows"]=320
        with self.assertRaisesRegex(reviewer.Top1AuditError,"resource"):
            reviewer.replay(self.conditional,self.conditional_original,data)

    def test_forged_head_split_count_rejected(self):
        data=copy.deepcopy(self.conditional_result)
        data["results"][3]["metrics"]["head_1_rows"] += 1
        with self.assertRaises(reviewer.Top1AuditError):
            reviewer.replay(self.conditional,self.conditional_original,data)

    def test_forged_backend_batch_count_rejected(self):
        data=copy.deepcopy(self.conditional_result)
        data["results"][1]["metrics"]["head_batch_matmuls"] += 1
        with self.assertRaises(reviewer.Top1AuditError):
            reviewer.replay(self.conditional,self.conditional_original,data)

    def test_hidden_router_cost_rejected(self):
        data=copy.deepcopy(self.conditional_result)
        data["results"][2]["metrics"]["router_rows"]=0
        with self.assertRaises(reviewer.Top1AuditError):
            reviewer.replay(self.conditional,self.conditional_original,data)

    def test_prior_weight_tamper_rejected_before_top1(self):
        bad=copy.deepcopy(self.conditional_original)
        bad["results"][2]["weights_fp32"]["heads"]["data_le_hex"] = "00"*40
        with self.assertRaises(original.AuditError):
            reviewer.replay(self.conditional,bad,self.conditional_result)

    def test_forged_original_soft_prediction_rejected(self):
        bad=copy.deepcopy(self.conditional_original)
        bad["results"][3]["predictions"]["future_2"][0]["probability"] = 0.5
        bad["results"][3]["prediction_sha256"] = original.digest(bad["results"][3]["predictions"])
        with self.assertRaises(original.AuditError):
            reviewer.replay(self.conditional,bad,self.conditional_result)

    def test_wrong_source_panel_or_training_lineage_rejected(self):
        with self.assertRaises((original.AuditError, reviewer.Top1AuditError)):
            reviewer.replay(self.stable,self.conditional_original,self.conditional_result)
        bad=copy.deepcopy(self.conditional_result)
        bad["predecessor_report_sha256"] = "a"*64
        with self.assertRaises(reviewer.Top1AuditError):
            reviewer.replay(self.conditional,self.conditional_original,bad)

    def test_changed_holdout_label_does_not_change_weights_or_top1_outputs(self):
        altered=copy.deepcopy(self.conditional)
        for part in trial.EVAL_PARTITIONS:
            for row in altered["partitions"][part]:
                row["label"] ^= 1
        counterpart=trial.run(altered,steps=8)
        alternative=top.create_report(altered,counterpart)
        for a,b in zip(self.conditional_result["results"],alternative["results"],strict=True):
            self.assertEqual(a["weights_sha256"],b["weights_sha256"])
            self.assertEqual(a["top1_prediction_sha256"],b["top1_prediction_sha256"])
            self.assertNotEqual(a["retrospective_evaluation"],b["retrospective_evaluation"])

    def test_fake_retrospective_metric_rejected(self):
        bad=copy.deepcopy(self.conditional_result)
        bad["results"][2]["retrospective_evaluation"]["future_1"]["brier"]=0.0
        with self.assertRaisesRegex(reviewer.Top1AuditError,"metric"):
            reviewer.replay(self.conditional,self.conditional_original,bad)

    def test_cannot_label_same_source_as_future_or_ood(self):
        for key,value in (("real_ood_verified",True),
                          ("future_window_prospective",True),
                          ("compute_matched_training",True),
                          ("independent_pretrained_encoder_attested",True),
                          ("model_selection_permitted",True),
                          ("physical_cell_split_permitted",True),
                          ("authority_posture","ALLOW"),
                          ("production_admission","ACCEPTED")):
            with self.subTest(key=key):
                bad=copy.deepcopy(self.conditional_result)
                bad[key]=value
                with self.assertRaises(reviewer.Top1AuditError):
                    reviewer.replay(self.conditional,self.conditional_original,bad)

    def test_stringified_bool_counter_or_nan_rejected(self):
        for value in ("160",True,-1,1.5,float("nan")):
            with self.subTest(value=value):
                bad=copy.deepcopy(self.conditional_result)
                bad["results"][2]["metrics"]["executed_head_rows"] = value
                with self.assertRaises(reviewer.Top1AuditError):
                    reviewer.replay(self.conditional,self.conditional_original,bad)

    def test_training_input_missing_prevents_top1_dispatch(self):
        panel=copy.deepcopy(self.conditional)
        panel["partitions"]["new_train"]=[]
        with self.assertRaises(trial.InvalidPanel):
            top.create_report(panel,self.conditional_original)

    def test_untrusted_file_symlink_duplicate_json_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            json_path=root/"value.json"
            for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
                json_path.write_bytes(raw)
                with self.assertRaises(original.AuditError):
                    original.load(json_path)
            link=root/"alias.json"
            link.symlink_to(json_path)
            with self.assertRaises((OSError,original.AuditError)):
                original.load(link)
            if hasattr(os,"mkfifo"):
                fifo=root/"fifo"
                os.mkfifo(fifo)
                with self.assertRaises(original.AuditError):
                    original.load(fifo)

    def test_cli_preserves_old_output_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            inp=p/"panel.json";inp.write_bytes(trial.canonical(self.conditional))
            fit=p/"fit.json";fit.write_bytes(trial.canonical(self.conditional_original))
            out=p/"out.json";out.write_bytes(b"NOT_OVERWRITTEN")
            child=subprocess.run([sys.executable,str(Path(top.__file__)),
                                  "--panel",str(inp),"--soft-report",str(fit),
                                  "--out",str(out)],capture_output=True,timeout=50)
            self.assertEqual(child.returncode,2)
            self.assertEqual(out.read_bytes(),b"NOT_OVERWRITTEN")

    def test_producer_and_independent_reviewer_are_separate(self):
        producer=Path(top.__file__).read_text()
        audit=Path(reviewer.__file__).read_text()
        self.assertIn("torch.mv(",producer)
        self.assertNotIn("import torch",audit)
        self.assertNotIn("physical_router_top1 import",audit)
        self.assertNotIn("numpy",audit)


if __name__ == "__main__":
    unittest.main()
