"""Hermetic negative/source conformance for the SHA-pinned offline MiniLM canary.

The original six-layer 160-forward physical experiment is separate and requires
an authenticated historic archive; these tests DO NOT claim pretrained efficacy.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from real_minilm_reference import CHECKSUMS, Denied, source_records, verified_material, wordpiece
from review_real_minilm import check_receipt


class MiniLMSourceTests(unittest.TestCase):
    def test_byte_manifest_is_original_and_bounded(self):
        self.assertEqual(len(CHECKSUMS), 5)
        self.assertTrue(all(len(sha) == 64 for sha in CHECKSUMS.values()))
        self.assertEqual(len(set(CHECKSUMS.values())), 5)

    def test_wordpiece_exact_ids_and_unknown(self):
        vocab = {"[CLS]": 101, "[SEP]": 102, "new": 200, "##found": 201, "@": 202}
        self.assertEqual(wordpiece("Newfound @", vocab), [101, 200, 201, 202, 102])
        self.assertEqual(wordpiece("nonexistent", vocab), [101, 100, 102])

    def test_wordpiece_unicode_normalization_and_guard(self):
        vocab = {"cafe": 700, "!": 150, "a": 155}
        self.assertEqual(wordpiece("CAFÉ!", vocab), [101, 700, 150, 102])
        for s in ("", " ", "x"*4097):
            with self.subTest(s_len=len(s)),self.assertRaises(Denied):
                wordpiece(s, vocab)

    def test_wordpiece_refuses_long_or_invalid_tokenization(self):
        vocab = {"a": 200}
        with self.assertRaises(Denied):
            wordpiece(" ".join(["a"] * 127), vocab)
        self.assertEqual(wordpiece("a"*101, vocab), [101, 100, 102])

    def test_source_only_case_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = []
            for family in range(10):
                turns = [{"dia_id":f"D1:{i}", "speaker":f"person{family}",
                          "text":f"An original synthetic conversation statement number {family}-{i} is long enough."}
                         for i in range(6)]
                corpus.append({"sample_id":f"conv-{family}", "conversation":{"session_1":turns},
                               "qa":[{"question":"If label leaks, this field must not be used", "answer":family}]})
            (root/"locomo.json").write_text(json.dumps(corpus))
            records = source_records(root)
            self.assertEqual(len(records), 32)
            self.assertEqual(len({r["source_sha256"] for r in records}), 32)
            self.assertTrue(all("answer" not in r and "qa" not in r for r in records))
            self.assertEqual(records, source_records(root))

    def test_source_rejects_duplicate_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = {"sample_id":"conv-0", "conversation":{"session_1":[
                {"dia_id":"D1:1","speaker":"abc","text":"This is a legitimate sounding sample."}]}}
            (root/"locomo.json").write_text(json.dumps([sample]*10))
            with self.assertRaises(Denied):
                source_records(root)

    def test_refuse_unverified_model_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Denied):
                verified_material(Path(tmp))
            path = Path(tmp)/"encoder/model.safetensors"
            path.parent.mkdir()
            path.write_bytes(b"not an authentic model")
            with self.assertRaises(Denied):
                verified_material(Path(tmp))

    def test_reviewer_rejects_absent_original_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                check_receipt(Path(tmp), {})

    def test_reviewer_denies_forged_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                check_receipt(Path(tmp), {"schema":"hepta.hdsi.real-minilm-original-cpu.local-shadow.v1",
                                               "original_model_sha256":CHECKSUMS["encoder/model.safetensors"],
                                               "original_locomo_sha256":CHECKSUMS["locomo.json"],
                                               "archive_sha256":"07b357cbb3362f4afa4dc1872ab5e5aa30f411572037",
                                               "production_authorized":True})


if __name__ == "__main__":
    unittest.main()
