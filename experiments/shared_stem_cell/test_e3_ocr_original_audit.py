"""Stdlib-only negative controls; fabricated source/labels, no actual OCR result."""
import copy
import json
import unittest
import e3_ocr_original_audit as a

def source_case():
    refs,ocr,labels=[],[],[]
    for i in range(64):
        rid=f"{i+1:064x}"
        group=f"{i+100:064x}"
        source=f"{i+200:064x}"
        refs.append({"id":rid,"group":group,"split":"test",
                     "source_input_sha256":source,
                     "arms":{"text_only":[.7,.1,.1,.1]}})
        ocr.append({"id":rid,"group":group,"source_input_sha256":source,
                    "probabilities":[.1,.7,.1,.1]})
        labels.append({"id":rid,"group":group,"split":"test","label":1})
    original={"schema":"hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions",
              "source_sha256":a.SOURCE_SHA,"production_accepted":False,
              "held_labels_visible_to_inference":False,
              "independent_ground_truth_observer":False,
              "physical_text_forward_batches":60,"predictions":refs}
    phys={"schema":"hepta.e3.ocr-granite-physical.v1",
          "model":{"repo":a.OCR_MODEL[0],"revision":a.OCR_MODEL[1],
                   "pipeline_digest":"a"*64},
          "source_sha256":a.SOURCE_SHA,"production_accepted":False,
          "stem_selected":False,"authority":"DENY_ALL",
          "signed_model_origin_authenticated":False,
          "ocr_engine":"tesseract","physical_ocr_calls":192,
          "ocr_nonempty_cases":110,"physical_granite_forward_batches":60,
          "actual_original_pretrained_forward_self_reported":True,"rows":ocr}
    return original,phys,labels

class IndependentOcrReview(unittest.TestCase):
    def test_strict_synthetic_positive(self):
        out=a.outcome(*source_case())
        self.assertEqual(out["correct"]["ocr_text"],64)
        self.assertEqual(out["correct"]["text_only"],0)
        self.assertTrue(out["mcnemar_two_sided_exact_unadjusted_p"] < .0001)
        self.assertEqual(out["authority"],"DENY_ALL")
        self.assertIsNone(out["stem_winner"])

    def test_wrong_ocr_source_denied(self):
        o,v,l=source_case();v["source_sha256"]="f"*64
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_wrong_original_source_denied(self):
        o,v,l=source_case();o["source_sha256"]="0"*64
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_fake_model_revision_denied(self):
        o,v,l=source_case();v["model"]["revision"]="b"*40
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_fake_forward_denied(self):
        o,v,l=source_case();v["physical_granite_forward_batches"]=0
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_missing_original_row_denied(self):
        o,v,l=source_case();o["predictions"].pop()
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_missing_ocr_row_denied(self):
        o,v,l=source_case();v["rows"].pop()
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_duplicate_ocr_id_denied(self):
        o,v,l=source_case();v["rows"][1]["id"]=v["rows"][0]["id"]
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_swapped_image_source_denied(self):
        o,v,l=source_case();v["rows"][0]["source_input_sha256"]="0"*64
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_mismatched_held_label_denied(self):
        o,v,l=source_case();l[0]["group"]="b"*64
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_held_label_before_prediction_denied(self):
        o,v,l=source_case();v["rows"][0]["label"]=1
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_fake_promotion_denied(self):
        o,v,l=source_case();v["production_accepted"]=True
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_bool_probability_denied(self):
        o,v,l=source_case();v["rows"][0]["probabilities"]=[True,0,0,0]
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_nonfinite_probability_denied(self):
        o,v,l=source_case();v["rows"][0]["probabilities"]=[float("nan"),.1,.2,.7]
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_false_census_denied(self):
        o,v,l=source_case();v["ocr_nonempty_cases"]=193
        with self.assertRaises(a.OriginalOcrError):a.outcome(o,v,l)

    def test_duplicate_json_key_denied(self):
        with self.assertRaises(a.OriginalOcrError):
            a.parse(b'{"text":1,"text":2}')

    def test_nonfinite_constant_denied(self):
        with self.assertRaises(a.OriginalOcrError):
            a.parse(b'{"text":NaN}')

if __name__=="__main__":
    unittest.main()
