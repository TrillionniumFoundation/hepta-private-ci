"""Tiny synthetic feature arrays only. Nothing here is a physical 400M/421M run."""
import copy
import unittest
from unittest import mock

import numpy as np

import gate
import matched_head as mh
import matched_head_review as review
from test_gate import fixture


def synthetic():
    panel, _, _ = fixture()
    rng = np.random.default_rng(20261017)
    model="ettin400"
    repo, revision, _, _ = gate.MODELS[model]
    cases=panel["cases"]
    bank={"schema":mh.FEATURE_SCHEMA,"panel_sha256":gate.digest(panel),
          "model":model,"repo":repo,"revision":revision,
          "source_weights_sha256":"a"*64,"source_tokenizer_sha256":"b"*64,
          "encoder_output_dimension": 16,"precision":"float32",
          "rows":[{"case_id":c["case_id"],"source_sha256":c["source_sha256"],
                   "input_sha256":c["input_sha256"],"values":rng.uniform(-2,2,16).tolist()}
                  for c in cases],
          "actual_pretrained_forward_reported": True,
          "physical_source_sha256_checked_reported":True,
          "signed_publisher_identity_verified":False,"production_authorized":False,
          "future_window_verified":False,"authority":"DENY_ALL"}
    labels={"schema":mh.FIT_SCHEMA,"panel_sha256":gate.digest(panel),
            "source_label_owner_sha256":"c"*64,"targets":[
                {"case_id":c["case_id"],"target":j%2}
                for j,c in enumerate(cases) if c["split"]=="fit"],
            "authority":"DENY_ALL","production_authorized":False}
    return panel,bank,labels


class MatchedHeadTests(unittest.TestCase):
    def test_dimensions_and_zero_extra_trained_projection(self):
        self.assertEqual(mh.PARAMS, 4161)
        p,b,l=synthetic();out=mh.train_one(p,b,l)
        self.assertEqual(out["receipt"]["projection"]["projection_trainable_params"],0)
        self.assertEqual(out["receipt"]["trainable_params"],4161)
        self.assertEqual(out["receipt"]["steps"],40)
        self.assertFalse(out["receipt"]["production_promotion_permitted"])
        self.assertFalse(out["receipt"]["has_test_labels"])

    def test_independent_numpy_replays_every_sgd_step_and_blind_logit(self):
        p,b,l=synthetic();product=mh.train_one(p,b,l)
        receipt=review.independent_replay(p,b,l,product)
        self.assertLess(receipt["parameter_max_abs_error"],3e-5)
        self.assertFalse(receipt["human_heldout_accuracy_scored"])
        self.assertFalse(receipt["promotion_permitted"])

    def test_projection_is_deterministic_and_label_independent(self):
        p,b,l=synthetic()
        x, cost=mh.project_bank(b)
        l["targets"][0]["target"] ^= 1
        y,new_cost=mh.project_bank(b)
        self.assertTrue(np.array_equal(x,y));self.assertEqual(cost,new_cost)

    def test_reordered_input_rejected(self):
        p,b,l=synthetic();b["rows"][0],b["rows"][1]=b["rows"][1],b["rows"][0]
        with self.assertRaises(gate.Denied): mh.validate_bank(p,b)

    def test_calibration_or_held_label_in_training_rejected(self):
        p,b,l=synthetic()
        for held in ("case2","case4"):
            altered=copy.deepcopy(l)
            altered["targets"].append({"case_id":held,"target":1})
            with self.assertRaises(gate.Denied):mh.validate_fit(p,altered)

    def test_extra_input_columns_rejected(self):
        p,b,l=synthetic();b["rows"][0]["target"]=1
        with self.assertRaises(gate.Denied):mh.validate_bank(p,b)

    def test_nonfinite_and_oversized_features_rejected(self):
        for bad in (float('nan'),float('inf'),9.0,"a",True):
            with self.subTest(bad=str(bad)):
                p,b,l=synthetic();b["rows"][0]["values"][0]=bad
                with self.assertRaises(gate.Denied):mh.validate_bank(p,b)

    def test_model_or_version_mismatch_rejected(self):
        for key,value in (("model","unknown"),( "revision","0"*40),
                           ("authority","PERMIT"),("production_authorized",True),
                           ("signed_publisher_identity_verified",True)):
            p,b,l=synthetic();b[key]=value
            with self.subTest(key=key):
                with self.assertRaises(gate.Denied):mh.validate_bank(p,b)

    def test_absent_both_class_support_fails(self):
        p,b,l=synthetic();l["targets"][1]["target"]=0
        with self.assertRaises(gate.Denied):mh.validate_fit(p,l)

    def test_unfair_training_budget_fails(self):
        p,b,l=synthetic();p["budget"]["head_trainable_params"]=4145
        b["panel_sha256"]=gate.digest(p);l["panel_sha256"]=gate.digest(p)
        with self.assertRaises(gate.Denied):mh.train_one(p,b,l)

    def test_reviewer_detects_self_rehashed_weights_attack(self):
        p,b,l=synthetic();out=mh.train_one(p,b,l)
        out["trained_head_tensors"]["2.bias"] += np.float32(0.1)
        # Updating the report hash must still fail genuine SGD replay.
        from hashlib import sha256
        hasher=sha256()
        for key,val in sorted(out["trained_head_tensors"].items()):
            hasher.update(key.encode()+b"\0"+val.tobytes())
        out["receipt"]["head_weight_sha256"]=hasher.hexdigest()
        with self.assertRaises(gate.Denied):review.independent_replay(p,b,l,out)

    def test_independent_projection_detects_self_consistent_corrupt_training_features(self):
        p,b,l=synthetic()
        original = mh.project_bank
        def tampered(feature_bank):
            arrays, cost = original(feature_bank)
            arrays[:, 0] += np.float32(0.25)
            return arrays, cost
        with mock.patch.object(mh, "project_bank", side_effect=tampered):
            product=mh.train_one(p,b,l)
        # Producer-side training and its reported costs are internally consistent,
        # but the reviewer recomputes the source-feature transform independently.
        with self.assertRaises(gate.Denied):review.independent_replay(p,b,l,product)

    def test_reviewer_rejects_corrupt_sealed_test_prediction(self):
        p,b,l=synthetic();out=mh.train_one(p,b,l)
        out["receipt"]["raw_test_logits"][0]["logit"]+=0.4
        with self.assertRaises(gate.Denied):review.independent_replay(p,b,l,out)

    def test_second_model_gets_same_trainable_budget_but_not_free_projection(self):
        p,b,l=synthetic();out0=mh.train_one(p,b,l)
        repo,rev,_,_=gate.MODELS["laya421"]
        b["model"]="laya421";b["repo"]=repo;b["revision"]=rev
        out1=mh.train_one(p,b,l)
        self.assertEqual(out0["receipt"]["trainable_params"],out1["receipt"]["trainable_params"])
        self.assertEqual(out0["receipt"]["steps"],out1["receipt"]["steps"])
        self.assertNotEqual(out0["receipt"]["projection"]["projection_digest"],
                            out1["receipt"]["projection"]["projection_digest"])


if __name__=="__main__": unittest.main()
