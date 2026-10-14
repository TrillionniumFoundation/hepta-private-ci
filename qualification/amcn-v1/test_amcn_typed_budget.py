"""Actual CPU tensor training plus adversarial typed MemoryCell census tests."""
from copy import deepcopy
from hashlib import sha256
import unittest

import torch

from amcn_core import Refused
from amcn_learning import FeatureMatrix, Row
from amcn_typed_budget import ARMS, train_typed_budget, type_inventory_digest
from amcn_typed_score import score_typed_budget


def digest(s):
    return sha256(s.encode()).hexdigest()


def trial():
    rows, data, types, train, withheld = [], [], {}, {}, {}
    splits = {"train": 4, "select": 2, "future_a": 2,
              "future_b": 2, "retention": 2}
    for kind_idx, kind in enumerate(("semantic", "procedural")):
        for split, count in splits.items():
            for j in range(count):
                key = f"{kind}-{split}-{j}"
                # RETENTION intentionally revisits old TRAIN families.
                source = (f"{kind}-train-{j}" if split == "retention"
                          else key)
                family = (f"{kind}-train-family-{j}" if split == "retention"
                          else f"{kind}-{split}-family-{j}")
                label = j % 2
                rows.append(Row(key, source, family, split, "lab", "g1", digest(key)))
                data.append([float(label * 2 - 1), float(kind_idx * 2 - 1),
                             float(label ^ kind_idx), 0.2 * (j + 1)])
                types[key] = kind
                if split == "train":
                    train[key] = label
                else:
                    withheld[key] = label
    matrix = FeatureMatrix(rows, torch.tensor(data, dtype=torch.float32),
                           encoder_sha256=digest("fixed-encoder"),
                           scope="lab", generation="g1",
                           backend_profile="mechanics_fixture")
    return matrix, types, train, withheld


class TypedMemoryBudgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.matrix, cls.types, cls.train, cls.withheld = trial()
        cls.type_sha = type_inventory_digest(cls.matrix, cls.types)
        cls.trial_result = train_typed_budget(cls.matrix, cls.train, cls.types,
                                              expected_type_digest=cls.type_sha,
                                              steps=6, batch=2, seed=19)

    def test_physically_trained_equal_parameter_and_examples(self):
        receipt = self.trial_result["receipt"]
        metrics = receipt["metrics"]
        a, b = metrics["untyped_budget"], metrics["typed_budget"]
        for field in ("parameters", "parameter_bytes", "optimizer_steps", "examples_processed"):
            self.assertEqual(a[field], b[field])
        self.assertEqual(a["optimizer_steps"], 12)
        self.assertEqual(a["examples_processed"], 24)
        self.assertEqual(a["parameters"], 2 * metrics["baseline_head"]["parameters"])
        self.assertNotEqual(a["head_sha256"], b["head_sha256"])
        self.assertEqual(metrics["backend_profile"], "mechanics_fixture")
        self.assertIsNone(metrics["measured_end_to_end_compression_ratio"])
        self.assertFalse(receipt["production_accepted"])

    def test_sealed_predictions_are_complete_and_never_include_labels(self):
        predictions = self.trial_result["predictions"]
        self.assertEqual(len(predictions), len(self.withheld))
        self.assertEqual({x["row_id"] for x in predictions}, set(self.withheld))
        self.assertTrue(all(set(r["probabilities"]) == set(ARMS) for r in predictions))
        self.assertNotIn("label", str(predictions))
        self.assertEqual(len(set(self.trial_result["receipt"]["metrics"]["physical_inference_calls"].values())), 1)
        self.assertTrue(all(self.trial_result["receipt"]["metrics"]["physical_inference_calls"][a]
                            == len(predictions) for a in ARMS))

    def test_blind_independent_scoring(self):
        score = score_typed_budget(self.matrix, self.types, self.trial_result["predictions"],
                                   self.withheld, pinned_type_sha256=self.type_sha,
                                   pinned_predictions_sha256=self.trial_result["receipt"]["metrics"]["prediction_sha256"])
        self.assertEqual(score["metrics"]["complete_case_count"], len(self.withheld))
        self.assertFalse(score["production_accepted"])
        self.assertFalse(score["metrics"]["strong_hybrid_rag_superiority_proven"])
        self.assertEqual(len([r for r in score["metrics"]["descriptive_scores"]
                              if r["split"] == "future_a"]), len(ARMS))

    def test_changed_type_inventory_refused(self):
        types = dict(self.types)
        types[next(iter(types))] = "procedural"
        with self.assertRaises(Refused):
            train_typed_budget(self.matrix, self.train, types,
                               expected_type_digest=self.type_sha, steps=2)

    def test_invalid_type_and_missing_type_rejected(self):
        types = dict(self.types)
        types[next(iter(types))] = "unknown"
        with self.assertRaises(Refused):
            type_inventory_digest(self.matrix, types)
        types.pop(next(iter(types)))
        with self.assertRaises(Refused):
            type_inventory_digest(self.matrix, types)

    def test_train_labels_cannot_contain_future_target(self):
        contaminated = dict(self.train)
        contaminated[next(iter(self.withheld))] = 1
        with self.assertRaises(Refused):
            train_typed_budget(self.matrix, contaminated, self.types,
                               expected_type_digest=self.type_sha, steps=2)

    def test_insufficient_type_class_diversity_rejected(self):
        labels = dict(self.train)
        for row_id in labels:
            if self.types[row_id] == "semantic":
                labels[row_id] = 0
        with self.assertRaises(Refused):
            train_typed_budget(self.matrix, labels, self.types,
                               expected_type_digest=self.type_sha, steps=2)

    def test_balanced_train_sampler_keeps_physical_budget_and_no_future_labels(self):
        output = train_typed_budget(self.matrix, self.train, self.types,
                                    expected_type_digest=self.type_sha,
                                    steps=4, batch=2, seed=19,
                                    train_sampling="balanced_binary")
        self.assertEqual(output["receipt"]["metrics"]["training_sampling"],
                         "balanced_binary")
        metrics = output["receipt"]["metrics"]
        for key in ("parameters", "parameter_bytes", "optimizer_steps", "examples_processed"):
            self.assertEqual(metrics["typed_budget"][key],
                             metrics["untyped_budget"][key])
        self.assertTrue(metrics["future_labels_opened_during_training"] is False)
        self.assertEqual(len(output["predictions"]), len(self.withheld))

    def test_unregistered_sampler_refused(self):
        with self.assertRaises(Refused):
            train_typed_budget(self.matrix, self.train, self.types,
                               expected_type_digest=self.type_sha,
                               train_sampling="sample_future_labels")

    def test_work_budget_requires_actual_complete_groups(self):
        with self.assertRaises(Refused):
            train_typed_budget(self.matrix, self.train, self.types,
                               expected_type_digest=self.type_sha, steps=2, batch=8)
        with self.assertRaises(Refused):
            train_typed_budget(self.matrix, self.train, self.types,
                               expected_type_digest=self.type_sha, steps=0)

    def test_missing_future_type_is_not_silent(self):
        subset = [i for i, r in enumerate(self.matrix.rows)
                  if not (r.split == "future_b" and self.types[r.row_id] == "semantic")]
        matrix = FeatureMatrix([self.matrix.rows[i] for i in subset],
                               self.matrix.x[subset],
                               encoder_sha256=digest("fixed-encoder"),
                               scope="lab", generation="g1",
                               backend_profile="mechanics_fixture")
        typed = {row.row_id: self.types[row.row_id] for row in matrix.rows}
        with self.assertRaises(Refused):
            train_typed_budget(matrix, self.train, typed,
                               expected_type_digest=type_inventory_digest(matrix, typed),
                               steps=2)

    def test_score_rejects_missing_future_labels_and_train_labels(self):
        for labels in (dict(list(self.withheld.items())[:-1]),
                       {**self.withheld, next(iter(self.train)): 1}):
            with self.assertRaises(Refused):
                score_typed_budget(self.matrix, self.types, self.trial_result["predictions"], labels,
                                   pinned_type_sha256=self.type_sha,
                                   pinned_predictions_sha256=self.trial_result["receipt"]["metrics"]["prediction_sha256"])

    def test_score_rejects_tampering_even_with_rehashed_predictions(self):
        from amcn_core import digest as canonical_digest
        for field, new_value in (("family", "fake-family"),
                                 ("memory_type", "procedural"),
                                 ("split", "train"),
                                 ("input_sha256", digest("wrong"))):
            altered = deepcopy(self.trial_result["predictions"])
            altered[0][field] = new_value
            with self.assertRaises(Refused):
                score_typed_budget(self.matrix, self.types, altered, self.withheld,
                                   pinned_type_sha256=self.type_sha,
                                   pinned_predictions_sha256=canonical_digest(altered))

    def test_score_rejects_partial_or_forged_probabilities(self):
        from amcn_core import digest as canonical_digest
        for change in ("drop", "bad", "missing-arm", "duplicate"):
            altered = deepcopy(self.trial_result["predictions"])
            if change == "drop":
                altered.pop()
            elif change == "bad":
                altered[0]["probabilities"]["typed_equal_budget"] = 1.4
            elif change == "missing-arm":
                del altered[0]["probabilities"]["single_shared"]
            else:
                altered[-1] = deepcopy(altered[0])
            with self.assertRaises(Refused):
                score_typed_budget(self.matrix, self.types, altered, self.withheld,
                                   pinned_type_sha256=self.type_sha,
                                   pinned_predictions_sha256=canonical_digest(altered))

    def test_seal_digest_and_type_epoch_mismatch_fail_closed(self):
        with self.assertRaises(Refused):
            score_typed_budget(self.matrix, self.types, self.trial_result["predictions"], self.withheld,
                               pinned_type_sha256=digest("other"),
                               pinned_predictions_sha256=self.trial_result["receipt"]["metrics"]["prediction_sha256"])
        with self.assertRaises(Refused):
            score_typed_budget(self.matrix, self.types, self.trial_result["predictions"], self.withheld,
                               pinned_type_sha256=self.type_sha,
                               pinned_predictions_sha256=digest("forged"))


if __name__ == "__main__":
    unittest.main()
