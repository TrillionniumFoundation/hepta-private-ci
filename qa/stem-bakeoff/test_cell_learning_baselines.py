"""Source-only lookup and semantic-control behavior checks."""

import unittest
from collections import Counter
import re

import numpy as np

from cell_learning_baselines import FrozenBaselines, normalized_text, retained_state_bytes


class LearningBaselineTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"source_id": "a", "group_id": "a", "text": "socket network timeout"},
                     {"source_id": "b", "group_id": "b", "text": "syntax parser failure"}]
        self.features = np.eye(2)
        self.baseline = FrozenBaselines(self.features, [0, 1], self.rows, 2)

    def test_exact_misses_and_lexical_matches_have_distinct_admission(self):
        rows = [{"source_id": "c", "group_id": "c", "text": "network timeout again"}]
        exact = self.baseline.predict("exact", [[1, 0]], rows)
        lexical = self.baseline.predict("bm25", [[1, 0]], rows)
        self.assertEqual(exact["eligible"].tolist(), [False])
        self.assertEqual(lexical["eligible"].tolist(), [True])
        self.assertEqual(lexical["retrieved_source_ids"], ["a"])
        self.assertEqual(lexical["logits"].argmax(axis=1).tolist(), [0])

    def test_dense_and_prototype_use_actual_features(self):
        for arm in ("dense_nearest", "prototype"):
            result = self.baseline.predict(arm, self.features[::-1], self.rows)
            self.assertEqual(result["logits"].argmax(axis=1).tolist(), [1, 0])
            self.assertEqual(result["cost"]["encoder_forward_calls"], 0)

    def test_prediction_rejects_gold_fields(self):
        leaked = [{**self.rows[0], "label": 0}]
        with self.assertRaises(ValueError):
            self.baseline.predict("dense_nearest", [[1, 0]], leaked)

    def test_conflicting_exact_training_sources_abstain(self):
        rows = [self.rows[0], {**self.rows[0], "source_id": "other", "group_id": "other"}]
        model = FrozenBaselines(self.features, [0, 1], rows, 2)
        self.assertEqual(model.predict("exact", [[1, 0]], rows[:1])["eligible"].tolist(), [False])

    def test_sparse_bm25_matches_independent_dense_formula(self):
        rng = np.random.default_rng(37)
        vocabulary = np.array(["network", "parser", "quoted", "unicode", "错误", "value", "timeout"])
        rows = [{"source_id": str(i), "group_id": str(i),
                 "text": " ".join(rng.choice(vocabulary, size=i + 1))} for i in range(12)]
        queries = [{"source_id": "q" + str(i), "group_id": "q" + str(i), "text": text}
                   for i, text in enumerate(("timeout timeout 错误", "network parser", "unseen", "!!!"))]
        labels = np.arange(len(rows)) % 3
        model = FrozenBaselines(np.ones((len(rows), 2)), labels, rows, 3)
        counts = [Counter(re.findall(r"\w+", normalized_text(r["text"]))) for r in rows]
        lengths = np.array([sum(c.values()) for c in counts])
        expected = np.zeros((len(queries), len(rows)))
        for i, query in enumerate(queries):
            for token in set(re.findall(r"\w+", normalized_text(query["text"]))):
                df = sum(token in document for document in counts)
                if df:
                    tf = np.array([document[token] for document in counts])
                    expected[i] += np.log(1 + (len(rows) - df + .5) / (df + .5)) * tf * 2.2 / (
                        tf + 1.2 * (.25 + .75 * lengths / max(float(lengths.mean()), 1.0)))
        result = model.predict("bm25", np.ones((len(queries), 2)), queries)
        expected_logits = np.stack([expected[:, labels == k].max(axis=1) for k in range(3)], axis=1)
        np.testing.assert_array_equal(result["logits"], expected_logits)
        np.testing.assert_array_equal(result["eligible"], expected.max(axis=1) > 0)
        self.assertEqual(result["retrieved_source_ids"], [rows[j]["source_id"] if expected[i].max() else None
                         for i, j in enumerate(expected.argmax(axis=1))])
        self.assertTrue(result["cost"]["python_container_overhead_measured"])
        self.assertGreater(result["cost"]["retained_tensor_bytes"], model.features.nbytes + model.centroids.nbytes)

    def test_reachable_memory_does_not_duplicate_shared_numpy_buffers(self):
        values = np.arange(16, dtype=np.float64)
        result = retained_state_bytes({"first": values, "alias": values, "view": values[1:]})
        self.assertEqual(result["retained_tensor_bytes"], values.nbytes)
        self.assertGreater(result["reachable_python_bytes"], 0)
        self.assertEqual(result["reachable_state_bytes"], values.nbytes + result["reachable_python_bytes"])


if __name__ == "__main__":
    unittest.main()
