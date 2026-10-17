"""CPU-only, explicitly synthetic Tensor and hard-fail original identity tests.

No test exercises a real pretrained model or claims task efficacy.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import save_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
import encoder_centroid_v7 as producer
import independent_encoder_centroid_v7 as audit


def fake_source():
    labels=[i % 4 for i in range(64)]
    return {"schema":"synthetic-not-publisher-source",
            "train":[{"case_id":f"fit:{i:064x}","label":labels[i],
                      "source_sha256":f"{i:064x}","text":f"fit sample {i}"}
                     for i in range(64)],
            "heldout":[{"case_id":f"heldout:{i+100:064x}",
                        "source_sha256":f"{i+100:064x}","text":f"heldout {i}"}
                       for i in range(32)]}


def fake_tensor():
    rng=torch.Generator().manual_seed(37)
    z=torch.randn((96,384),generator=rng)
    for i in range(64):
        z[i, (i%4)*32] += 3
    for i in range(32):
        z[64+i, (i%4)*32] += 3
    return torch.nn.functional.normalize(z,dim=-1).contiguous().float()


class V7OriginalCentroidTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=fake_source()
        cls.features=fake_tensor()
        with patch.object(producer.frozen,"validate_source"):
            cls.output=producer.calibrate(cls.features,cls.source)

    def test_genuine_torch_projection_and_fold_control(self):
        self.assertEqual(len(self.output["t1"]),32)
        self.assertEqual(len(self.output["calibrated"]),32)
        self.assertEqual([self.output["fit_folds"].count(k) for k in range(4)],[16]*4)
        self.assertIn(self.output["selected_temperature"],producer.GRID)
        self.assertNotEqual(self.output["calibrated"],self.output["t1"])
        self.assertTrue(all(abs(sum(x)-1)<1e-5 for x in self.output["calibrated"]))

    def test_future_features_do_not_tune_temperature(self):
        changed=self.features.clone()
        changed[64:]=torch.nn.functional.normalize(torch.randn_like(changed[64:]),dim=-1)
        with patch.object(producer.frozen,"validate_source"):
            alt=producer.calibrate(changed,self.source)
        self.assertEqual(self.output["cv_brier_by_temp"],alt["cv_brier_by_temp"])
        self.assertEqual(self.output["selected_temperature"],alt["selected_temperature"])

    def test_original_encoder_dimensions_and_nonfinite_rejected(self):
        for change in (self.features[:95],self.features[:,:32],self.features.double()):
            with patch.object(producer.frozen,"validate_source"):
                with self.assertRaisesRegex(ValueError,"incompatible original feature"):
                    producer.calibrate(change,self.source)
        damaged=self.features.clone()
        damaged[1,2]=float("nan")
        with patch.object(producer.frozen,"validate_source"):
            with self.assertRaisesRegex(ValueError,"incompatible original feature"):
                producer.calibrate(damaged,self.source)

    def test_logits_require_four_represented_train_classes(self):
        with self.assertRaisesRegex(ValueError,"empty centroid"):
            producer._logits(self.features[:16],[0]*16,self.features[64:])

    def make_receipt(self, feature_file):
        source=self.source
        mat={"candidates":{"granite47":{"repo":"ibm/research","revision":"a"*40,"weight_sha256":"b"*64}}}
        r={"schema":audit.SCHEMA,"source_plan_sha256":audit.SOURCE_SHA,
           "candidate":"granite47", "model_repo":mat["candidates"]["granite47"]["repo"],
           "model_revision":"a"*40,"weight_sha256":"b"*64,
           "model_material_sha256":audit.sha(audit.canonical(mat)),
           "features_sha256":audit.sha(Path(feature_file).read_bytes()),
           "feature_dtype":"float32","feature_rows":96,"feature_width":384,
           "fit_ids":[x["case_id"] for x in source["train"]],
           "heldout_ids":[x["case_id"] for x in source["heldout"]],
           "fold_salt":audit.FOLD_SALT,"grid":list(audit.GRID),
           "fit_folds":self.output["fit_folds"],
           "cv_brier_by_temp":self.output["cv_brier_by_temp"],
           "selected_temperature":self.output["selected_temperature"],
           "rows":[{"case_id":item["case_id"],"source_sha256":item["source_sha256"],
                    "scores":{"original_centroid_t1":self.output["t1"][i],
                              "train_calibrated_centroid":self.output["calibrated"][i]}}
                   for i,item in enumerate(source["heldout"])],
           "cost":{"encoder_forward_batches":6,"physical_encoder_sequences":96,
                   "model_download_load_wall_seconds":1.2,"feature_encode_wall_seconds":2.0,
                   "elapsed_wall_seconds":3.8,"elapsed_cpu_seconds":2.5,
                   "maxrss_bytes":250000000,"energy_joules":None,"p99_latency_ms":None},
           "publisher_heldout_label_access":False,"source_independent_families":1,
           "future_windows":0,"physical_claim_unattested":True,
           "production_authorized":False,"stem_winner_verified":False,
           "disposition":"HOLD_NO_GO","authority":"DENY_ALL"}
        old={"candidate":"granite47","source_plan_sha256":audit.SOURCE_SHA,
             "rows":[{"case_id":item["case_id"],
                      "scores":{"centroid":self.output["t1"][i]}}
                     for i,item in enumerate(source["heldout"])]}
        return r,mat,old

    def test_independent_numpy_real_safetensors_replay_on_synthetic_features(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"features.safetensors"
            save_file({"features":self.features},str(p))
            receipt,mat,old=self.make_receipt(p)
            result=audit._original_replay(self.source,receipt,mat,old,p)
            self.assertTrue(result["original_t1_replays_v3"])
            self.assertEqual(result["temperature"],self.output["selected_temperature"])

    def test_tamper_expected_original_v3_predictions_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"features.safetensors"
            save_file({"features":self.features},str(p))
            receipt,mat,old=self.make_receipt(p)
            old["rows"][0]["scores"]["centroid"]=[0.9,.05,.03,.02]
            with self.assertRaisesRegex(ValueError,"independent V3 pretrained T1 drift"):
                audit._original_replay(self.source,receipt,mat,old,p)

    def test_modified_raw_tensor_or_cv_temperature_denied(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"features.safetensors"
            save_file({"features":self.features},str(p))
            receipt,mat,old=self.make_receipt(p)
            tampered=copy.deepcopy(receipt)
            tampered["selected_temperature"]=.5 if receipt["selected_temperature"]!=.5 else 32.
            with self.assertRaisesRegex(ValueError,"temperature/CV loss"):
                audit._original_replay(self.source,tampered,mat,old,p)
            p.write_bytes(p.read_bytes()+b"fake")
            with self.assertRaisesRegex(ValueError,"feature artifact byte mismatch"):
                audit._original_replay(self.source,receipt,mat,old,p)

    def test_wrong_authority_and_cost_disallowed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"features.safetensors"
            save_file({"features":self.features},str(p))
            receipt,mat,old=self.make_receipt(p)
            for change in (lambda x:x.__setitem__("production_authorized",True),
                           lambda x:x["cost"].__setitem__("p99_latency_ms",.1),
                           lambda x:x.__setitem__("publisher_heldout_label_access",True)):
                mod=copy.deepcopy(receipt)
                change(mod)
                with self.assertRaises(ValueError):
                    audit._original_replay(self.source,mod,mat,old,p)


if __name__=="__main__":
    unittest.main()
