"""Actual original-data and adversarial nonpromotion tests for tiny SGD Head."""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest

from source_head_sgd_original import (
    ARMS, FEATURES, SOURCE_SHA, STEPS,
    dump, from_file, h, prepare, train, predict, score, source_bytes,
)


class SourceHeadTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = os.environ.get("HEPTA_ORIGINAL_EVENT_ZIP")
        if not source:
            raise RuntimeError("explicit immutable original source archive required")
        cls.source = Path(source)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.prep = cls.root / "prepared"
        prepare(cls.source, cls.prep)
        cls.train_file = cls.prep / "calibration-source-only.json"
        cls.public_file = cls.prep / "heldout-public-input.json"
        cls.train_sha = h(cls.train_file.read_bytes())
        cls.public_sha = h(cls.public_file.read_bytes())
        cls.policy = cls.root / "policy.json"
        train(cls.train_file, cls.policy, expected_sha=cls.train_sha)
        cls.policy_sha = h(cls.policy.read_bytes())
        cls.predictions = cls.root / "predictions.json"
        predict(cls.public_file, cls.policy, cls.predictions,
                data_sha=cls.public_sha, policy_sha=cls.policy_sha)
        cls.pred_sha = h(cls.predictions.read_bytes())
        cls.report = cls.root / "report.json"
        score(cls.source, cls.predictions, cls.policy, cls.report,
              predictions_sha=cls.pred_sha, policy_sha=cls.policy_sha)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def copy_as(self, document):
        path = self.root / ("mutant-" + str(len(list(self.root.glob("mutant-*")))) + ".json")
        dump(path, document)
        return path

    def test_exact_original_source_zip_and_label_blind_split(self):
        parsed = source_bytes(self.source)
        self.assertIn("plan", parsed)
        self.assertNotIn("labels", parsed)
        t, p = from_file(self.train_file), from_file(self.public_file)
        self.assertEqual(t["source_zip_sha256"], SOURCE_SHA)
        self.assertEqual(len(t["training_scopes"]), 8)
        self.assertEqual(len(p["heldout_scopes"]), 8)
        self.assertFalse(set(t["training_scopes"]) & set(p["heldout_scopes"]))
        self.assertNotIn("support", p["cases"][0])
        self.assertNotIn("expected", p["cases"][0])
        self.assertFalse(p["target_labels_present"])

    def test_real_192_step_torch_sgd_weights_update(self):
        receipt = from_file(self.policy)
        self.assertEqual(set(receipt["training"]), {"teacher_sgd", "shuffled_sgd"})
        for arm in ("teacher_sgd", "shuffled_sgd"):
            self.assertEqual(receipt["training"][arm]["gradient_updates"], STEPS)
            self.assertEqual(receipt["training"][arm]["parameter_count"], len(FEATURES))
            self.assertGreater(receipt["training"][arm]["actual_update_squared_l2"], 0)
        self.assertEqual(receipt["actual_model_generations"], 0)
        self.assertFalse(receipt["production_accepted"])

    def test_heldout_teacher_wins_weak_frozen_but_ties_strong_organized(self):
        report = from_file(self.report)
        m = report["arms"]
        self.assertEqual({a: m[a]["support_exact"] for a in ARMS}, {
            "frozen_rank_only": 3,
            "teacher_sgd": 8,
            "shuffled_sgd": 0,
            "frozen_organized": 8,
        })
        self.assertEqual(report["actual_new_model_generations"], 0)
        self.assertTrue(report["actual_torch_parameter_updates_verified_from_frozen_policy"])
        self.assertFalse(report["model_output_quality_measured"])
        self.assertEqual(report["independent_future_project_families"], 0)
        self.assertFalse(report["production_accepted"])

    def test_injected_test_gold_into_train_file_rejected_even_if_rehashed(self):
        x = from_file(self.train_file)
        x["evaluation_gold"] = [{"id": "secret", "answer": "site_wrong"}]
        path = self.copy_as(x)
        with self.assertRaisesRegex(ValueError, "train-only admitted"):
            train(path, self.root / "invalid-trained.json", expected_sha=h(path.read_bytes()))

    def test_unadmitted_training_cross_scope_document_rejected(self):
        x = from_file(self.train_file)
        x["cases"][0]["docs"][0]["scope"] = x["cases"][1]["scope"]
        path = self.copy_as(x)
        with self.assertRaisesRegex(ValueError, "train-only admitted"):
            train(path, self.root / "invalid-cross-source.json", expected_sha=h(path.read_bytes()))

    def test_trainable_head_cannot_copy_frozen_organizer_on_holdout(self):
        original = from_file(self.public_file)
        changed = deepcopy(original)
        for case in changed["cases"]:
            excluded = set(case["organized"])
            noncontrol = [
                ident for ident in case["candidate_ids"] if ident not in excluded
            ]
            self.assertGreaterEqual(len(noncontrol), len(case["organized"]))
            case["organized"] = noncontrol[: len(case["organized"])]
        altered_public = self.copy_as(changed)
        altered_predictions = self.root / "organizer-control-mutant-predictions.json"
        predict(
            altered_public,
            self.policy,
            altered_predictions,
            data_sha=h(altered_public.read_bytes()),
            policy_sha=self.policy_sha,
        )
        expected = from_file(self.predictions)["predictions"]
        actual = from_file(altered_predictions)["predictions"]
        self.assertEqual(len(actual), 32)
        for prior, changed_row in zip(expected, actual, strict=True):
            self.assertEqual((prior["scope"], prior["arm"]),
                             (changed_row["scope"], changed_row["arm"]))
            if prior["arm"] == "frozen_organized":
                self.assertNotEqual(prior["selected"], changed_row["selected"])
            else:
                self.assertEqual(prior["selected"], changed_row["selected"])
        with self.assertRaisesRegex(ValueError, "not bound"):
            score(
                self.source,
                altered_predictions,
                self.policy,
                self.root / "organizer-control-mutant-rejected.json",
                predictions_sha=h(altered_predictions.read_bytes()),
                policy_sha=self.policy_sha,
            )

    def test_injected_eval_targets_rejected_before_reader_choice(self):
        p = from_file(self.public_file)
        p["cases"][0]["target"] = "site_secret"
        source = self.copy_as(p)
        with self.assertRaises(ValueError):
            predict(source, self.policy, self.root / "leaked.json",
                    data_sha=h(source.read_bytes()), policy_sha=self.policy_sha)

    def test_invalid_policy_hash_rejected_before_testing(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            predict(self.public_file, self.policy, self.root / "wrong-pin.json",
                    data_sha=self.public_sha, policy_sha="0" * 64)

    def test_forged_model_update_claim_rejected_at_scoring(self):
        p = from_file(self.policy)
        p["training"]["teacher_sgd"]["gradient_updates"] = 0
        path = self.copy_as(p)
        with self.assertRaisesRegex(ValueError, "gradient-update provenance"):
            score(self.source, self.predictions, path, self.root / "fake-report.json",
                  predictions_sha=self.pred_sha, policy_sha=h(path.read_bytes()))

    def test_original_frozen_organizer_cannot_be_relabelled(self):
        pred = from_file(self.predictions)
        row = next(r for r in pred["predictions"] if r["arm"] == "frozen_organized")
        row["selected"] = list(reversed(row["selected"])) if len(row["selected"]) == 2 else ["out-of-pool"]
        path = self.copy_as(pred)
        with self.assertRaises(ValueError):
            score(self.source, path, self.policy, self.root / "altered-report.json",
                  predictions_sha=h(path.read_bytes()), policy_sha=self.policy_sha)

    def test_duplicate_task_arm_or_missing_attempt_rejected(self):
        pred = from_file(self.predictions)
        pred["predictions"][1] = deepcopy(pred["predictions"][0])
        path = self.copy_as(pred)
        with self.assertRaises(ValueError):
            score(self.source, path, self.policy, self.root / "dup-report.json",
                  predictions_sha=h(path.read_bytes()), policy_sha=self.policy_sha)

    def test_changed_original_outer_archive_is_rejected(self):
        path = self.root / "altered-source.zip"
        path.write_bytes(self.source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "wrong original"):
            source_bytes(path)

    def test_cannot_present_duplicate_json_keys_as_frozen_public_input(self):
        bad = self.root / "duplicate-source.json"
        bad.write_bytes(b'{"cases":[],"cases":[]}')
        with self.assertRaisesRegex(ValueError, "duplicate original JSON"):
            from_file(bad, h(bad.read_bytes()))


if __name__ == "__main__":
    unittest.main()
