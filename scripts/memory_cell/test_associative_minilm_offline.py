"""Standalone CPU/native pretrained mechanics; not memory superiority evidence."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from associative_minilm_offline import (
    AsciiWordPiece, MiniLMOfflineEncoder, PARITY_TEXTS,
    MODEL_FILES, REGISTERED_ENCODER_IDENTITY, inventory, compare_with_transformers,
)

ENCODER = os.environ.get("HEPTA_ASSOC_ENCODER_DIR")
KNOWN_PIN = "5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a"


class AdmissionTests(unittest.TestCase):
    def test_reject_missing_extra_or_symlinked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "missing"):
                inventory(root)
            for name in MODEL_FILES:
                (root / name).write_bytes(b"test")
            info, digest = inventory(root)
            self.assertEqual(set(info), MODEL_FILES)
            self.assertEqual(len(digest), 64)
            (root / "tampered").write_text("x")
            with self.assertRaisesRegex(ValueError, "unexpected"):
                inventory(root)
            (root / "tampered").unlink()
            (root / "vocab.txt").unlink()
            (root / "vocab.txt").symlink_to(root / "config.json")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                inventory(root)

    def test_reject_same_filename_model_with_unregistered_weight_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in MODEL_FILES:
                (root / filename).write_bytes(b"unregistered")
            with self.assertRaisesRegex(ValueError, "unregistered pretrained"):
                MiniLMOfflineEncoder(root)
        self.assertEqual(REGISTERED_ENCODER_IDENTITY, KNOWN_PIN)

    def test_wrong_inventory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in MODEL_FILES:
                (root / name).write_bytes(name.encode())
            expected, digest = inventory(root)
            tampered = {k: dict(v) for k,v in expected.items()}
            tampered["vocab.txt"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "mismatch"):
                inventory(root, expected=tampered)


@unittest.skipUnless(ENCODER and Path(ENCODER).is_dir(), "pinned weights not staged")
class NativeWeightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoder = MiniLMOfflineEncoder(ENCODER)

    def test_pinned_identity_and_real_weight_embeddings(self):
        self.assertEqual(self.encoder.identity, KNOWN_PIN)
        x = self.encoder.encode(list(PARITY_TEXTS))
        self.assertEqual(x.shape, (5, 384))
        np.testing.assert_allclose(np.linalg.norm(x, axis=1), np.ones(5), atol=1e-6)
        self.assertGreater(float(np.std(x)), 0.001)
        self.assertGreater(float(np.max(np.abs(x[0]-x[1]))), 0.005)
        self.assertEqual(self.encoder.truncated_inputs, 0)

    def test_wordpiece_visible_literal_vector_and_piece_bound(self):
        tokens = self.encoder.tokenizer
        self.assertEqual(tokens.encode("hello world"), [101, 7592, 2088, 102])
        self.assertEqual(tokens.encode("hello world", add_special_tokens=False), [7592, 2088])
        self.assertEqual(tokens.encode("HELLO WORLD"), tokens.encode("hello world"))
        self.assertIn(100, tokens.encode("q" * 101))
        for bad in ("", "   ", "caf\u00e9", "\u4e16\u754c", "hello\x00word"):
            with self.subTest(text=bad), self.assertRaises(ValueError):
                tokens.encode(bad)

    def test_same_text_padded_batch_and_determinism(self):
        a = self.encoder.encode(["The build passed."])[0]
        b = self.encoder.encode(["The build passed.", "A significantly longer source record and extra tokens."])[0]
        c = self.encoder.encode(["The build passed."])[0]
        self.assertLess(float(np.max(np.abs(a-b))), 2e-6)
        np.testing.assert_array_equal(a, c)

    def test_fail_closed_no_truncation_or_mutation(self):
        old_count = self.encoder.calls
        with self.assertRaisesRegex(ValueError, "limit"):
            self.encoder.encode(["word " * 260])
        self.assertEqual(self.encoder.calls, old_count)
        with self.assertRaises(ValueError):
            self.encoder.encode(["A valid ASCII source", "undecodable \u4e2d"])
        self.assertEqual(self.encoder.calls, old_count)
        with self.assertRaises(ValueError):
            self.encoder.encode(["short"] * 17)
        self.assertEqual(self.encoder.calls, old_count)

    def test_pretrained_source_bound_parameter_training(self):
        from associative_text_bridge import PinnedTextProjection, prepare_experiences, source_facts, train_scope
        @dataclass(frozen=True)
        class Doc:
            identity: str
            root: str
            scope: str
            observed_at: str
            content: str
        docs = []
        for i, (a,v) in enumerate((("location","zone_north"), ("owner","member_alpha"),
                                     ("successful_mode","mode_safe"))):
            payload = dict(schema="hepta.controlled-event.v1",id=f"src_{i}",
                           entity="service_1",attribute=a,value=v,revision=1,supersedes=[])
            docs.append(Doc(f"src_{i}",f"root_{i}","safe_scope",
                            "2026-10-01T09:00:00+00:00",json.dumps(payload,sort_keys=True)))
        projection = PinnedTextProjection(self.encoder,dimension=24)
        examples = prepare_experiences(source_facts(tuple(docs))[0],projection,scope="safe_scope")
        self.assertEqual({e.kind for e in examples},{"semantic","procedural"})
        candidate,receipt = train_scope(examples,tuple(docs),projection,steps=36,rank=4)
        self.assertGreater(receipt["tensor_delta_squared_norm"],0)
        self.assertEqual(candidate.roots,{"root_0","root_1","root_2"})
        self.assertEqual(candidate.encoder_identity,projection.identity)
        self.assertEqual(candidate.parameter_count(),2*4*24)
        self.assertEqual(self.encoder.truncated_inputs,0)

    def test_native_observed_source_probe_does_not_claim_winner(self):
        from associative_minilm_probe import run
        with tempfile.TemporaryDirectory() as tmp:
            previous_threads = torch.get_num_threads()
            report = run(ENCODER, Path(tmp) / "observations", steps=48, rank=3, dimension=24)
            self.assertEqual(torch.get_num_threads(), previous_threads)
            self.assertEqual(len(report["cases"]), 6)
            self.assertEqual(report["source_family_count"], 1)
            self.assertEqual(report["pretrained_model_inventory_bytes"],
                             sum(item["bytes"] for item in self.encoder.files.values()))
            self.assertFalse(report["strong_tuned_rag_executed"])
            self.assertFalse(report["transformers_parity_verified"])
            self.assertFalse(report["production_accepted"])
            self.assertGreater(report["tensor_updates"], 0)
            self.assertGreater(report["aggregate"]["parametric_mse"],
                               report["aggregate"]["cached_vector_nn_mse"])
            copied = Path(tmp) / "observations" / "candidate.json"
            payload = copied.read_bytes()
            self.assertNotIn(b"site_north", payload)
            self.assertNotIn(b"team_blue", payload)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), report["candidate_sha256"])

    @unittest.skipUnless(__import__('importlib').util.find_spec("transformers") is not None,
                         "Transformers reference unavailable; no parity claim")
    def test_exact_reference_parity(self):
        receipt = compare_with_transformers(ENCODER, PARITY_TEXTS)
        self.assertTrue(receipt["parity_verified"])
        self.assertFalse(receipt["production_accepted"])


if __name__ == "__main__":
    unittest.main()
