"""No-authority test vectors for public real-Encoder/Q24 snapshot contract."""
import copy
import hashlib
import json
import unittest

from real_encoder_q24_snapshot_gate import Refused, validate

def h(s):
    return hashlib.sha256(s.encode()).hexdigest()

def sample():
    reg={"fit_case_ids":["train-A","train-B"],"heldout_case_ids":["test-A"]}
    rsha=hashlib.sha256(json.dumps(reg,sort_keys=True).encode()).hexdigest()
    enc,proj=h("frozen Encoder"),h("train-only projector")
    rows=[
        {"case_id":cid,"split":spl,"source_text_sha256":h(cid),
         "feature_q24":[0]*32}
        for cid,spl in [("train-A","fit"),("train-B","fit"),("test-A","heldout")]
    ]
    snap={"schema":"hepta.neuron.public-encoder-q24-feature-snapshot.v1",
          "encoder_sha256":enc,"projection_sha256":proj,"registry_sha256":rsha,
          "projection_fit_case_ids":["train-A","train-B"],"feature_rows":rows,
          "claimed_independent_provenance":False,"production_qualification":False,
          "ndu_eligible":False}
    return snap,reg,enc,proj,rsha

class SnapshotAdmission(unittest.TestCase):
    def check(self,s,r,e,p,d):
        return validate(s,r,expected_encoder=e,expected_projection=p,
                        expected_registry_sha=d)

    def test_valid_synthetic_protocol_is_never_model_authority(self):
        s,r,e,p,d=sample()
        result=self.check(s,r,e,p,d)
        self.assertEqual(result["split_count"],{"fit":2,"heldout":1})
        self.assertFalse(result["independent_encoder_execution_attested"])
        self.assertFalse(result["original_selected_v1_a0_verified"])
        self.assertFalse(result["production_qualification"])
        self.assertEqual(result["decision"],"NO_MODEL_PROMOTION")

    def test_wrong_pretrained_encoder_hash(self):
        s,r,e,p,d=sample()
        with self.assertRaisesRegex(Refused,"identity"):
            self.check(s,r,h("not frozen"),p,d)

    def test_different_projection_denied(self):
        s,r,e,p,d=sample()
        with self.assertRaises(Refused):
            self.check(s,r,e,h("heldout-fit"),d)

    def test_leaked_heldout_projection_rejected(self):
        s,r,e,p,d=sample()
        s["projection_fit_case_ids"].append("test-A")
        with self.assertRaisesRegex(Refused,"training IDs"):
            self.check(s,r,e,p,d)

    def test_missing_heldout_feature_rejected(self):
        s,r,e,p,d=sample()
        s["feature_rows"].pop()
        with self.assertRaises(Refused):
            self.check(s,r,e,p,d)

    def test_duplicate_or_swapped_case_rejected(self):
        s,r,e,p,d=sample()
        s["feature_rows"][2]["case_id"]="train-A"
        with self.assertRaises(Refused):
            self.check(s,r,e,p,d)
        s,r,e,p,d=sample()
        s["feature_rows"][2]["split"]="fit"
        with self.assertRaises(Refused):
            self.check(s,r,e,p,d)

    def test_non_integer_and_bad_width_rejected(self):
        for change in [True,0.0,"0",134217729]:
            s,r,e,p,d=sample()
            s["feature_rows"][0]["feature_q24"][0]=change
            with self.assertRaises(Refused):
                self.check(s,r,e,p,d)
        s,r,e,p,d=sample()
        s["feature_rows"][0]["feature_q24"].pop()
        with self.assertRaises(Refused):
            self.check(s,r,e,p,d)

    def test_labels_are_not_a_feature_snapshot_field(self):
        s,r,e,p,d=sample()
        s["feature_rows"][0]["label"]=0
        with self.assertRaises(Refused):
            self.check(s,r,e,p,d)

    def test_fake_production_and_provenance_denied(self):
        for name in ["production_qualification","ndu_eligible",
                     "claimed_independent_provenance"]:
            s,r,e,p,d=sample()
            s[name]=True
            with self.assertRaises(Refused):
                self.check(s,r,e,p,d)

    def test_registry_train_test_overlap_rejected(self):
        s,r,e,p,d=sample()
        r["heldout_case_ids"]=["train-A"]
        with self.assertRaises(Refused):
            self.check(s,r,e,p,d)

    def test_unknown_fields_and_missing_digest_denied(self):
        s,r,e,p,d=sample()
        s["trusted"]=True
        with self.assertRaises(Refused):
            self.check(s,r,e,p,d)
        s,r,e,p,d=sample()
        with self.assertRaises(Refused):
            self.check(s,r,e,"",d)

if __name__=="__main__":
    unittest.main()
