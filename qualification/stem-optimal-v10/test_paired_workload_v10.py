"""Physical Torch CPU math on fixture vectors, plus fail-closed V10 receipt checks.

No real pretrained weights in these tests; hosted source/model lanes remain separate.
"""
from __future__ import annotations
import copy
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paired_workload_v10 as producer
import independent_workload_review_v10 as audit


class PairedPhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(2)
        cls.torch = torch
        z = torch.arange(64*384,dtype=torch.float32).reshape(64,384)
        cls.train = torch.nn.functional.normalize(torch.sin(z/101), dim=-1)
        cls.head, cls.receipt = producer.make_head_and_fit(
            cls.train, [i % 4 for i in range(64)],config={"seed":17,"steps":100,
             "learning_rate":0.006,"per_cell_parameters":6914,"cells":4})

    def test_real_head_checkpoint_and_parameter_shapes(self):
        self.assertNotEqual(self.receipt["initial_sha256"],self.receipt["trained_sha256"])
        self.assertEqual(self.receipt["actual_optimizer_updates"],100)
        self.assertEqual(len(self.receipt["trained_sha256"]),64)
        self.assertEqual(sum(x.numel() for x in self.head.parameters()),27656)

    def test_original_head_refuses_budget_or_labels(self):
        for changed in ({"seed":18,"steps":100,"learning_rate":0.006,
                         "per_cell_parameters":6914,"cells":4},
                        {"seed":17,"steps":50,"learning_rate":0.006,
                         "per_cell_parameters":6914,"cells":4}):
            with self.assertRaisesRegex(ValueError, "budget"):
                producer.make_head_and_fit(self.train,[i%4 for i in range(64)],config=changed)
        with self.assertRaisesRegex(ValueError, "feature/label"):
            producer.make_head_and_fit(self.train,[4]*64,
                config={"seed":17,"steps":100,"learning_rate":0.006,
                 "per_cell_parameters":6914,"cells":4})

    def test_genuinely_paid_both_cpu_batch_arms_and_model_parity(self):
        torch = self.torch
        rows = [{"case_id":f"heldout:{i}","text":f"original-{i}"} for i in range(32)]
        selected = [rows[i] for i in (0,2,4,6,8,10,12,14)]
        class NumericEncoder:
            def __init__(self):self.sequences=0;self.calls=0
        model=NumericEncoder()
        def actual_fake_encode(texts, tokenizer, model):
            model.calls += math.ceil(len(texts)/16)
            model.sequences += len(texts)
            x = torch.tensor([int(s.split("-")[-1]) for s in texts], dtype=torch.float32)
            # Explicit actual Torch CPU compute per row; not a pre-trained checkpoint.
            v=torch.nn.functional.normalize(torch.sin(x.unsqueeze(1)*0.01 +
                            torch.arange(384).float().unsqueeze(0)*0.1),dim=-1)
            return v, math.ceil(len(texts)/16)
        stub=types.SimpleNamespace(_encode=actual_fake_encode)
        with patch.dict(sys.modules,{"stem_candidate_v1":stub}):
            timings,outputs,paid,batches=producer.paired_runs(
                model,None,self.head,[],rows,selected)
        self.assertEqual(paid,{"selected":32,"full":128})
        self.assertEqual(batches,{"selected":4,"full":8})
        self.assertEqual(model.sequences,160)
        self.assertEqual(model.calls,12)
        self.assertEqual(len(timings["selected"]),4)
        self.assertEqual(len(outputs["full"]),4)
        original={"rows":[{"case_id":k,"scores":{"learned":v}}
                         for k,v in outputs["full"][0].items()]}
        parity=producer.observed_parity(outputs,original,selected)
        self.assertLess(parity["max_original_v3_probability_abs_drift"],1e-6)
        self.assertLess(parity["max_full_vs_selected_probability_abs_drift"],1e-6)
        altered=copy.deepcopy(outputs)
        altered["selected"][0][selected[0]["case_id"]][0] += .01
        with self.assertRaisesRegex(ValueError, "numerical parity"):
            producer.observed_parity(altered,original,selected)

    def test_rejects_zero_or_wrong_arm_sizes(self):
        rows=[{"case_id":f"heldout:{i}","text":f"x{i}"} for i in range(32)]
        with self.assertRaisesRegex(ValueError,"wrong fixed"):
            producer.paired_runs(None,None,self.head,[],rows,rows[:7])


