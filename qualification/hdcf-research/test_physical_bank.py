"""Real scalar-SGD mechanics and adversarial held-label isolation controls."""
import copy
import math
import unittest

from physical_bank import Denied, SCHEMA, digest, score, train, validate_bundle

SHA = "a" * 64


def original():
    """Explicit synthetic mathematical fixture; NOT a pretrained Encoder."""
    fit, held, labels = [], [], []
    for i in range(80):
        t = "left" if i % 2 == 0 else "right"
        y = (i // 2) % 2
        # The identical direction means conflicting labels for two types,
        # so a type-oblivious classifier has a genuine parameter-sharing loss.
        value = (1 if y else -1) * (1 if t == "left" else -1)
        x = [value + i * 0.0001, (i - 40) * 0.001, 0.1 if t == "left" else -0.1, 0.2]
        fit.append(dict(id=f"fit-{i}", family="train-A" if i < 40 else "train-B",
                        type=t, vector=x, target=y))
    for i in range(32):
        t = "left" if i % 2 == 0 else "right"
        y = (i // 2) % 2
        value = (1 if y else -1) * (1 if t == "left" else -1)
        x = [value + (i+100)*0.0001, (i - 16)*0.001, 0.1 if t == "left" else -0.1, 0.2]
        id_ = f"test-{i}"
        held.append(dict(id=id_, family="test-C", type=t, vector=x))
        labels.append(dict(id=id_, family="test-C", type=t, target=y))
    bundle = dict(schema=SCHEMA, producer=dict(encoder_sha256=SHA, preprocess_sha256=SHA,
                 source_sha256=SHA, generation=1, principal="fixture"),
                  dimension=4, types=["left", "right"], fit=fit, held=held)
    return bundle, dict(schema="hepta.hdcf.blind-targets.v1", bundle_digest=digest(bundle), targets=labels)


class PhysicalBank(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.targets = original()
        cls.trial = train(cls.bundle, steps=256, seed=7347)
        cls.review = score(cls.trial, cls.targets)

    def test_physical_updates_real_and_parameter_matched(self):
        t = self.trial
        self.assertEqual(t["head_params_per_arm"], 10)
        self.assertEqual(t["head_weight_payload_bytes_per_arm"], 80)
        self.assertNotEqual(t["arms"]["split"]["weights_digest"], t["arms"]["frozen"]["weights_digest"])
        self.assertEqual(t["arms"]["shared_one_touch"]["estimated_parameter_touches"],
                         t["arms"]["split"]["estimated_parameter_touches"])
        self.assertEqual(t["arms"]["shared_dense"]["estimated_parameter_touches"],
                         t["arms"]["split"]["estimated_parameter_touches"] * 2)
        self.assertGreater(t["arms"]["split"]["observed_train_cpu_ns"], 0)
        self.assertEqual(t["encoder_forward_count"], 0)
        self.assertFalse(t["pretrained_model_provenance_verified"])
        self.assertFalse(t["production_authorized"])

    def test_independent_review_all_arms_and_group(self):
        result = self.review["results"]
        self.assertEqual(set(result), {"frozen", "shared_dense", "shared_one_touch", "split", "swapped"})
        self.assertEqual(result["split"]["n"], 32)
        self.assertEqual(set(result["split"]["type_accuracy"]), {"left", "right"})
        self.assertGreater(result["split"]["accuracy"], result["swapped"]["accuracy"])
        self.assertFalse(self.review["future_window_claim"])

    def test_production_held_target_cannot_enter_training(self):
        bad = copy.deepcopy(self.bundle)
        bad["held"][0]["target"] = 1
        with self.assertRaises(Denied):
            train(bad, steps=8)

    def test_feature_source_overlap_rejected(self):
        bad = copy.deepcopy(self.bundle)
        bad["held"][0]["family"] = "train-A"
        with self.assertRaisesRegex(Denied, "source-family overlap"):
            validate_bundle(bad)

    def test_duplicate_feature_and_id_rejected(self):
        for key in ("id", "vector"):
            bad = copy.deepcopy(self.bundle)
            bad["held"][0][key] = copy.deepcopy(bad["fit"][0][key])
            with self.subTest(key=key), self.assertRaises(Denied):
                validate_bundle(bad)

    def test_missing_type_and_nonfinite_rejected(self):
        for badtype in (True, math.nan, math.inf, float("-inf"), 9.0):
            bad = copy.deepcopy(self.bundle)
            bad["fit"][0]["vector"][0] = badtype
            with self.subTest(value=str(badtype)), self.assertRaises(Denied):
                validate_bundle(bad)
        bad = copy.deepcopy(self.bundle)
        bad["fit"][0]["type"] = "rogue"
        with self.assertRaises(Denied):
            validate_bundle(bad)

    def test_target_identity_tamper_rejected(self):
        tampered = copy.deepcopy(self.targets)
        tampered["bundle_digest"] = "b" * 64
        with self.assertRaisesRegex(Denied, "identity"):
            score(self.trial, tampered)
        tampered = copy.deepcopy(self.targets)
        tampered["targets"][0]["type"] = "right"
        with self.assertRaisesRegex(Denied, "source/type"):
            score(self.trial, tampered)

    def test_missing_or_duplicate_predictions_rejected(self):
        bad = copy.deepcopy(self.trial)
        bad["predictions"]["split"].pop()
        with self.assertRaises(Denied):
            score(bad, self.targets)
        bad = copy.deepcopy(self.trial)
        bad["predictions"]["split"][0] = dict(bad["predictions"]["split"][1])
        with self.assertRaises(Denied):
            score(bad, self.targets)

    def test_untrusted_labels_and_trial_are_denied(self):
        bad = copy.deepcopy(self.trial)
        bad["production_authorized"] = True
        with self.assertRaises(Denied):
            score(bad, self.targets)
        bad = copy.deepcopy(self.targets)
        bad["targets"][0]["target"] = True
        with self.assertRaises(Denied):
            score(self.trial, bad)

    def test_bad_hyperparameters_preflight(self):
        for kwargs in ({"steps": 0}, {"steps": 100000}, {"seed": 0}, {"lr": math.nan}, {"lr": 1.0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(Denied):
                train(self.bundle, **kwargs)


if __name__ == "__main__":
    unittest.main()
