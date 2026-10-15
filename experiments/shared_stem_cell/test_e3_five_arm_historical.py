"""Synthetic *mechanism-only* tests; no original pretrained model is loaded."""
import copy
import hashlib
import json
import unittest
import e3_five_arm_historical as m

SHA = "a"*64

def cases():
    original=[]
    ocr=[]
    native=[]
    labels=[]
    v=[.1,.2,.3,.4]
    for i in range(64):
        rid=f"{i:064x}"
        group=f"{i+1000:064x}"
        original.append({"id":rid,"group":group,"split":"test",
                        "source_input_sha256":f"{i+2000:064x}",
                        "arms":{"text_only":list(v),
                                "unaligned_equal_fusion":list(v),
                                "train_gate":list(v),
                                "rotated_equal_fusion":list(v),
                                "bridge_image_only":list(v),
                                "bridge_equal_fusion":list(v),
                                "calibrated_fusion":list(v),
                                "image_masked":list(v)}})
        for result in (ocr,native):
            result.append({"id":rid,"group":group,
                           "source_input_sha256":f"{i+2000:064x}",
                           "probabilities":list(v)})
        labels.append({"id":rid,"group":group,"split":"test","label":3})
    return original,ocr,native,labels

def panel():
    x,y,z,lab=cases()
    orig={"schema":m.ORIGINAL,"production_accepted":False,
          "held_labels_visible_to_inference":False,
          "independent_ground_truth_observer":False,
          "stem_model":{"repo":m.GRANITE[0],"revision":m.GRANITE[1],"sha256":SHA},
          "vision_model":{"repo":"facebook/dinov2-small",
                          "revision":"ed25f3a31f01632728cabb09d1542f84ab7b0056",
                          "sha256":SHA},
          "fit":{"private_cell_head_parameters":769,"cell_optimizer_updates":80,
                 "train_cases":96,"calibration_cases":32,"holdout_cases":64},
          "physical_text_forward_batches":60,"physical_vision_forward_batches":24,
          "source_sha256":SHA,"predictions":x}
    ocr={"schema":m.OCR,"source_sha256":SHA,"authority":"DENY_ALL",
         "production_accepted":False,"stem_selected":False,
         "signed_model_origin_authenticated":False,
         "model":{"repo":m.GRANITE[0],"revision":m.GRANITE[1],
                  "pipeline_digest":SHA},
         "physical_granite_forward_batches":1,
         "ocr_engine":"tesseract","physical_ocr_calls":192,"rows":y}
    native={"schema":m.NATIVE,"source_sha256":SHA,"authority":"DENY_ALL",
            "production_accepted":False,"stem_selected":False,
            "signed_model_origin_authenticated":False,
            "model":{"repo":m.GEMMA[0],"revision":m.GEMMA[1],
                     "pipeline_digest":SHA},
            "physical_joint_encode_batches":1,
            "native_joint_text_image":True,
            "audio_tower_loaded":False,
            "train_only_private_head_parameters":769,
            "train_only_head_updates":80,"future_labels_visible":False,
            "source_token_preflight_rows":1344,
            "max_conservative_context_tokens":1600,
            "native_context_limit":8192,
            "max_image_soft_tokens_charged":1120,
            "text_tokenizer_truncation_disabled":True,
            "image_tokens_physically_verified":False,
            "rows":z}
    return orig,ocr,native,lab

def compose(payload):
    a,b,c,_=payload
    return m.compose(a,b,c,original_sha=SHA,ocr_sha="b"*64,native_sha="c"*64)

