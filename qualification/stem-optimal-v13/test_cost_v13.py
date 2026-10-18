"""Source-only negative gates and real synthetic Torch CPU paired arithmetic."""
import copy
import math
import sys
import types
import unittest
from unittest.mock import patch

import cost_only_v13 as producer
import independent_cost_v13 as review


def fixture():
    source = {"source_plan_sha256": producer.SOURCE_SHA,
              "heldout": [{"case_id": f"heldout:{i:02}", "source_sha256": f"{i:02}"}
                          for i in range(32)]}
    cheap = {"source_plan_sha256": producer.SOURCE_SHA, "rows": [
        {"case_id": f"heldout:{i:02}", "source_sha256": f"{i:02}",
         "scores": {"char_345_tfidf_centroid": [0.4 + i/500, .3, .2-i/500, .1]}}
        for i in range(32)]}
    original = {"candidate": "granite47", "source_plan_sha256": producer.SOURCE_SHA,
                "actual_weight_sha256": "d"*64, "model_revision": "e"*40,
                "initial_head_sha256": "a"*64, "trained_head_sha256": "c"*64}
    report = {"schema": producer.SCHEMA, "candidate": "granite47",
       "source_plan_sha256": producer.SOURCE_SHA,
       "original_weight_sha256": original["actual_weight_sha256"],
       "original_model_revision": original["model_revision"],
       "original_head_initial_sha256": original["initial_head_sha256"],
       "original_head_trained_sha256": original["trained_head_sha256"],
       "observed_head_initial_sha256": original["initial_head_sha256"],
       "observed_head_trained_sha256": "b"*64,
       "historical_trained_head_byte_equal": False,
       "historical_prediction_numerically_admitted": False,
       "max_historical_prediction_abs_drift_descriptive": .000001,
       "max_within_run_selected_full_abs_drift": 1e-8,
       "actual_selected_case_ids": review.original_selected(source, cheap),
       "complete_loader_inventory": {"missing_parameter_count":0,
             "unexpected_parameter_count":0,"mismatched_parameter_count":0,
             "loader_error_count":0,"complete_base_material_admitted":True,
             "loaded_parameter_scalars":47662464,"model_weight_sha256":"d"*64},
       "cheap_route_wall_seconds": .01,"cheap_route_cpu_seconds": .01,
       "model_load_wall_seconds":1.0, "fit_encoder_wall_seconds":1.0,
       "head_training_wall_seconds": .2,
       "fit_encoder_sequences":64,"fit_encoder_batches":4,
       "trained_head_optimizer_updates":100,
       "measured_order": [list(x) for x in producer.v10.ARM_ORDER],
       "measured_arm_times": {
         "selected": [{"wall_seconds":.1,"cpu_seconds":.08,"actual_sequences":8,
                       "batches":1} for _ in range(4)],
         "full": [{"wall_seconds":.3,"cpu_seconds":.22,"actual_sequences":32,
                   "batches":2} for _ in range(4)]},
       "measured_arm_sequence_counts":{"selected":32,"full":128},
       "measured_arm_batch_counts":{"selected":4,"full":8},
       "actual_total_encoder_sequences":224,"actual_total_encoder_batches":16,
       "median_arm_wall_seconds":{"selected":.1,"full":.3},
       "median_arm_cpu_seconds":{"selected":.08,"full":.22},
       "total_paid_workload_wall_seconds":4.0,"total_paid_workload_cpu_seconds":3.0,
       "self_reported_process_maxrss_bytes":700000000,
       "physical_8_vs_32_matched_process_cost_observed":True,
       "full_lifecycle_resource_savings_verified":False,
       "test_gold_ever_reopened":False,"historical_test_labels_previously_exposed":True,
       "independent_source_families":1,"future_windows":0,
       "target_host_p99_energy_attested":False,"stem_winner_verified":False,
       "ndu_gain_verified":False,"production_authorized":False,
       "cell_split_authorized":False,"authority":"DENY_ALL","disposition":"HOLD_NO_GO"}
    return source, cheap, original, report


