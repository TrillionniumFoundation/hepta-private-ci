"""Real optimizer updates on bounded fixtures, not task-efficacy evidence."""

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from perc1.schema import Invalid, sha
from test_perc1_acquisition import pair

HAS_NUMPY = importlib.util.find_spec("numpy") is not None
if HAS_NUMPY:
    from perc1.mlp_head import predict, train_head, validate_head


@unittest.skipUnless(HAS_NUMPY, "optional NumPy training runtime is unavailable")
class MlpHeadTests(unittest.TestCase):
    def setUp(self):
        self.train = [
            pair("t" + str(i), "train", x) for i, x in enumerate((-1.0, -0.5, 0.5, 1.0))
        ]
        self.dev = [
            pair("d" + str(i), "dev", x) for i, x in enumerate((-1.0, 0.0, 1.0))
        ]
        self.groups = dict(
            train=[p["source_group"] for p in self.train],
            dev=[p["source_group"] for p in self.dev],
            confirmation=["unused"],
        )
        self.options = dict(
            feature_extractor_sha256=sha("fixture extractor"),
            seed=3,
            steps=200,
            batch=2,
        )

    def fit(self, **kwargs):
        return train_head(self.train, self.dev, self.groups, **(self.options | kwargs))

    def test_seed_replays_actual_optimizer_and_other_seed_changes_path(self):
        a, b, c = self.fit(), self.fit(), self.fit(seed=7)
        self.assertEqual(a["parameters"], b["parameters"])
        for k in (
            "initial_parameters_sha256",
            "final_parameters_sha256",
            "order_sha256",
            "trace_sha256",
        ):
            self.assertEqual(a["training_receipt"][k], b["training_receipt"][k])
            self.assertNotEqual(a["training_receipt"][k], c["training_receipt"][k])
        receipt = a["training_receipt"]
        self.assertNotEqual(
            receipt["initial_parameters_sha256"], receipt["final_parameters_sha256"]
        )
        self.assertEqual(len(receipt["trace"]), 200)
        self.assertGreater(receipt["elapsed_ns"], 0)
        self.assertFalse(a["scientific_qualified"])

    def test_fitted_gain_changes_with_observed_features_and_roundtrips(self):
        import json

        head = json.loads(json.dumps(self.fit()))
        negative = predict(head, self.dev[0]["features"])
        positive = predict(head, self.dev[-1]["features"])
        self.assertLess(negative["expected_gain"], -0.5)
        self.assertGreater(positive["expected_gain"], 0.5)
        self.assertGreaterEqual(positive["expected_cost"], 0)
        self.assertEqual(
            positive, predict(head, copy.deepcopy(self.dev[-1]["features"]))
        )

    def test_no_confirmation_groups_or_aliased_capture_enters_fit(self):
        changed = copy.deepcopy(self.train)
        changed[0]["split"] = "confirmation"
        with self.assertRaises(Invalid):
            train_head(changed, self.dev, self.groups, **self.options)
        dev = copy.deepcopy(self.dev)
        dev[0]["with"]["evidence"][-1]["capture_sha256"] = self.train[0]["with"][
            "evidence"
        ][-1]["capture_sha256"]
        with self.assertRaises(Invalid):
            train_head(self.train, dev, self.groups, **self.options)
        groups = copy.deepcopy(self.groups)
        groups["confirmation"].append(groups["train"][0])
        with self.assertRaises(Invalid):
            train_head(self.train, self.dev, groups, **self.options)

    def test_existing_acquisition_serialization_prediction_and_choice_dispatch(self):
        from perc1 import acquisition

        head = self.fit()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "head.json"
            identity = acquisition.save_head(path, head)
            loaded = acquisition.load_head(path, identity)
        public = self.dev[-1]["features"]
        self.assertEqual(acquisition.predict(loaded, public), predict(head, public))
        self.assertEqual(
            acquisition.choose(
                loaded, [dict(id="extra", upper_cost=4, features=public)]
            )["action"],
            "ACQUIRE",
        )
        changed = copy.deepcopy(public)
        changed["task_goal"].append(0.0)
        with self.assertRaises(Invalid):
            acquisition.predict(loaded, changed)

    def test_finite_bounds_and_training_digests_are_enforced(self):
        for kwargs in (
            {"steps": 2001},
            {"batch": 0},
            {"hidden": 65},
            {"learning_rate": float("nan")},
        ):
            with self.assertRaises(Invalid):
                self.fit(**kwargs)
        head = self.fit(steps=3)
        for field, value in (
            ("w2", [[float("nan"), 0.0]] * 8),
            ("b2", [True, 0.0]),
            ("b1", []),
        ):
            changed = copy.deepcopy(head)
            changed["parameters"][field] = value
            with self.assertRaises(Invalid):
                validate_head(changed)
        head["training_receipt"]["trace"][0]["batch_sha256"] = sha("changed batch")
        with self.assertRaises(Invalid):
            validate_head(head)


if __name__ == "__main__":
    unittest.main()
