"""Controlled fixtures exercise learning/decision boundaries, not task efficacy."""

import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from perc1.acquisition import choose, features, load_head, paired_label, predict
from perc1.acquisition import save_head, train_head
from perc1.schema import Cost, Invalid, sha


def pair(group, split, value):
    evidence = [
        dict(
            source_id="initial",
            receipt_sha256=sha([group, "initial-receipt"]),
            capture_sha256=sha([group, "initial-capture"]),
        )
    ]
    prefix = sha([group, "prefix"])
    public = dict(
        schema="perc1.acquisition-features.v1",
        prefix_sha256=prefix,
        task_goal=[value],
        coverage=0.25,
        source_repeat=0.0,
        remaining_budget=100,
        uncertainty=0.95,
        acquired_latent=[],
        acquired_receipt_sha256s=[evidence[0]["receipt_sha256"]],
    )
    before = dict(
        prefix_sha256=prefix,
        solver_sha256=sha("frozen-solver"),
        inference_seed=7,
        evidence=evidence,
        score=1.0 if value < 0 else 0.0,
        cost=asdict(Cost(acquisition=2, encoding=2, inference=2)),
    )
    after = copy.deepcopy(before)
    after["evidence"].append(
        dict(
            source_id="extra",
            receipt_sha256=sha([group, "extra-receipt"]),
            capture_sha256=sha([group, "extra-capture"]),
        )
    )
    after["score"] = 1.0 if value > 0 else 0.0
    after["cost"] = asdict(
        Cost(acquisition=3, encoding=3, inference=3, communication=1)
    )
    return dict(
        schema="perc1.acquisition-pair.v1",
        source_group=group,
        split=split,
        candidate_id="extra",
        features=public,
        without=before,
        **{"with": after},
    )


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.train = [
            pair("train-" + str(i), "train", x) for i, x in enumerate((-1.0, 0.0, 1.0))
        ]
        self.dev = [
            pair("dev-" + str(i), "dev", x) for i, x in enumerate((-1.0, 0.0, 1.0))
        ]
        self.splits = {
            "train": [p["source_group"] for p in self.train],
            "dev": [p["source_group"] for p in self.dev],
            "confirmation": ["heldout-source"],
        }
        self.options = dict(
            feature_extractor_sha256=sha("public-extractor"), ridge=0.01, cost_value=0.1
        )
        self.head = train_head(self.train, self.dev, self.splits, **self.options)

    def candidate(self, value, upper=4):
        public = pair("heldout-source", "confirmation", value)["features"]
        return {"id": "extra", "upper_cost": upper, "features": public}

    def test_fixed_and_random_do_not_run_the_unused_learned_head(self):
        with patch(
            "perc1.acquisition.predict", side_effect=AssertionError("unused head ran")
        ):
            for mode in ("fixed", "random"):
                result = choose(self.head, [self.candidate(1.0)], mode=mode)
                self.assertEqual(result["action"], "ACQUIRE")
                self.assertIsNone(result["prediction"])

    def test_pair_uses_terminal_gain_and_complete_incremental_cost(self):
        self.assertEqual(paired_label(self.train[2]), (1.0, 4))
        self.assertEqual(paired_label(self.train[0]), (-1.0, 4))
        self.assertEqual(paired_label(self.train[1]), (0.0, 4))

    def test_learned_positive_negative_and_noisy_observations(self):
        useful = choose(self.head, [self.candidate(1.0)])
        self.assertEqual(useful["action"], "ACQUIRE")
        self.assertGreater(useful["net_value"], 0.5)
        for value in (-1.0, 0.0):
            candidate = self.candidate(value)
            candidate["features"]["uncertainty"] = 1.0
            self.assertEqual(choose(self.head, [candidate])["action"], "STOP")
        self.assertFalse(useful["scientific_qualified"])

    def test_same_prefix_hidden_outcomes_do_not_enter_prediction(self):
        candidate = self.candidate(1.0)
        expected = choose(self.head, [candidate])
        for sealed_score in (0.0, 1.0):
            private_pair = pair("heldout-source", "confirmation", 1.0)
            private_pair["with"]["score"] = sealed_score
            candidate["features"] = private_pair["features"]
            self.assertEqual(choose(self.head, [candidate]), expected)
        candidate["features"]["target_score"] = 1.0
        with self.assertRaises(Invalid):
            choose(self.head, [candidate])

    def test_pair_requires_same_prefix_solver_seed_and_one_new_capture(self):
        variants = []
        for key, value in (
            ("prefix_sha256", sha("different")),
            ("solver_sha256", sha("different")),
            ("inference_seed", 9),
        ):
            changed = copy.deepcopy(self.train[2])
            changed["with"][key] = value
            variants.append(changed)
        changed = copy.deepcopy(self.train[2])
        changed["with"]["evidence"].append(changed["with"]["evidence"][-1])
        variants.append(changed)
        changed = copy.deepcopy(self.train[2])
        changed["with"]["evidence"][-1]["capture_sha256"] = changed["without"][
            "evidence"
        ][0]["capture_sha256"]
        variants.append(changed)
        changed = copy.deepcopy(self.train[2])
        changed["features"]["acquired_receipt_sha256s"].append(sha("unseen"))
        variants.append(changed)
        changed = copy.deepcopy(self.train[2])
        changed["with"]["cost"] = changed["without"]["cost"]
        variants.append(changed)
        for changed in variants:
            with self.subTest(pair=sha(changed)), self.assertRaises(Invalid):
                paired_label(changed)

    def test_train_dev_and_confirmation_boundaries(self):
        overlap = copy.deepcopy(self.splits)
        overlap["dev"].append(overlap["train"][0])
        with self.assertRaises(Invalid):
            train_head(self.train, self.dev, overlap, **self.options)
        changed = copy.deepcopy(self.train)
        changed[0]["split"] = "confirmation"
        with self.assertRaises(Invalid):
            train_head(changed, self.dev, self.splits, **self.options)
        changed = copy.deepcopy(self.dev)
        changed[0]["with"]["evidence"][-1]["capture_sha256"] = self.train[0]["with"][
            "evidence"
        ][-1]["capture_sha256"]
        with self.assertRaises(Invalid):
            train_head(self.train, changed, self.splits, **self.options)

    def test_finite_exact_bounded_public_features(self):
        for key, value in (
            ("task_goal", [float("nan")]),
            ("uncertainty", float("inf")),
            ("coverage", True),
            ("remaining_budget", -1),
            ("acquired_latent", [0.0] * 65),
            ("unseen_latent", [1.0]),
        ):
            public = self.candidate(1.0)["features"]
            public[key] = value
            with self.subTest(field=key), self.assertRaises(Invalid):
                features(public)
        public = self.candidate(1.0)["features"]
        public["acquired_latent"] = [1.0]
        public["acquired_receipt_sha256s"] = []
        with self.assertRaises(Invalid):
            features(public)

    def test_all_policies_obey_same_budget_and_shared_prefix(self):
        for mode in ("active", "fixed", "random"):
            self.assertEqual(
                choose(self.head, [self.candidate(1.0, 101)], mode=mode)["action"],
                "STOP",
            )
            self.assertEqual(
                choose(self.head, [self.candidate(1.0, 100)], mode=mode)["action"],
                "ACQUIRE",
            )
        a, b = self.candidate(1.0), self.candidate(0.0)
        b["id"] = "other"
        b["features"]["remaining_budget"] = 99
        with self.assertRaises(Invalid):
            choose(self.head, [a, b])

    def test_roundtrip_digest_and_nonfinite_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "head.json"
            identity = save_head(path, self.head)
            self.assertEqual(load_head(path, identity), self.head)
            self.assertEqual(
                predict(load_head(path), self.candidate(1.0)["features"]),
                predict(self.head, self.candidate(1.0)["features"]),
            )
            changed = copy.deepcopy(self.head)
            changed["coefficients"][0][0] += 0.1
            save_head(path, changed)
            with self.assertRaises(Invalid):
                load_head(path, identity)
            changed["coefficients"][0][0] = float("nan")
            path.write_text(json.dumps(changed))
            with self.assertRaises(Invalid):
                load_head(path)

    def test_deterministic_seed_is_not_an_independent_training_replicate(self):
        other = train_head(self.train, self.dev, self.splits, seed=99, **self.options)
        self.assertEqual(other["coefficients"], self.head["coefficients"])
        self.assertFalse(other["training_receipt"]["independent_training_replicate"])
        self.assertGreater(other["training_receipt"]["elapsed_ns"], 0)
        self.assertEqual(
            other["training_receipt"]["train_pairs_sha256"], sha(self.train)
        )


if __name__ == "__main__":
    unittest.main()
