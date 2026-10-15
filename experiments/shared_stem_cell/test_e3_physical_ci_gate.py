"""Adversarial CPU-only contract tests: fixtures are synthetic, not pretrained results."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from e3_physical_ci_gate import ARMS, DATASET_REVISION, DINO, GRANITE, PhysicalGateError, digest, inspect, main

SHA = "a" * 64
HEAD = "b" * 40


def make():
    source = {"source_sha256": SHA, "fit_labels_sha256": "c" * 64,
              "private_test_labels_sha256": "d" * 64, "dataset_revision": DATASET_REVISION}
    def model(m):
        return {"repo": m[0], "revision": m[1], "sha256": SHA}
    rows = [{"id":f"test-{i}","arms":{a:[0.1,0.2,0.3,0.4] for a in ARMS}}
            for i in range(64)]
    pred = {"schema":"hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions",
            "source_sha256": SHA, "fit_labels_sha256": "c"*64, "arms":list(ARMS),
            "stem_model":model(GRANITE), "vision_model":model(DINO),
            "physical_text_forward_batches":1,"physical_vision_forward_batches":1,
            "fit":{"private_cell_head_parameters":769,"cell_optimizer_updates":80,
                   "train_cases":96,"calibration_cases":32,"holdout_cases":64},
            "held_labels_visible_to_inference":False,"production_accepted":False,
            "independent_ground_truth_observer":False, "predictions":rows}
    metrics = {a:{"cases":64,"correct":16,"accuracy":0.25,
                  "brier_4class_mean":0.1,"nll":1.3} for a in ARMS}
    review = {"schema":"hepta.e3-granite-dinov2-scienceqa.v1.independent-heldout-review",
              "source_sha256":SHA,"holdout_targets_sha256":"d"*64,
              "original_heldout_cases":64,"arms":metrics,
              "external_ground_truth_independent_owner":False,
              "visual_necessity_ground_truth_adjudicated":False,
              "statistical_selection_authorized":False,"stem_winner":None,
              "production_accepted":False,"authority":"DENY_ALL"}
    return source,pred,review


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def check(state, prediction_raw=None, review_raw=None, source_head=HEAD, seal_override=None):
    source,pred,review=state
    raw=prediction_raw if prediction_raw is not None else encode(pred)
    review["sealed_predictions_sha256"] = digest(raw)
    seal = seal_override if seal_override is not None else digest(raw).encode() + b"  predictions.json\n"
    return inspect(encode(source),raw,seal,review_raw if review_raw is not None else encode(review),source_head=source_head)


class TestPhysicalGate(unittest.TestCase):
    def test_synthetic_positive_non_authorizing(self):
        value=check(make())
        self.assertEqual(value["authority"],"DENY_ALL")
        self.assertIsNone(value["stem_winner"])
        self.assertFalse(value["signed_model_origin_authenticated"])

    def test_requires_trusted_exact_source_head_shape(self):
        with self.assertRaises(PhysicalGateError):check(make(),source_head="bad")

    def test_reject_missing_image_forward(self):
        state=make();state[1]["physical_vision_forward_batches"]=0
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_bool_forward(self):
        state=make();state[1]["physical_text_forward_batches"]=True
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_unpinned_model_revision(self):
        state=make();state[1]["vision_model"]["revision"]="0"*40
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_forged_production_claim(self):
        state=make();state[2]["production_accepted"]=True
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_ground_truth_claim(self):
        state=make();state[2]["external_ground_truth_independent_owner"]=True
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_false_visual_necessity(self):
        state=make();state[2]["visual_necessity_ground_truth_adjudicated"]=True
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_stem_winner(self):
        state=make();state[2]["stem_winner"]="Granite97"
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_changed_original_label_digest(self):
        state=make();state[2]["holdout_targets_sha256"]="f"*64
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_missing_arm(self):
        state=make();del state[2]["arms"]["image_masked"]
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_swapped_pred_seal(self):
        with self.assertRaises(PhysicalGateError):check(make(),seal_override=b"0"*64)

    def test_reject_misaligned_pred_review(self):
        state=make();state[2]["sealed_predictions_sha256"]="f"*64
        sr,pr,rr=state
        with self.assertRaises(PhysicalGateError):inspect(encode(sr),encode(pr),
                        (digest(encode(pr))+"  predictions.json").encode(),encode(rr),source_head=HEAD)

    def test_reject_optimization_hidden_flag(self):
        state=make();state[1]["fit"]["cell_optimizer_updates"]=0
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_modified_image_mask_control(self):
        state=make();state[1]["predictions"][0]["arms"]["image_masked"]=[0.4,0.3,0.2,0.1]
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_nonfinite_float_json(self):
        state=make();source,pred,review=state
        raw=encode(pred).replace(b'0.4',b'1e999',1)
        with self.assertRaises(PhysicalGateError):check(state,prediction_raw=raw)

    def test_reject_duplicate_key_json(self):
        state=make();source,pred,review=state
        raw=encode(pred).replace(b'"arms":',b'"arms":[],"arms":',1)
        with self.assertRaises(PhysicalGateError):check(state,prediction_raw=raw)

    def test_reject_bool_metric(self):
        state=make();state[2]["arms"]["text_only"]["correct"]=True
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_missing_predictions(self):
        state=make();state[1]["predictions"]=[]
        with self.assertRaises(PhysicalGateError):check(state)

    def test_reject_unvalidated_scores(self):
        state=make();state[2]["arms"]["train_gate"]["accuracy"]=0.999
        with self.assertRaises(PhysicalGateError):check(state)


if __name__ == "__main__":
    unittest.main()