class AuditorTests(unittest.TestCase):
    def setUp(self):
        self.old={"candidate":"granite47", "source_plan_sha256":"a"*64,
                  "actual_weight_sha256":"b"*64,"model_revision":"c"*40,
                  "trained_head_sha256":"d"*64}
        self.report={"schema":audit.SCHEMA,"candidate":"granite47",
            "source_plan_sha256":self.old["source_plan_sha256"],
            "actual_weight_sha256":self.old["actual_weight_sha256"],
            "original_v3_model_revision":self.old["model_revision"],
            "original_trained_head_sha256":self.old["trained_head_sha256"],
            "authority":"DENY_ALL","disposition":"HOLD_NO_GO",
            "production_authorized":False,"stem_winner_verified":False,
            "cell_split_authorized":False,"amortized_full_lifecycle_savings_verified":False,
            "production_p99_gpu_energy_wal_attested":False,
            "negative_transfer_verified":False,"ndu_net_gain_verified":False,
            "source_independent_families":1,"future_windows":0,
            "fit_training_actual_updates":100,"fit_physical_encoder_sequences":64,
            "fit_physical_encoder_batches":4,
            "measured_full_and_selected_both_executed":True,
            "counterbalanced_order":[list(x) for x in audit.ORDER],
            "measured_arm_sequence_counts":{"selected":32,"full":128},
            "measured_arm_batch_counts":{"selected":4,"full":8},
            "actual_total_workload_encoder_sequences":224,
            "actual_total_workload_encoder_batches":16,
            "measured_arm_timings": {
                "selected":[{"wall_seconds":0.1,"cpu_seconds":0.08,
                   "actual_sequences":8,"batches":1} for _ in range(4)],
                "full":[{"wall_seconds":0.3,"cpu_seconds":0.25,
                    "actual_sequences":32,"batches":2} for _ in range(4)]},
            "per_arm_median_query_wall_seconds":{"selected":0.1,"full":0.3},
            "per_arm_median_query_cpu_seconds":{"selected":0.08,"full":0.25},
            "cheap_actual_wall_seconds":0.02,"cheap_actual_cpu_seconds":0.01,
            "model_load_wall_seconds":2.0,"fit_encode_wall_seconds":0.4,
            "fit_training_wall_seconds":0.1,
            "paid_workload_total_wall_seconds":4.5,
            "paid_workload_total_cpu_seconds":3.5,
            "self_reported_same_process_peak_rss_bytes":200_000_000,
            "max_original_v3_probability_abs_drift":0.00001,
            "max_full_vs_selected_probability_abs_drift":0.00001}

    def test_independent_recount_accepts_bounded_unattested_data(self):
        result=audit.inspect(self.report,self.old)
        self.assertEqual(result["all_measured_encoder_sequences"],224)
        self.assertFalse(result["encoder_forward_count_independently_attested"])
        self.assertFalse(result["full_lifecycle_savings_verified"])
        self.assertEqual(result["authority"],"DENY_ALL")

    def test_false_cost_or_unauthorized_promotion_denied(self):
        for mutate in (lambda x:x.__setitem__("production_authorized",True),
                       lambda x:x.__setitem__("actual_total_workload_encoder_sequences",72),
                       lambda x:x["measured_arm_timings"]["selected"][0].__setitem__("batches",2),
                       lambda x:x.__setitem__("max_full_vs_selected_probability_abs_drift",0.01),
                       lambda x:x.__setitem__("paid_workload_total_wall_seconds",1.0),
                       lambda x:x["per_arm_median_query_wall_seconds"].__setitem__("full",0.01)):
            report=copy.deepcopy(self.report)
            mutate(report)
            with self.assertRaises(ValueError): audit.inspect(report,self.old)

    def test_original_model_source_substitution_rejected(self):
        report=copy.deepcopy(self.report)
        report["original_trained_head_sha256"]="e"*64
        with self.assertRaisesRegex(ValueError,"checkpoint/source"):
            audit.inspect(report,self.old)


if __name__=="__main__":unittest.main()