class MaterialSourceTests(unittest.TestCase):
    def test_loader_accepts_exact_complete_mapping(self):
        self.assertEqual(producer.loading_inventory({"missing_keys":[],
            "unexpected_keys":(),"mismatched_keys":set(),"error_msgs":[]}),
            {"missing_parameter_count":0,"unexpected_parameter_count":0,
             "mismatched_parameter_count":0,"loader_error_count":0,
             "complete_base_material_admitted":True})

    def test_any_missing_mismatch_unexpected_error_is_fail_closed(self):
        for key,value in (("missing_keys",["embeddings.tok_embeddings.weight"]),
                          ("unexpected_keys",["some.unloaded.weight"]),
                          ("mismatched_keys",[("x",(1,),(2,))]),
                          ("error_msgs",["meta tensor"]),
                          ("missing_keys","not a list")):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    producer.loading_inventory({key:value})

    def test_same_process_pair_parity_is_independent_of_historical_sha(self):
        selected=[{"case_id":f"heldout:{i:02}"} for i in range(8)]
        one={f"heldout:{i:02}":[.1,.2,.3,.4] for i in range(32)}
        outputs={"selected":[{r["case_id"]:one[r["case_id"]][:] for r in selected}
                             for _ in range(4)],
                 "full":[copy.deepcopy(one) for _ in range(4)]}
        self.assertEqual(producer.internal_parity(outputs,selected),0.0)
        outputs["selected"][0]["heldout:00"][0]+=.001
        with self.assertRaisesRegex(ValueError,"same-run"):
            producer.internal_parity(outputs,selected)

    def test_unknown_model_cannot_claim_original_47m_cost(self):
        self.assertEqual(producer.CANDIDATES,("granite47","granite97"))
        self.assertNotIn("mmbert140",producer.CANDIDATES)

    def test_real_torch_cpu_pair_uses_physically_paid_32_plus_128(self):
        try:
            import torch
        except ImportError:
            self.skipTest("Torch necessary for numerical paired-fixture")
        rows=[{"case_id":f"heldout:{i:02}","text":f"number:{i}"} for i in range(32)]
        selected=rows[:8]
        torch.manual_seed(19)
        head=torch.nn.Linear(384,4).eval()
        def mock_encode(texts,tokenizer,model):
            import torch.nn.functional as F
            inputs=torch.tensor([int(x.split(":")[1]) for x in texts],dtype=torch.float32)
            feats=F.normalize(torch.sin(inputs[:,None] + torch.arange(384).float()[None,:]),dim=-1)
            model["sequences"]+=len(texts)
            model["batches"]+=math.ceil(len(texts)/16)
            return feats,math.ceil(len(texts)/16)
        model={"sequences":0,"batches":0}
        with patch.dict(sys.modules,{"stem_candidate_v1":types.SimpleNamespace(_encode=mock_encode)}):
            times,out,paid,batches=producer.v10.paired_runs(model,None,head,[],rows,selected)
        self.assertEqual(model,{"sequences":160,"batches":12})
        self.assertEqual(paid,{"selected":32,"full":128})
        self.assertEqual(batches,{"selected":4,"full":8})
        self.assertLess(producer.internal_parity(out,selected),1e-6)
        self.assertTrue(all(t["wall_seconds"]>0 for arm in times.values() for t in arm))


class OriginalIndependentCostTests(unittest.TestCase):
    def setUp(self):
        self.source,self.cheap,self.original,self.report=fixture()

    def test_genuine_224_sequence_cost_only_accepts_negative_byte_parity(self):
        r=review.inspect(self.report,self.original,self.source,self.cheap)
        self.assertEqual(r["candidate"],"granite47")
        self.assertFalse(r["trained_head_byte_equal"])
        self.assertFalse(r["full_lifecycle_savings_verified"])
        self.assertEqual(r["authority"],"DENY_ALL")

    def test_tamper_source_model_or_selected_inputs_rejected(self):
        for mutation in (
            lambda r:r["actual_selected_case_ids"].reverse(),
            lambda r:r.__setitem__("original_weight_sha256","f"*64),
            lambda r:r.__setitem__("historical_trained_head_byte_equal",True),
            lambda r:r["complete_loader_inventory"].__setitem__("missing_parameter_count",1),
            lambda r:r.__setitem__("max_within_run_selected_full_abs_drift",0.001),
            lambda r:r.__setitem__("actual_total_encoder_sequences",72),
            lambda r:r.__setitem__("total_paid_workload_wall_seconds",1.0),
            lambda r:r.__setitem__("production_authorized",True),
            lambda r:r.__setitem__("full_lifecycle_resource_savings_verified",True),
            lambda r:r["median_arm_wall_seconds"].__setitem__("selected",0.0001)):
            a=copy.deepcopy(self.report)
            mutation(a)
            with self.assertRaises(ValueError):review.inspect(a,self.original,self.source,self.cheap)


if __name__=="__main__":
    unittest.main()