class FiveArmContract(unittest.TestCase):
    def test_complete_all_five_synthetic(self):
        result=compose(panel())
        self.assertEqual(result["authority"],"DENY_ALL")
        self.assertEqual(len(result["cases"]),64)
        self.assertEqual(set(result["cases"][0]["arms"]),set(m.ARMS))

    def test_exact_score_nonpromotion(self):
        orig,ocr,native,labels=panel()
        result=m.score(compose((orig,ocr,native,labels)),labels)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["cost_matched"])
        self.assertFalse(result["real_future_windows_available"])
        self.assertEqual(result["accuracy"]["native_multimodal"],1.0)

    def test_original_missing_text_forward(self):
        q=panel();q[0]["physical_text_forward_batches"]=0
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_original_missing_gate(self):
        q=panel();del q[0]["predictions"][0]["arms"]["train_gate"]
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_ocr_source_alias(self):
        q=panel();q[1]["source_sha256"]="z"*64
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_ocr_real_calls_required(self):
        q=panel();q[1]["physical_ocr_calls"]=0
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_ocr_bogus_model_revision(self):
        q=panel();q[1]["model"]["revision"]="d"*40
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_image_bypass(self):
        q=panel();q[2]["native_joint_text_image"]=False
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_audio_not_omitted(self):
        q=panel();q[2]["audio_tower_loaded"]=True
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_zero_optimizer_steps(self):
        q=panel();q[2]["train_only_head_updates"]=0
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_training_budget_changed(self):
        q=panel();q[2]["train_only_private_head_parameters"]=2048
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_missing_real_native_forward(self):
        q=panel();q[2]["physical_joint_encode_batches"]=0
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_preflight_missing(self):
        q=panel();del q[2]["source_token_preflight_rows"]
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_partial_preflight_denied(self):
        q=panel();q[2]["source_token_preflight_rows"]=1343
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_non_conservative_image_charge_denied(self):
        q=panel();q[2]["max_image_soft_tokens_charged"]=280
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_falsely_verified_media_denied(self):
        q=panel();q[2]["image_tokens_physically_verified"]=True
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_truncated_text_claim_denied(self):
        q=panel();q[2]["text_tokenizer_truncation_disabled"]=False
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_native_context_overflow_denied(self):
        q=panel();q[2]["max_conservative_context_tokens"]=8193
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_duplicate_native_id(self):
        q=panel();q[2]["rows"][0]["id"]=q[2]["rows"][1]["id"]
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_wrong_ocr_group(self):
        q=panel();q[1]["rows"][0]["group"]="e"*64
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_extra_label_payload_in_prediction(self):
        q=panel();q[2]["rows"][0]["label"]=0
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_forged_production(self):
        q=panel();q[1]["production_accepted"]=True
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_future_truth_claim(self):
        q=panel();q[2]["future_labels_visible"]=True
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_missing_native_row(self):
        q=panel();q[2]["rows"].pop()
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_bad_probability(self):
        q=panel();q[1]["rows"][0]["probabilities"]=[0,0,0,0]
        with self.assertRaises(m.FiveArmError):compose(q)

    def test_score_reject_wrong_group(self):
        q=panel();doc=compose(q)
        q[3][0]["group"]="f"*64
        with self.assertRaises(m.FiveArmError):m.score(doc,q[3])

    def test_score_reject_missing_target(self):
        q=panel();doc=compose(q)
        with self.assertRaises(m.FiveArmError):m.score(doc,q[3][1:])

    def test_score_reject_future_forgery(self):
        q=panel();doc=compose(q);doc["cohort"]="future1"
        with self.assertRaises(m.FiveArmError):m.score(doc,q[3])

    def test_score_requires_exact_arms(self):
        q=panel();doc=compose(q)
        del doc["cases"][0]["arms"]["ocr_text"]
        with self.assertRaises(m.FiveArmError):m.score(doc,q[3])

    def test_score_reject_promotion(self):
        q=panel();doc=compose(q);doc["stem_winner"]="native"
        with self.assertRaises(m.FiveArmError):m.score(doc,q[3])

    def test_exact_p_and_holm(self):
        self.assertEqual(m.exact_p(0,0),1.0)
        self.assertEqual(m.exact_p(14,7),0.18924713134765625)
        self.assertEqual(m.exact_p(4,0),.125)

    def test_duplicate_key_json(self):
        with self.assertRaises(m.FiveArmError):
            m.loads(b'{"a":1,"a":2}')

    def test_bool_probability(self):
        with self.assertRaises(m.FiveArmError):
            m.probs([True,0,0,0])

    def test_nonfinite_overflow(self):
        with self.assertRaises(m.FiveArmError):
            m.loads(b'{"p":1e999}')

if __name__=="__main__":
    unittest.main()
