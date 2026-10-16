#!/usr/bin/env python3
"""Contract and physical fixture tests. Fake features are NOT pretrained evidence."""
from __future__ import annotations
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from banking77_material import INTENTS, prepare
from stem_q24_original_bridge_v1 import produce, fit_only_pca, q24, H, Q, read
from stem_q24_original_review_v1 import review, document


def original_shape_fixture():
    def csv_rows(prefix):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(("text","category"))
        for category in INTENTS:
            for i in range(20):
                writer.writerow((f"{prefix} generated sample {category} {i}",category))
        return output.getvalue().encode()
    inputs, observer, _ = prepare(csv_rows("fit"), csv_rows("heldout"))
    return inputs, observer


class SyntheticBackend:
    """Explicit non-HF physical fixture with true 64D numeric forward calls."""
    calls = 0
    receipt = {"snapshot_sha256": None, "pretrained": False}
    verified = False

    def encode(self, row):
        self.calls += 1
        seed = int(hashlib.sha256(row["state"].encode()).hexdigest()[:16], 16)
        x = np.random.default_rng(seed).standard_normal(64).astype(np.float32)
        return torch.from_numpy(x), 8

    def reverify(self):
        self.verified = True


class Q24OriginalBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs, cls.observer = original_shape_fixture()
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name) / "bridge"
        cls.model = SyntheticBackend()
        cls.receipt = produce(cls.inputs, cls.model, cls.root, steps=2)
        cls.result = review(cls.root, cls.inputs, cls.observer)

    def clone(self):
        import shutil
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        target = Path(temp.name) / "bridge"
        shutil.copytree(self.root, target)
        return target

    def test_full_source_population_one_shared_encoder_forward(self):
        self.assertEqual(self.model.calls, 96)
        self.assertTrue(self.model.verified)
        self.assertEqual(self.receipt["encoder_forward_count"], 96)
        self.assertEqual(self.receipt["source_class"], "FIXTURE")
        self.assertEqual(self.result["source_class"], "FIXTURE")
        self.assertEqual(self.result["decision"], "HOLD_NO_GO")
        self.assertFalse(self.result["production_authorized"])

    def test_original_tensor_and_independent_numpy_all_cells(self):
        self.assertTrue(self.result["q24_all_96_numerically_recomputed"])
        self.assertTrue(self.result["independent_numpy_96_arm_predictions"])
        self.assertEqual(set(self.result["score"]), {"initial","learned","cyclic_wrong_labels"})
        self.assertEqual([self.result["score"][k]["count"] for k in
                          ("initial","learned","cyclic_wrong_labels")], [32]*3)
        self.assertEqual(self.receipt["cell_params_each_arm"], 264)

    def test_training_only_frozen_projector(self):
        x = np.random.default_rng(7347).normal(size=(64, 64))
        mean, axes, scale = fit_only_pca(x)
        self.assertEqual(axes.shape, (64,32))
        held = np.random.default_rng(22).normal(size=(32,64))
        changed = held.copy(); changed[0,0] += 100
        self.assertTrue(np.array_equal(axes, fit_only_pca(x)[1]))
        self.assertFalse(np.array_equal(q24(held,mean,axes,scale)[0],
                                        q24(changed,mean,axes,scale)[0]))

    def test_signed_q24_clip_bounds(self):
        x = np.random.default_rng(4).normal(size=(64,64))
        mean, basis, scale = fit_only_pca(x)
        foreign = np.ones((2,64),dtype=np.float64)*1_000_000
        result, clipped = q24(foreign,mean,basis,scale)
        self.assertGreater(clipped,0)
        self.assertTrue(np.all(result <= H) and np.all(result >= -H))
        self.assertTrue(np.issubdtype(result.dtype,np.signedinteger))

    def test_missing_private_file(self):
        root=self.clone()
        (root/"initial.safetensors").unlink()
        with self.assertRaises((ValueError,FileNotFoundError)):
            review(root,self.inputs,self.observer)

    def test_rewritten_q24_and_resealed_hash_still_rejects(self):
        root=self.clone()
        path=root/"private-q24.json"
        rows=read(path)
        rows["heldout"][0]["feature_q24"][0] += 1
        path.write_text(json.dumps(rows,sort_keys=True),encoding="utf8")
        receipt=read(root/"PRODUCER.json")
        receipt["private_files"][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        (root/"PRODUCER.json").write_text(json.dumps(receipt),encoding="utf8")
        with self.assertRaisesRegex(ValueError,"Q24 outputs differ"):
            review(root,self.inputs,self.observer)

    def test_rewritten_pca_and_resealed_hash_still_rejects(self):
        from safetensors.numpy import load_file,save_file
        root=self.clone(); path=root/"private-pca.safetensors"
        tensors=load_file(str(path))
        tensors["axes"][0,0] += .05
        save_file(tensors,str(path))
        receipt=read(root/"PRODUCER.json")
        receipt["private_files"][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        (root/"PRODUCER.json").write_text(json.dumps(receipt),encoding="utf8")
        with self.assertRaisesRegex(ValueError,"PCA not derived"):
            review(root,self.inputs,self.observer)

    def test_false_prod_authorization_rejected(self):
        root=self.clone()
        report=read(root/"PRODUCER.json")
        report["production_authorized"]=True
        (root/"PRODUCER.json").write_text(json.dumps(report),encoding="utf8")
        with self.assertRaisesRegex(ValueError,"false original-forward"):
            review(root,self.inputs,self.observer)

    def test_counterfeit_model_original_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            fake = SyntheticBackend()
            with self.assertRaises((KeyError,ValueError)):
                produce(self.inputs,fake,Path(td)/"cannot_claim_pretrained",
                        source_class="ORIGINAL_PUBLIC_MODERNBERT")
            self.assertEqual(fake.calls,0)

    def test_heldout_labels_cannot_enter_training_input(self):
        bad=copy.deepcopy(self.inputs)
        bad["heldout"][0]["label"]=0
        with tempfile.TemporaryDirectory() as td:
            fake=SyntheticBackend()
            with self.assertRaises(ValueError):
                produce(bad,fake,Path(td)/"invalid")
            self.assertEqual(fake.calls,0)

    def test_observer_labels_rebound_to_wrong_id_rejected(self):
        wrong=copy.deepcopy(self.observer)
        wrong["rows"][0]["id"]=wrong["rows"][1]["id"]
        with self.assertRaisesRegex(ValueError,"mismatched publisher"):
            review(self.root,self.inputs,wrong)

    def test_observer_incomplete_denominator_rejected(self):
        wrong=copy.deepcopy(self.observer)
        wrong["rows"].pop()
        with self.assertRaisesRegex(ValueError,"external heldout"):
            review(self.root,self.inputs,wrong)

    def test_source_id_replacement_rejected(self):
        bad=copy.deepcopy(self.inputs)
        bad["heldout"][0]["id"]="fake"
        with self.assertRaisesRegex(ValueError,"wrong source"):
            review(self.root,bad,self.observer)

    def test_double_json_key_denial(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"a.json"
            path.write_text('{"authority":"DENY_ALL","authority":"PROD"}')
            with self.assertRaisesRegex(ValueError,"duplicate JSON"):
                document(path)

    def test_nonfinite_json_denial(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"a.json"
            path.write_text('{"x":NaN}')
            with self.assertRaises(ValueError):
                document(path)

    def test_pretrained_gain_not_inferred_from_synthetic(self):
        self.assertFalse(self.result["future_task_gain_verified"])
        self.assertFalse(self.result["independent_issuer_verified"])
        self.assertFalse(self.result["stem_winner_verified"])
        self.assertFalse(self.result["native_rust_q24_executed"])
        self.assertEqual(self.result["authority"],"DENY_ALL")


if __name__ == "__main__":
    unittest.main()
