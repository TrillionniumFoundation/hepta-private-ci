import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from index import PersistentIndex, RetrievalPolicy, tune_policy
from native import Document, Question, load


class NativeTests(unittest.TestCase):
    def test_longmemeval_labels_never_enter_history(self):
        sample = dict(
            question_id="a_abs",
            question_type="knowledge-update",
            question="Where?",
            answer="DO_NOT_LEAK_GOLD",
            question_date="2024/01/02",
            haystack_session_ids=["s"],
            haystack_dates=["2024/01/01"],
            haystack_sessions=[[dict(role="user", content="A fact", has_answer=True)]],
            answer_session_ids=["s"],
        )
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "data.json"
            p.write_text(json.dumps([sample, dict(sample, question_id="b")]))
            benchmark = load(p, "longmemeval")
            self.assertTrue(benchmark.targets["longmemeval:a_abs"].unanswerable)
            self.assertNotIn(
                "DO_NOT_LEAK", str(benchmark.documents) + str(benchmark.questions)
            )
            self.assertNotIn("has_answer", str(benchmark.documents))
            self.assertEqual(len(set(benchmark.families.values())), 1)
            sample["haystack_dates"] = []
            p.write_text(json.dumps([sample]))
            with self.assertRaises(ValueError):
                load(p, "longmemeval")

    def test_locomo_adversarial_and_caption_scope(self):
        sample = dict(
            sample_id="one",
            conversation={
                "session_1_date_time": "2023/01/01",
                "session_1": [
                    dict(
                        speaker="A",
                        dia_id="D1:1",
                        text="An observation",
                        img_url="https://example.invalid/p.png",
                        blip_caption="generated caption",
                    )
                ],
            },
            qa=[
                dict(
                    question="Which?",
                    adversarial_answer="NOT_TRUTH",
                    category=5,
                    evidence=[],
                )
            ],
        )
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "locomo.json"
            p.write_text(json.dumps([sample]))
            b = load(p, "locomo")
            self.assertIsNone(b.targets[b.questions[0].identity].answer)
            self.assertEqual(b.documents[0].assets, ("https://example.invalid/p.png",))
            self.assertNotIn("NOT_TRUTH", str(b))
            sample["qa"][0]["evidence"] = ["missing"]
            p.write_text(json.dumps([sample]))
            with self.assertRaises(ValueError):
                load(p, "locomo")

    def test_persistent_index_reopen_is_identical_and_revocation_is_not_optional(self):
        docs = tuple(
            Document(str(i), f"r{i}", "scope", "s", "2024", value)
            for i, value in enumerate(("alpha compiler", "beta migration"))
        )
        q = Question("q", "f", "scope", "compiler", "2025")
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "index.sqlite"
            blob = PersistentIndex.build(p, docs, np.eye(2), "fixed-encoder-sha", "cut")
            index = PersistentIndex(
                p,
                "cut",
                set(),
                expected_file_digest=blob,
                expected_encoder="fixed-encoder-sha",
            )
            first, receipt = index.query(
                q, np.array([1, 0]), RetrievalPolicy(), current_cut="cut", revoked=set()
            )
            self.assertEqual(first[0], docs[0])
            self.assertGreater(receipt["index_file_bytes"], 0)
            index.close()
            index = PersistentIndex(
                p,
                "cut",
                set(),
                expected_file_digest=blob,
                expected_encoder="fixed-encoder-sha",
            )
            second, _ = index.query(
                q, np.array([1, 0]), RetrievalPolicy(), current_cut="cut", revoked=set()
            )
            self.assertEqual(first, second)
            for query, cut, revoked in (
                (replace(q, scope="other"), "cut", set()),
                (q, "new", set()),
                (q, "cut", {"r0"}),
            ):
                with self.assertRaises(ValueError):
                    index.query(
                        query,
                        np.ones(2),
                        RetrievalPolicy(),
                        current_cut=cut,
                        revoked=revoked,
                    )
            index.close()
            with self.assertRaises(FileExistsError):
                PersistentIndex.build(p, docs, np.eye(2), "fixed", "cut")
            with self.assertRaises(ValueError):
                tune_policy([(q, "test")], {}, {}, {}, "cut", set())

    def test_scope_pooling_and_nonfinite_vectors_rejected(self):
        d = Document("d", "r", "scope", "s", "2024", "text")
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                PersistentIndex.build(
                    Path(root) / "x",
                    (d, replace(d, scope="other")),
                    np.eye(2),
                    "e",
                    "c",
                )
            with self.assertRaises(ValueError):
                PersistentIndex.build(
                    Path(root) / "y", (d,), np.array([[float("nan")]]), "e", "c"
                )


if __name__ == "__main__":
    unittest.main()
