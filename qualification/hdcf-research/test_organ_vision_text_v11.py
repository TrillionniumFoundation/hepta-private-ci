"""Adversarial original source and model-feature replay tests. No test-label SGD."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import numpy as np
import organ_vision_text_v11 as m

SOURCE=os.environ.get("HDCF_ORIGINAL_SOURCE_ZIP","")
FEATURES=os.environ.get("HDCF_ORIGINAL_FEATURE_ZIP","")
TARGETS=os.environ.get("HDCF_ORIGINAL_TARGET_ZIP","")

class OriginalStrictV11(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # No fallback to unverified/random feature fixtures on hosted execution.
        for path in (SOURCE,FEATURES,TARGETS):
            if not Path(path).is_file():
                raise RuntimeError("all three source-original immutable ZIPs are mandatory")
        cls.data=m.load_original(SOURCE,FEATURES)
        cls.seal=m.run_fit(SOURCE,FEATURES)
        cls.review=m.score_postseal(cls.seal,SOURCE,FEATURES,TARGETS)

    def test_original_three_way_source_truth(self):
        self.assertEqual(len(self.data["train"]),36)
        self.assertEqual(len(self.data["held"]),24)
        self.assertEqual(self.data["xtrain"].shape,(36,384))
        self.assertEqual(self.data["xtest"].shape,(24,384))
        self.assertEqual(dict(zip(*np.unique(self.data["ytrain"],return_counts=True))),{0:12,1:12,2:12})
        self.assertEqual(set(self.data["teacher_text_digests"]),set(m.CLASSES))
        self.assertTrue(all("target" not in r and "class_label" not in r for r in self.data["held"]))

    def test_original_only_real_staged(self):
        self.assertEqual(self.review["disposition"],"HOLD_NO_GO_DENY_ALL")
        self.assertFalse(self.review["general_multimodal_capability_verified"])
        self.assertFalse(self.review["organ_benefit_verified"])
        self.assertFalse(self.review["cell_split_benefit_verified"])
        self.assertFalse(self.review["production_authorized"])
        self.assertEqual(self.seal["manifest"]["original_model_new_forwards"],0)
        self.assertFalse(self.seal["manifest"]["blind_labels_in_fit"])

    def test_strong_frozen_original_pretrained_control(self):
        self.assertEqual(self.review["arm_scores"]["original_frozen_visual_prototype"],{"correct":20,"n":24})
        self.assertEqual(self.review["arm_scores"]["organ_shared_one_touch"]["correct"],20)
        self.assertEqual(self.review["arm_scores"]["organ_split"]["correct"],19)
        self.assertEqual(self.review["paired"]["organ_split_vs_organ_shared"]["candidate_only"],1)
        self.assertEqual(self.review["paired"]["organ_split_vs_organ_shared"]["control_only"],2)

    def test_original_real_text_vs_matching_null(self):
        self.assertEqual(self.review["arm_scores"]["trained_text_organ_cosine"]["correct"],20)
        self.assertEqual(self.review["arm_scores"]["trained_null_organ_cosine"]["correct"],20)
        self.assertEqual(self.review["paired"]["text_organ_cosine_vs_null_cosine"]["candidate_only"],0)
        self.assertFalse(self.review["independent_source_issuer"])

    def test_full_head_arms_matched_steps_and_touches(self):
        arms=self.seal["manifest"]["head_work"]
        for arm in ("organ_shared_one_touch","organ_split","raw_shared_one_touch","null_organ_shared_one_touch"):
            self.assertEqual(arms[arm]["steps"],m.HEAD_STEPS)
            self.assertEqual(arms[arm]["parameter_touches"],m.HEAD_STEPS*385*3)
            self.assertEqual(arms[arm]["parameters_total"],2310)
        self.assertEqual(arms["organ_swapped"]["steps"],0)
        for key in ("text","orthogonal_null"):
            self.assertEqual(self.seal["manifest"]["organ_work"][key]["parameters"],6144)
            self.assertEqual(self.seal["manifest"]["organ_work"][key]["steps"],160)

    def test_reproducible_real_logits(self):
        second=m.run_fit(SOURCE,FEATURES)
        self.assertEqual(second["predictions"],self.seal["predictions"])
        for arm in ("text","orthogonal_null"):
            self.assertEqual(second["manifest"]["organ_work"][arm]["weights_sha256"],
                             self.seal["manifest"]["organ_work"][arm]["weights_sha256"])

    def test_archive_outer_sha_tamper_denied(self):
        with tempfile.TemporaryDirectory() as td:
            tampered=Path(td)/"tampered.zip"
            tampered.write_bytes(Path(FEATURES).read_bytes()+b"evil")
            with self.assertRaises(m.Reject):
                m.load_original(SOURCE,str(tampered))

    def test_missing_original_archive_denied(self):
        with self.assertRaises(m.Reject):
            m.load_original(SOURCE,"/nonexistent/original.zip")

    def test_late_label_archive_tamper_denied(self):
        with tempfile.TemporaryDirectory() as td:
            tampered=Path(td)/"targets.zip"
            raw=bytearray(Path(TARGETS).read_bytes());raw[-10] ^= 0x1;tampered.write_bytes(raw)
            with self.assertRaises(m.Reject):
                m.score_postseal(self.seal,SOURCE,FEATURES,str(tampered))

    def invalid_seal(self, fn):
        s=copy.deepcopy(self.seal)
        fn(s)
        with self.assertRaises(m.Reject):
            m.score_postseal(s,SOURCE,FEATURES,TARGETS)

    def test_modified_probability_denied(self):
        self.invalid_seal(lambda s:s["predictions"][0]["probabilities"]["organ_split"].__setitem__(0,0.1))

    def test_changed_case_id_denied(self):
        self.invalid_seal(lambda s:s["predictions"][0].__setitem__("id","fake-case"))

    def test_cross_scope_event_denied_even_resealed(self):
        def fn(s):
            s["predictions"][0]["family"]="untrusted-scope"
            s["seal_sha256"]=m.dig({k:v for k,v in s.items() if k!="seal_sha256"})
        self.invalid_seal(fn)

    def test_changed_model_revision_denied_even_resealed(self):
        def fn(s):
            s["manifest"]["dinov2_revision"]="0"*40
            s["seal_sha256"]=m.dig({k:v for k,v in s.items() if k!="seal_sha256"})
        self.invalid_seal(fn)

    def test_false_production_authorization_denied_even_resealed(self):
        def fn(s):
            s["manifest"]["production_authorized"]=True
            s["seal_sha256"]=m.dig({k:v for k,v in s.items() if k!="seal_sha256"})
        self.invalid_seal(fn)

    def test_false_time_window_claim_denied_even_resealed(self):
        def fn(s):
            s["manifest"]["future_time_outcome"]=True
            s["seal_sha256"]=m.dig({k:v for k,v in s.items() if k!="seal_sha256"})
        self.invalid_seal(fn)

    def test_fake_training_touches_denied_even_resealed(self):
        def fn(s):
            s["manifest"]["head_work"]["organ_split"]["parameter_touches"]-=1
            s["seal_sha256"]=m.dig({k:v for k,v in s.items() if k!="seal_sha256"})
        self.invalid_seal(fn)

    def test_duplicate_prediction_case_denied_even_resealed(self):
        def fn(s):
            s["predictions"][1]["id"]=s["predictions"][0]["id"]
            s["seal_sha256"]=m.dig({k:v for k,v in s.items() if k!="seal_sha256"})
        self.invalid_seal(fn)

    def test_invalid_probability_denied_even_resealed(self):
        def fn(s):
            s["predictions"][0]["probabilities"]["organ_split"]=[0.7,0.7,0.7]
            s["seal_sha256"]=m.dig({k:v for k,v in s.items() if k!="seal_sha256"})
        self.invalid_seal(fn)

    def test_random_target_teacher_geometry_unchanged(self):
        p=self.data["teacher"]
        rng=np.random.default_rng(m.SEED)
        perm=rng.permutation(m.WIDTH)
        signs=rng.choice(np.array([-1.,1.]),m.WIDTH)
        null=p[:,perm]*signs
        self.assertTrue(np.allclose(p@p.T,null@null.T,rtol=0,atol=1e-12))

    def test_gradient_matches_finite_difference(self):
        rng=np.random.default_rng(45)
        x=m.norm(rng.normal(size=(6,m.WIDTH)))
        proto=m.norm(rng.normal(size=(3,m.WIDTH)))
        A=rng.normal(0,.01,(m.WIDTH,m.RANK)); B=rng.normal(0,.01,(m.RANK,m.WIDTH))
        y=np.array([0,1,2,0,1,2])
        loss,dA,dB=m._loss_and_grad(x,y,proto,A,B)
        self.assertTrue(np.isfinite(loss))
        for name, tensor, gradient, positions in (("A",A,dA,((0,0),(17,6),(300,2))),
                                                  ("B",B,dB,((0,0),(7,91),(5,380)))):
            for i,j in positions:
                h=1e-5
                tensor[i,j]+=h;plus=m._loss_and_grad(x,y,proto,A,B)[0]
                tensor[i,j]-=2*h;minus=m._loss_and_grad(x,y,proto,A,B)[0]
                tensor[i,j]+=h
                self.assertAlmostEqual((plus-minus)/(2*h),gradient[i,j],delta=1e-6,msg=(name,i,j))

    def test_single_writer_output_mode_private(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"review.json"
            m.secure_write(p,self.review)
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):m.secure_write(p,self.review)

    def test_original_trained_null_not_semantic_cert(self):
        self.assertFalse(self.review["organ_benefit_verified"])
        self.assertEqual(self.review["paired"]["text_organ_shared_vs_null_organ_shared"]["nominal_case_level_exact_p"],1.0)
        self.assertFalse(self.seal["manifest"]["total_lifecycle_cost_attested"])

if __name__=="__main__":
    unittest.main()
