"""Real-model-capable E1 core 97M/140M/149M failure and control tests.

Every feature and receipt in these tests is SYNTHETIC. No model checkpoint is
downloaded and no positive production or future outcome is established.
"""
from __future__ import annotations
import copy
import unittest

import e1_core_real_cpu as run
import e1_public_triplet_real_cpu as trainer
import e1_public_triplet_review as review
from test_e1_public_triplet_review import fixture as historical_fixture

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)
        panel, reports=historical_fixture()
        reports.pop("embeddinggemma_2_text")
        width=768
        vectors={c["case_id"]:
                 [((int(c["case_id"][:4],16)%99)-50)/100]*width
                 for c in panel["cases"]}
        fit=trainer.fit_heads(panel,"modernbert_base",vectors,feature_width=768)
        previous=reports["mmbert_small"]
        modern=copy.deepcopy(previous)
        modern["model"]="modernbert_base"
        modern["model_name"]="answerdotai/ModernBERT-base"
        modern["model_revision"]=run.MODELS["modernbert_base"][1]
        modern["feature_width"]=width
        modern["fitting"]=fit
        modern["wall_ms"]=fit["train_time_ms"]+10.
        modern["cpu_process_ms"]=fit["train_time_ms"]+1.
        reports["modernbert_base"]=modern
        for name,report in reports.items():
            report["model_name"]=run.MODELS[name][0]
            report["physical_observations"].update({
                "local_all_saved_model_tensors_checked_by_loader":True,
                "publisher_files_checked_by_local_acquisition":True,
                "local_encoder_forward_calls_observed":224,
                "publisher_file_inventory_sha256":"b"*64,
                "reference_transformers_runtime_version":"4.57.1",
            })
        cls.source=(panel,reports)

    def data(self):
        return copy.deepcopy(self.source)

    def deny(self, edit):
        panel,reports=self.data()
        edit(panel,reports)
        with self.assertRaises((review.Invalid,KeyError,ValueError,TypeError)):
            review.evaluate(panel,reports,core=True)

    def test_distinct_core_model_registry(self):
        self.assertEqual(set(run.MODELS),set(review.CORE_MODELS))
        self.assertNotIn("embeddinggemma_2_text",run.MODELS)
        self.assertEqual(run.MODELS["modernbert_base"][2],768)
        with self.assertRaises(run.Invalid):
            run.spec("embeddinggemma_2_text")

    def test_exact_joint_input(self):
        self.assertEqual(
            run._render_joint({"state":"S","question":"Q","options":["A","B"]}),
            "State: S\nQuestion: Q\nOptions: 0: A | 1: B")

    def test_768_sgd_head_has_full_private_parameter_ledger(self):
        panel,reports=self.data()
        observed=review.evaluate(panel,reports,core=True)
        self.assertEqual(observed["schema"],"hepta.e1-core-triad-real-cpu-numeric.v1")
        self.assertEqual(observed["cases"],224)
        self.assertEqual(len(observed["pairwise_test"]),3)
        self.assertTrue(observed["registered_core_triad"])
        self.assertEqual(observed["resource_observations"]["modernbert_base"]["complete_Head_parameters"],1538)
        self.assertFalse(observed["true_future_three_window_evidence_available"])
        self.assertFalse(observed["production_no_change_checkpoint_authenticated"])
        self.assertFalse(observed["stem_winner_selected"])
        self.assertFalse(observed["production_promotion_permitted"])
        self.assertEqual(observed["authority"],"DENY_ALL")

    def test_missing_modern_cannot_substitute_gemma(self):
        def edit(p,r):
            r["embeddinggemma_2_text"]=r.pop("modernbert_base")
        self.deny(edit)

    def test_fake_768_parameter_ledger(self):
        self.deny(lambda p,r:r["modernbert_base"]["fitting"].update(head_parameter_count=770))

    def test_changed_modern_revision(self):
        self.deny(lambda p,r:r["modernbert_base"].update(model_revision="f"*40))

    def test_wrong_model_publisher(self):
        self.deny(lambda p,r:r["modernbert_base"].update(model_name="jhu-clsp/mmBERT-small"))

    def test_unverified_saved_model_tensor(self):
        self.deny(lambda p,r:r["modernbert_base"]["physical_observations"].update(
            local_all_saved_model_tensors_checked_by_loader=False))

    def test_missing_publisher_bytes(self):
        self.deny(lambda p,r:r["granite_97m_r2"]["physical_observations"].update(
            publisher_file_inventory_sha256=None))

    def test_fake_complete_local_forwards(self):
        self.deny(lambda p,r:r["mmbert_small"]["physical_observations"].update(
            local_encoder_forward_calls_observed=223))

    def test_inconsistent_runtime(self):
        self.deny(lambda p,r:r["modernbert_base"]["physical_observations"].update(
            reference_transformers_runtime_version="5.19.0"))

    def test_changed_training_budget(self):
        self.deny(lambda p,r:r["modernbert_base"]["fitting"].update(steps=41))

    def test_missing_original_pair(self):
        self.deny(lambda p,r:r["modernbert_base"]["fitting"]["controls"]["learned_head"][
            "predictions"].pop())

    def test_forged_new_public_future(self):
        self.deny(lambda p,r:r["granite_97m_r2"].update(
            public_dataset_is_chronological_future=True))

    def test_unsupported_empty_stage_and_model(self):
        with self.assertRaises(run.Invalid):
            run.spec("")
        with self.assertRaises(run.Invalid):
            run._render_joint({"state":"S","question":"Q","options":"A"})

if __name__=="__main__":
    unittest.main()
