"""Stock HF safetensors forward smoke on a RANDOM tiny BERT, not pretrained efficacy.

Without Transformers this suite skips locally. Hosted CI explicitly installs and
imports its pinned HF dependencies, then rejects any skips.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

import torch
from multimodal_alignment_contract import canonical, load_pinned_jsonl, sha
from multimodal_bridge import ContractError, ModalityFeature
from multimodal_real_encoder import PROFILE_SCHEMA, run_offline


def pin(value):
    return hashlib.sha256(value.encode()).hexdigest()


@unittest.skipUnless(importlib.util.find_spec("transformers"), "requires pinned hosted HF packages")
class PhysicalMaterialIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from transformers import BertConfig, BertModel, BertTokenizerFast
        cls.BertConfig, cls.BertModel, cls.BertTokenizerFast = BertConfig, BertModel, BertTokenizerFast
        torch.set_num_threads(1)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.model_root = self.root / "model"
        self.model_root.mkdir()
        with torch.random.fork_rng():
            torch.manual_seed(321)
            cfg = self.BertConfig(vocab_size=16, hidden_size=16, intermediate_size=32,
                                  num_hidden_layers=1, num_attention_heads=4,
                                  max_position_embeddings=32, hidden_dropout_prob=0.0,
                                  attention_probs_dropout_prob=0.0)
            self.model = self.BertModel(cfg).eval().requires_grad_(False)
        self.model.save_pretrained(self.model_root, safe_serialization=True)
        (self.model_root / "vocab.txt").write_text(
            "[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\n"
            "small\ntest\nreal\nencoder\ntext\nexample\nzero\none\ntwo\nthree\nfour\n")
        self.tokenizer = self.BertTokenizerFast(vocab_file=str(self.model_root / "vocab.txt"),
                                               do_lower_case=True)
        self.tokenizer.save_pretrained(self.model_root)
        inventory = {p.relative_to(self.model_root).as_posix(): sha(p.read_bytes())
                     for p in self.model_root.rglob("*") if p.is_file()}
        self.assertTrue(any(p.endswith(".safetensors") for p in inventory))
        self.profile = {"schema": PROFILE_SCHEMA, "candidate": "tiny-random-bert-not-pretrained",
                        "snapshot": {"revision": "c" * 40, "kind": "encoder", "files": inventory},
                        "expected_width": 16, "maximum_tokens": 32, "batch_size": 3,
                        "pooling": "attention-mask-mean", "normalization": "none"}
        self.profile_path = self.root / "profile.json"
        rows = []
        phrases = ["small test real encoder", "small test one", "encoder text example",
                   "real test two", "small encoder three", "text example one",
                   "real encoder four", "small text example"]
        for i, phrase in enumerate(phrases):
            feature = ModalityFeature.from_vector("image", pin(f"source-{i}"),
                                                 pin("toy-visual"), (i / 10, 0.25))
            rows.append({"case_id": f"t{i}", "group_id": f"g{i//2}",
                         "scope": "tiny-smoke", "observed_at": i + 1,
                         "split": "train", "target_text": phrase,
                         "source": {"modality": feature.modality,
                                    "input_sha256": feature.input_sha256,
                                    "encoder_sha256": feature.encoder_sha256,
                                    "values": list(feature.values)}})
        self.rows = rows
        self.input_path = self.root / "train.jsonl"

    def run_ingress(self, *, output="out", profile=None):
        self.profile_path.write_bytes(canonical(profile or self.profile))
        self.input_path.write_bytes(b"".join(canonical(r) for r in self.rows))
        return run_offline(self.profile_path, sha(self.profile_path.read_bytes()),
                           self.model_root, self.input_path, sha(self.input_path.read_bytes()),
                           self.root / output, "train")

    def test_real_checkpoint_forward_matches_stock_model_oracle_and_reloads(self):
        receipt = self.run_ingress()
        self.assertEqual(receipt["physical_forwards"], 3)
        self.assertTrue(receipt["model_checkpoint_locally_verified"])
        self.assertEqual(receipt["parameter_count"], sum(p.numel() for p in self.model.parameters()))
        self.assertFalse(receipt["model_publisher_authenticated"])
        self.assertFalse(receipt["actual_pretrained_model_proven"])
        self.assertFalse(receipt["production_accepted"])
        result, digest = load_pinned_jsonl(self.root / "out/encoded.jsonl", receipt["encoded_sha256"])
        self.assertEqual(len(result), 8)
        self.assertEqual(digest, receipt["encoded_sha256"])
        with torch.no_grad():
            for row, source in zip(result, self.rows):
                tokens = self.tokenizer([source["target_text"]], return_tensors="pt")
                hidden = self.model(**tokens).last_hidden_state
                mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                oracle = ((hidden * mask).sum(1) / mask.sum(1).clamp_min(1))[0]
                torch.testing.assert_close(torch.tensor(row["target"]["values"]),
                                           oracle.float(), atol=1e-5, rtol=1e-5)
                self.assertNotIn("target_text", row)
        again = self.run_ingress(output="again")
        self.assertEqual(receipt["encoded_sha256"], again["encoded_sha256"])
        self.assertEqual(receipt["feature_encoder_identity"], again["feature_encoder_identity"])

    def test_cls_pooled_real_forward_matches_independent_oracle(self):
        # RANDOM tiny BERT verifies actual LocalEncoder dispatch, not Granite quality.
        mean = self.run_ingress(output="mean-v7")
        cls_profile = deepcopy(self.profile)
        cls_profile["pooling"] = "cls-first-token"
        cls_profile["normalization"] = "unit_l2"
        cls = self.run_ingress(output="cls-v7", profile=cls_profile)
        self.assertEqual((mean["physical_forwards"], cls["physical_forwards"]), (3, 3))
        self.assertEqual(cls["pooling"], "cls-first-token")
        self.assertNotEqual(mean["feature_encoder_identity"],
                            cls["feature_encoder_identity"])
        self.assertNotEqual(mean["encoded_sha256"], cls["encoded_sha256"])
        encoded, _ = load_pinned_jsonl(self.root / "cls-v7/encoded.jsonl",
                                       cls["encoded_sha256"])
        with torch.no_grad():
            for row, source in zip(encoded, self.rows):
                tokens = self.tokenizer([source["target_text"]], return_tensors="pt")
                hidden = self.model(**tokens).last_hidden_state
                oracle = torch.nn.functional.normalize(hidden[:, 0, :], dim=1)[0]
                actual = torch.tensor(row["target"]["values"])
                torch.testing.assert_close(actual, oracle.float(), atol=1e-5, rtol=1e-5)
                self.assertAlmostEqual(float(torch.linalg.vector_norm(actual)), 1., places=5)
        self.assertFalse(cls["actual_pretrained_model_proven"])
        self.assertFalse(cls["production_accepted"])

    def test_modified_weight_fails_without_success_file(self):
        p = next(self.model_root / n for n in self.profile["snapshot"]["files"]
                 if n.endswith(".safetensors"))
        data = bytearray(p.read_bytes())
        data[-1] ^= 1
        p.write_bytes(data)
        with self.assertRaises((ContractError, ValueError)):
            self.run_ingress()
        self.assertFalse((self.root / "out").exists())

    def test_modified_tokenizer_fails_without_success_file(self):
        p = self.model_root / "vocab.txt"
        p.write_text(p.read_text() + "unregistered\n")
        with self.assertRaises((ContractError, ValueError)):
            self.run_ingress()
        self.assertFalse((self.root / "out").exists())

    def test_wrong_expected_width_fails_closed(self):
        profile = deepcopy(self.profile)
        profile["expected_width"] = 15
        with self.assertRaises(ContractError):
            self.run_ingress(profile=profile)
        self.assertFalse((self.root / "out").exists())

    def test_long_text_never_truncates_silently(self):
        profile = deepcopy(self.profile)
        profile["maximum_tokens"] = 8
        self.rows[0]["target_text"] = "real test one two three four small encoder example text"
        with self.assertRaises((ValueError, ContractError)):
            self.run_ingress(profile=profile)
        self.assertFalse((self.root / "out").exists())

    def test_undeclared_material_file_fails_closed(self):
        (self.model_root / "unlisted.file").write_bytes(b"not in inventory")
        with self.assertRaises((ValueError, ContractError)):
            self.run_ingress()
        self.assertFalse((self.root / "out").exists())


if __name__ == "__main__":
    unittest.main()
