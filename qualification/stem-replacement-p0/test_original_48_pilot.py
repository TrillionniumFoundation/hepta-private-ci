"""P2.3 source-only adversarial fixtures: NO pretrained weights or real held labels."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import gate
import matched_head as mh
import multirc_source_bridge as bridge
import original_48_pilot as pilot
import physical_feature_bank
from test_multirc_source_bridge import fixture


class Real48ProtocolTests(unittest.TestCase):
    def prepare(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        original_fit,original_blind=fixture()
        panel,views,fit,bridge_record=bridge.convert(original_fit,original_blind)
        # Fixture-generated source is never mistaken for real MultiRC.
        self.sha_patch=mock.patch.object(pilot,"SOURCE_SHA",gate.digest(panel))
        self.sha_patch.start();self.addCleanup(self.sha_patch.stop)
        self.sha1_patch=mock.patch.object(pilot,"SRC_TRAIN_SHA",original_fit["metadata"]["train_sha256"])
        self.sha1_patch.start();self.addCleanup(self.sha1_patch.stop)
        self.sha2_patch=mock.patch.object(pilot,"SRC_VALID_SHA",original_fit["metadata"]["validation_sha256"])
        self.sha2_patch.start();self.addCleanup(self.sha2_patch.stop)
        model="ettin400";repo,rev,_,_=gate.MODELS[model]
        rng=np.random.default_rng(44)
        bank={"schema":mh.FEATURE_SCHEMA,"panel_sha256":gate.digest(panel),
              "model":model,"repo":repo,"revision":rev,
              "source_weights_sha256":"a"*64,"source_tokenizer_sha256":"b"*64,
              "encoder_output_dimension":32,"precision":"float32",
              "rows":[{"case_id":c["case_id"],"source_sha256":c["source_sha256"],
                       "input_sha256":c["input_sha256"],
                       "values":rng.uniform(-1,1,32).tolist()}
                      for c in panel["cases"]],
              "actual_pretrained_forward_reported":True,
              "physical_source_sha256_checked_reported":True,
              "signed_publisher_identity_verified":False,"production_authorized":False,
              "future_window_verified":False,"authority":"DENY_ALL"}
        cost={"actual_encoder_forwards_observed":48,
              "actual_loaded_tensor_elements_reported":447_458_496,
              "input_tokenization_nontruncated_reported":True,
              "original_issuer_signature_verified":False,
              "production_authorized":False,"authority":"DENY_ALL","disposition":"HOLD_NO_GO",
              "total_real_input_tokens":48*45,
              "clock_cpu_ns_self_reported":1000,
              "source_review_receipt_sha256":"c"*64,
              "clock_wall_ns_self_reported":1001,
              "peak_rss_kib_linux_self_reported":2000}
        private=root/"private-48"/model
        private.parent.mkdir(mode=0o700)
        source=root/"panel.json";fit_path=root/"fit.json";views_path=root/"views.json"
        p0fit=root/"original-fit.json";p0blind=root/"original-blind.json";owner_path=root/"owner.json"
        owner={"schema":"hepta.p0.multirc-original-human-labels.v1",
               "panel_id":original_fit["metadata"]["panel_id"],
               "original_human_candidate_labels":{
                   c["case_id"]:(int(c["answer_id"],16)%2)
                   for c in original_blind["cases"] if c["condition"]=="original"},
               "generated_intervention_labels_invented":False,
               "source_signature_independently_verified":False,"authority":"DENY_ALL"}
        fake_receipt=root/"source-receipt.json"
        for path,value in ((source,panel),(fake_receipt,{"model":model,"repo":repo,
            "revision":rev,"selected_source_inventory":[{"is_weight":True,
            "source_identity":"a"*64,"source_identity_type":"lfs_sha256"}]}),
            (fit_path,fit),(views_path,views),
                           (p0fit,original_fit),(p0blind,original_blind),(owner_path,owner)):
            pilot.new_json(path,value)
        return locals()

    def review_one(self,v,destination):
        import physical_forward
        with mock.patch.object(physical_forward,"checked_receipt",return_value={
                "source_sha256_receipt":"c"*64}):
            return pilot.audit("ettin400",v["source"],v["fit_path"],v["private"],
                               v["fake_receipt"],v["root"],destination)

    def run_one(self,v):
        with mock.patch.object(physical_feature_bank,"make_bank",return_value=(v["bank"],v["cost"])):
            return pilot.produce("ettin400",v["source"],v["views_path"],v["fit_path"],
                                 v["source"],v["root"],v["private"])

    def test_complete_source_only_fixture_through_three_distinct_entrypoints(self):
        v=self.prepare()
        seal=self.run_one(v)
        self.assertEqual(seal["encoder_calls"],48)
        self.assertFalse(seal["original_human_test_labels_loaded"])
        audit_path=v["root"]/"review.json"
        audit=self.review_one(v,audit_path)
        self.assertEqual(audit["head_replayed_steps"],40)
        self.assertLessEqual(audit["head_replay_parameter_max_abs_error"],3e-5)
        self.assertFalse(audit["human_heldout_scored"])
        observed=pilot.observe("ettin400",v["source"],v["fit_path"],
            v["p0fit"],v["p0blind"],v["owner_path"],v["private"],audit_path,
            v["root"]/"aggregate.json")
        self.assertEqual(observed["test"]["cases"],16)
        self.assertEqual(observed["calibration"]["cases"],8)
        self.assertEqual(observed["test_independent_source_groups"],8)
        self.assertIsNone(observed["model_selected"])
        self.assertFalse(observed["production_promotion_permitted"])
        self.assertNotIn("case_id",json.dumps(observed))
        self.assertNotIn("logit",json.dumps(observed))
        self.assertNotIn("original_human_candidate_labels",json.dumps(observed))

    def test_actual_original_hosted_panel_hash_precedes_model_import(self):
        v=self.prepare()
        with mock.patch.object(physical_feature_bank,"make_bank") as fake:
            with mock.patch.object(pilot,"SOURCE_SHA","a"*64):
                with self.assertRaises(gate.Denied):
                    pilot.produce("ettin400",v["source"],v["views_path"],v["fit_path"],
                                  v["source"],v["root"],v["private"])
            fake.assert_not_called()

    def test_no_replacement_model_slot_can_load(self):
        v=self.prepare()
        with mock.patch.object(physical_feature_bank,"make_bank") as fake:
            with self.assertRaises(gate.Denied):
                pilot.produce("openjev434",v["source"],v["views_path"],v["fit_path"],
                              v["source"],v["root"],v["private"])
            fake.assert_not_called()

    def test_calibration_label_aboard_fit_contract_is_denied(self):
        v=self.prepare()
        doc=pilot.read_json(v["fit_path"])
        doc["targets"].append({"case_id":v["panel"]["cases"][24]["case_id"],"target":1})
        changed=v["root"]/"fit-tampered.json";pilot.new_json(changed,doc)
        with mock.patch.object(physical_feature_bank,"make_bank") as fake:
            with self.assertRaises(gate.Denied):
                pilot.produce("ettin400",v["source"],v["views_path"],changed,
                              v["source"],v["root"],v["private"])
            fake.assert_not_called()

    def test_after_seal_tensor_mutation_refused_before_review(self):
        v=self.prepare();self.run_one(v)
        with (v["private"]/"head-tensors.npz").open("ab") as f:f.write(b"changed")
        with self.assertRaisesRegex(gate.Denied,"altered after seal"):
            self.review_one(v,v["root"]/"r.json")

    def test_truncated_prediction_or_forged_label_in_review_denied(self):
        v=self.prepare();self.run_one(v)
        raw=pilot.read_json(v["private"]/"head.json")
        raw["raw_test_logits"][0]["logit"] += .5
        (v["private"]/"head.json").write_bytes(pilot.canonical(raw))
        with self.assertRaises(gate.Denied):
            self.review_one(v,v["root"]/"r.json")

    def test_observer_requires_independent_audit_before_human_label_open(self):
        v=self.prepare();self.run_one(v)
        with self.assertRaises(gate.Denied):
            pilot.observe("ettin400",v["source"],v["fit_path"],v["p0fit"],v["p0blind"],
                          v["owner_path"],v["private"],v["root"]/"missing-review.json",
                          v["root"]/"aggregate.json")

    def test_missing_replay_does_not_even_open_original_held_labels(self):
        v=self.prepare();self.run_one(v)
        original=pilot.read_json
        inspected=[]
        def tracked_read(path):
            inspected.append(str(path))
            return original(path)
        with mock.patch.object(pilot,"read_json",side_effect=tracked_read):
            with self.assertRaises(gate.Denied):
                pilot.observe("ettin400",v["source"],v["fit_path"],v["p0fit"],v["p0blind"],
                              v["owner_path"],v["private"],v["root"]/"missing-review.json",
                              v["root"]/"aggregate.json")
        self.assertNotIn(str(v["owner_path"]),inspected)
        self.assertNotIn(str(v["p0blind"]),inspected)

    def test_nonfinite_or_extreme_head_logits_refused(self):
        for bad in (float('nan'), float('inf'), 200.0, "1.0", True):
            with self.subTest(bad=str(bad)),self.assertRaises(gate.Denied):
                pilot._sigmoid(bad)

    def test_wrong_original_human_owner_rejected(self):
        v=self.prepare();self.run_one(v)
        audit=v["root"]/"review.json"
        self.review_one(v,audit)
        owner=pilot.read_json(v["owner_path"]);owner["panel_id"]="0"*64
        (v["owner_path"]).write_bytes(pilot.canonical(owner))
        with self.assertRaises(gate.Denied):
            pilot.observe("ettin400",v["source"],v["fit_path"],v["p0fit"],v["p0blind"],
                          v["owner_path"],v["private"],audit,v["root"]/"aggregate.json")

    def test_strict_input_json_duplicate_key_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"sample.json"
            for value in ('{"a":1,"a":2}', '{"x": NaN}'):
                p.write_text(value)
                with self.assertRaises(gate.Denied):pilot.read_json(p)

    def test_create_only_sealed_public_aggregate(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"receipt.json"
            pilot.new_json(p,{"authority":"DENY_ALL","model_selected":None})
            with self.assertRaises(gate.Denied):pilot.new_json(p,{"authority":"DENY_ALL"})
            self.assertEqual(p.stat().st_mode & 0o777,0o600)

    def test_private_npz_archive_refuses_unexpected_tensor(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"weights.npz"
            np.savez(path,bad=np.zeros((1,),dtype=np.float32))
            with self.assertRaises(gate.Denied):pilot.npz_product(path,{"authority":"DENY_ALL"})

if __name__=="__main__":unittest.main()
