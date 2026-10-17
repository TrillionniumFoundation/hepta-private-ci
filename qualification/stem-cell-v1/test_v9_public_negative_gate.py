"""Adversarial tests of public-only V9 failure evidence; never model success."""
import copy
import json
from pathlib import Path
import unittest
from v9_public_negative_gate import verify

ROOT=Path(__file__).parent

def original():
    def load(n):return json.loads((ROOT/n).read_bytes())
    return [load("STEM_V9_PHYSICAL_RECEIPT_20261015.json"),
            load("STEM_V9_POSTSEAL_WEAK_SCORES_20261015.json"),
            load("STEM_V9_TRAIN_DIAGNOSTIC_20261015.json"),
            load("STEM_V9_INDEPENDENT_AUDIT_20261015.json")]


class StrictPublicV9(unittest.TestCase):
    def test_source_control_passes_only_existing_negative(self):
        self.assertTrue(verify(*original()))

    def test_missing_heldout_root_denied(self):
        r=original();del r[1]["per_arm_source_root_aggregates"]["bm25_full"]["conv-49"]
        with self.assertRaises(ValueError):verify(*r)

    def test_invented_superior_model_denied(self):
        r=original();r[1]["per_arm_source_root_aggregates"]["seed41/new_only"]["conv-49"]["any_support_top3"]+=1
        with self.assertRaises(ValueError):verify(*r)

    def test_derived_weak_scores_not_reader_task(self):
        r=original();r[1]["independent_human_task_success"]=0.95
        with self.assertRaises(ValueError):verify(*r)

    def test_fake_future_windows_denied(self):
        r=original();r[1]["independent_calendar_future_windows"]=2
        with self.assertRaises(ValueError):verify(*r)

    def test_model_signature_fake_denied(self):
        r=original();r[0]["signed_model_owner"]=True
        with self.assertRaises(ValueError):verify(*r)

    def test_missing_original_batches_denied(self):
        r=original();r[0]["actual_original_encoder_forward_batches"]=0
        with self.assertRaises(ValueError):verify(*r)

    def test_fake_retention_repair_denied(self):
        r=original();r[2]["original_V6_retention_blocker_closed"]=True
        with self.assertRaises(ValueError):verify(*r)

    def test_fake_replay_denied(self):
        r=original();r[3]["actual_original_head_source_rank_replays"]=0
        with self.assertRaises(ValueError):verify(*r)

    def test_changed_original_answer_seal_denied(self):
        r=original();r[3]["original_prediction_sha256"]="f"*64
        with self.assertRaises(ValueError):verify(*r)

    def test_forged_authority_denied(self):
        r=original();r[0]["production_authorized"]=True
        with self.assertRaises(ValueError):verify(*r)


if __name__=='__main__':unittest.main()
