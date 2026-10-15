"""Isolated source-only 256-capacity mechanics; no pretrained reader claims."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import associative_locomo_shadow as m


def corpus(documents=275):
    return [dict(sample_id=f"conv-{j+1}",
                 conversation={"session_1": [dict(dia_id=f"D1:{i+1}", speaker="Alex",
                     text=(f"At source message {i+1}, Alex noted release milestone {i+1}."
                           if i % 2 else f"Step {i+1}: Alex planned the release milestone."))
                     for i in range(documents)]},
                 qa=[dict(question=f"Which milestone was noted in family {j+1}?",
                          answer="HIDDEN_ANSWER", evidence=["D1:240"], category="1"),
                     dict(question=f"When did {j+1} have a milestone?",
                          answer="HIDDEN_ANSWER_2", evidence=["D1:270"], category="1")])
            for j in range(10)]


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "dataset.json"
        raw = m.canonical(corpus())
        self.dataset.write_bytes(raw)
        self.pin = m.sha256(raw)

    def prepare256(self):
        with patch.object(m, "DATASET_SHA256", self.pin):
            return m.prepare(self.dataset, self.root / "prepared256",
                             source_limit=256, question_limit=2, expected_sha=self.pin)

    def test_fixed_256_source_pool_has_no_hidden_answer(self):
        manifest = self.prepare256()
        public = m.strict_json((self.root / "prepared256" / "public.json").read_bytes())
        self.assertEqual(manifest["source_count"], 2560)
        self.assertEqual(manifest["question_count"], 20)
        self.assertEqual(public["policy"]["source_limit_per_dialogue"], 256)
        self.assertEqual([d["id"] for d in public["families"][0]["sources"][-2:]],
                         ["D1:255", "D1:256"])
        self.assertNotIn("HIDDEN_ANSWER", (self.root / "prepared256" / "public.json").read_text())
        self.assertNotIn("HIDDEN_ANSWER", (self.root / "prepared256" / "private.json").read_text())
        self.assertIn('"evidence"', (self.root / "prepared256" / "private.json").read_text())
        with patch.object(m, "DATASET_SHA256", self.pin):
            m.validate_public(public)

    def test_256_candidate_pool_rejects_truncated_or_label_contamination(self):
        self.prepare256()
        public = m.strict_json((self.root / "prepared256" / "public.json").read_bytes())
        public["families"][0]["sources"].pop()
        with patch.object(m, "DATASET_SHA256", self.pin):
            with self.assertRaisesRegex(ValueError, "incomplete preregistered"):
                m.validate_public(public)
        public = m.strict_json((self.root / "prepared256" / "public.json").read_bytes())
        public["families"][2]["sources"][0]["answer"] = "leak"
        with patch.object(m, "DATASET_SHA256", self.pin):
            with self.assertRaisesRegex(ValueError, "answer labels"):
                m.validate_public(public)

    def test_limit_beyond_registered_capacity_rejected(self):
        with patch.object(m, "DATASET_SHA256", self.pin):
            with self.assertRaisesRegex(ValueError, "bounded preregistered"):
                m.prepare(self.dataset, self.root / "too_many", source_limit=257,
                          question_limit=2, expected_sha=self.pin)

    def test_same_questions_across_128_and_256(self):
        self.prepare256()
        with patch.object(m, "DATASET_SHA256", self.pin):
            m.prepare(self.dataset, self.root / "prepared128", source_limit=128,
                      question_limit=2, expected_sha=self.pin)
        a = m.strict_json((self.root / "prepared256" / "public.json").read_bytes())
        b = m.strict_json((self.root / "prepared128" / "public.json").read_bytes())
        for fa, fb in zip(a["families"], b["families"], strict=True):
            self.assertEqual(fa["questions"], fb["questions"])
            self.assertEqual(fa["sources"][:128], fb["sources"])

    def test_full_256_run_with_mock_encoder_seals_before_private_review(self):
        # Mechanics only: deterministic hash vectors, NOT pretrained weight evidence.
        import hashlib

        class FakeEncoder:
            def __init__(self, directory):
                self.identity = "fake-pretrained-model-not-accepted"
                self.files = {"fixture": {"bytes": 1}}

        class FakeProjection:
            def __init__(self, encoder, *, dimension):
                self.dimension = dimension
                self.identity = "fake-projection-not-accepted"
                self.encoded_texts = 0

            def encode(self, texts):
                values = []
                self.encoded_texts += len(texts)
                for text in texts:
                    seed = hashlib.sha256(text.encode()).digest()
                    values.append(tuple((seed[i % 32] - 128) / 128.0
                                        for i in range(self.dimension)))
                return values

        self.prepare256()
        isolated = self.root / "public_only"
        isolated.mkdir()
        for name in ("public.json", "manifest.json"):
            (isolated / name).write_bytes((self.root / "prepared256" / name).read_bytes())
        self.assertFalse((isolated / "private.json").exists())
        with (patch.object(m, "DATASET_SHA256", self.pin),
              patch.object(m, "MiniLMOfflineEncoder", FakeEncoder),
              patch.object(m, "PinnedTextProjection", FakeProjection)):
            done = m.run(isolated, self.root / "fake-encoder", self.root / "run256",
                         pre_steps=128, continuation_steps=1, dimension=16, rank=2)
            review = m.review(self.root / "prepared256", self.root / "run256",
                              self.root / "review256.json")
        self.assertEqual(done["complete_count"], 20)
        self.assertEqual(review["questions"], 20)
        self.assertEqual(review["reference_coverage"]["full_gold_in_pool"], 10)
        self.assertFalse(review["production_accepted"])
        self.assertFalse(review["semantic_reader_executed"])
        self.assertFalse(review["statistical_superiority_claim"])

    def test_inference_worker_cannot_see_private_labels(self):
        self.prepare256()
        public = self.root / "prepared256"
        with self.assertRaisesRegex(ValueError, "physically isolated"):
            m.run(public, self.root / "missing_encoder", self.root / "run")


if __name__ == "__main__":
    unittest.main()
