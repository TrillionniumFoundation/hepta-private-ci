"""Synthetic (not pretrained) real-schema admission negative controls."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import public_q24_independent_cases as bridge


def h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture(root: Path):
    """Physically create 96 synthetic 768D vectors; only mechanics can pass."""
    import torch
    from safetensors.torch import save_file
    torch.set_num_threads(1)
    torch.manual_seed(7347)
    root.mkdir(exist_ok=False)
    data = {"fit": torch.randn((64,768),dtype=torch.float32) * 0.3,
            "heldout": torch.randn((32,768),dtype=torch.float32) * 0.3}
    mean = data["fit"].mean(dim=0)
    _, singular, vh = torch.linalg.svd(data["fit"]-mean,full_matrices=False)
    proj=vh[:32].T.contiguous()
    for i in range(32):
        idx=int(torch.argmax(torch.abs(proj[:,i])).item())
        if proj[idx,i].item() < 0:
            proj[:,i].neg_()
    centered = (data["fit"]-mean) @ proj
    scale=torch.sqrt(torch.mean(centered.square(),dim=0)).clamp_min(1e-6)
    shapes={"center":mean.contiguous(),"components":proj,"scale":scale}
    quant={}
    for part in ("fit","heldout"):
        logits=((data[part]-mean)@proj)/scale
        quant[part]=torch.round(logits.to(torch.float64).clamp(-8,8)*bridge.Q).to(torch.int64)
    save_file(data,str(root/"pooled-f32.safetensors"))
    save_file(shapes,str(root/"train-only-pca32.safetensors"))
    save_file(quant,str(root/"feature-q24.safetensors"))
    registry={
        "schema":bridge.REGISTRY_SCHEMA, "input_id":h(b"synthetic-input"),
        "dataset_revision":bridge.FROZEN_BANKING77,
        "no_heldout_labels_in_feature_snapshot":True,
        "no_future_window_claim":True,
        "original_selected_v1_a0_verified":False,
        "fit_count":64,"heldout_count":32,
        "fit":[{"id":f"fit:{i:064x}","label":i%4} for i in range(64)],
        "heldout":[{"id":f"heldout:{i:064x}"} for i in range(32)],
    }
    (root/"case-registry.json").write_text(json.dumps(registry))
    files={
        name:{"sha256":h((root/name).read_bytes()),
              "bytes":(root/name).stat().st_size}
        for name in bridge.FILES
    }
    record={
        "schema":bridge.SOURCE_SCHEMA,
        "authority":"DENY_ALL","decision":"NO_MODEL_PROMOTION",
        "source_class":"SYNTHETIC_UNIT_FIXTURE_ONLY",
        "source_identity":None,
        "input_id":registry["input_id"],
        "split_counts":{"fit":64,"heldout":32},
        "frozen_feature_width":768,
        "q24_feature_width":32,
        "projection_fitted_on":"UNLABELED_FIT_FEATURES_ONLY",
        "physical_encoder_forward_calls_this_snapshot":96,
        "files":files,
    }
    for flag in (
        "production_qualification","ndu_eligible",
        "projection_trained_with_test_features_or_labels",
        "heldout_predictions_or_labels_scored","future_window_utility_verified",
        "no_change_production_v1_baseline_verified",
        "source_group_or_temporal_independence_verified",
    ):
        record[flag]=False
    (root/"SEALED.json").write_text(json.dumps(record,sort_keys=True))


@unittest.skipUnless(
    os.environ.get("HEPTA_NEURON_PHYSICAL_TESTS") == "1",
    "pinned CPU Torch/safetensors native research suite only",
)
class PublicQ24IndependentCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root=Path(cls.temporary.name)/"source"
        fixture(cls.root)

    def test_exact_frozen_quantized_inputs_do_not_claim_future_or_training(self):
        cases=bridge.accept_public_snapshot(self.root,synthetic_fixture_only=True)
        self.assertEqual(cases["source_class"],"SYNTHETIC_UNIT_FIXTURE_ONLY")
        self.assertEqual(cases["classification_unit"],
                         "ONE_INDEPENDENT_UTTERANCE_PER_CASE_NOT_TIMESERIES")
        self.assertEqual(len(cases["train"]),64)
        self.assertEqual(len(cases["heldout"]),32)
        self.assertTrue(all(set(row)=={"case_id","feature_q24","class_label"}
                            for row in cases["train"]))
        self.assertTrue(all(set(row)=={"case_id","feature_q24"}
                            for row in cases["heldout"]))
        self.assertFalse(cases["equivalent_to_hepta_temporal_training_input"])
        self.assertFalse(cases["future_window_utility_verified"])
        self.assertFalse(cases["production_qualification"])
        self.assertFalse(cases["ndu_eligible"])

    def test_synthetic_fixture_cannot_be_used_as_real_pretrained_source(self):
        with self.assertRaisesRegex(bridge.Invalid,"real"):
            bridge.accept_public_snapshot(self.root)

    def altered(self, *, filename, mutator):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            candidate=Path(tmp)/"copy"
            shutil.copytree(self.root,candidate)
            path=candidate/filename
            mutator(path)
            envelope=candidate/"SEALED.json"
            seal=json.loads(envelope.read_text())
            raw=path.read_bytes()
            seal["files"][filename]["sha256"]=h(raw)
            seal["files"][filename]["bytes"]=len(raw)
            envelope.write_text(json.dumps(seal))
            return bridge.accept_public_snapshot(candidate,synthetic_fixture_only=True)

    def test_hidden_official_test_labels_refused_despite_rehashed_seal(self):
        def mutate(path):
            obj=json.loads(path.read_text())
            obj["heldout"][0]["label"]=0
            path.write_text(json.dumps(obj))
        with self.assertRaisesRegex(bridge.Invalid,"heldout"):
            self.altered(filename="case-registry.json",mutator=mutate)

    def test_changed_projection_refused_despite_rehashed_seal(self):
        def mutate(path):
            from safetensors.torch import load_file,save_file
            values=load_file(str(path))
            values["components"][0,0]+=0.1
            save_file(values,str(path))
        with self.assertRaisesRegex(bridge.Invalid,"PCA32"):
            self.altered(filename="train-only-pca32.safetensors",mutator=mutate)

    def test_corrupted_actual_q24_feature_refused(self):
        def mutate(path):
            from safetensors.torch import load_file,save_file
            values=load_file(str(path))
            values["heldout"][0,0]+=1
            save_file(values,str(path))
        with self.assertRaisesRegex(bridge.Invalid,"Q24 feature replay"):
            self.altered(filename="feature-q24.safetensors",mutator=mutate)

    def test_source_claim_wrong_model_or_signed_authority_refused(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            copied=Path(tmp)/"copy"
            shutil.copytree(self.root,copied)
            receipt=copied/"SEALED.json"
            value=json.loads(receipt.read_text())
            value["production_qualification"]=True
            receipt.write_text(json.dumps(value))
            with self.assertRaisesRegex(bridge.Invalid,"authority"):
                bridge.accept_public_snapshot(copied,synthetic_fixture_only=True)

    def test_reject_crafted_duplicate_keys(self):
        with self.assertRaisesRegex(bridge.Invalid,"duplicate"):
            bridge.strict_json(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(bridge.Invalid,"nonfinite"):
            bridge.strict_json(b'{"a":1e999}')

    def test_two_identical_trials_preserve_same_input_hash(self):
        left=bridge.accept_public_snapshot(self.root,synthetic_fixture_only=True)
        right=bridge.accept_public_snapshot(self.root,synthetic_fixture_only=True)
        self.assertEqual(left,right)
        self.assertEqual(left["frozen_source_input_id"],h(b"synthetic-input"))

if __name__ == "__main__":
    unittest.main()
