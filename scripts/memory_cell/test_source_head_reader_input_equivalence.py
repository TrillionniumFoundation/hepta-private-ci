"""Synthetic adversarial controls, not model outcomes or actual training results."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from source_head_reader_input_equivalence import audit, compare
from source_head_sgd_original import ARMS, FEATURES, PROFILE, SOURCE_SHA, canonical, h


def fixture():
    scopes = [f"controlled_{k:08x}" for k in range(8)]
    cases = []
    rows = []
    for scope in scopes:
        candidates = [f"{scope}-e0", f"{scope}-e1"]
        cases.append(
            dict(
                scope=scope,
                kind="new_fact",
                candidate_ids=candidates,
                organized=candidates[:1],
                path=["location"],
            )
        )
        cases[-1]["docs"] = [
            dict(
                identity=identity,
                scope=scope,
                content=json.dumps({"id": identity, "value": "source-only"}),
                observed_at="2026-10-10T00:00:00+00:00",
            )
            for identity in candidates
        ]
        for arm in ARMS:
            rows.append(
                dict(
                    scope=scope,
                    kind="new_fact",
                    arm=arm,
                    selected=candidates[:1],
                    evidence_candidate_pool_sha256=h(canonical(candidates)),
                    trainable_parameters=len(FEATURES) if "sgd" in arm else 0,
                    actual_reader_model_calls=0,
                    independent_semantic_review=False,
                )
            )
    public_sha = "a" * 64
    weights_sha = "b" * 64
    predictions_sha = "c" * 64
    public = dict(
        profile=PROFILE,
        source_zip_sha256=SOURCE_SHA,
        target_labels_present=False,
        calibration_sources_present=False,
        heldout_scopes=scopes,
        cases=cases,
    )
    weights = dict(
        profile=PROFILE,
        frozen_before_test=True,
        tested_questions_exposed=False,
        heldout_task_metric=None,
        actual_model_generations=0,
        production_accepted=False,
        feature_keys=list(FEATURES),
        training={
            arm: dict(
                gradient_updates=192,
                parameter_count=len(FEATURES),
                actual_update_squared_l2=0.1,
            )
            for arm in ("teacher_sgd", "shuffled_sgd")
        },
    )
    predictions = dict(
        profile=PROFILE,
        public_test_data_sha256=public_sha,
        policy_sha256=weights_sha,
        heldout_label_bytes_opened=False,
        original_model_calls=0,
        no_future_window_independence=True,
        production_accepted=False,
        predictions=rows,
    )
    return public, weights, predictions, public_sha, weights_sha, predictions_sha


def check(args):
    return compare(args[0], args[1], args[2], public_sha=args[3], weights_sha=args[4], predictions_sha=args[5])


class ReaderInputIdentityTests(unittest.TestCase):
    def test_all_eight_matched_selectors_cannot_show_learning_lift(self):
        result = check(fixture())
        self.assertEqual(result["matched_choice_tasks"], 8)
        self.assertEqual(result["distinct_choice_tasks"], 0)
        self.assertEqual(result["matching_original_evidence_byte_tasks"], 8)
        self.assertTrue(result["exact_frozen_source_bytes_present"])
        self.assertTrue(
            all(row["exact_original_delivery_bytes_same"] for row in result["per_scope"])
        )
        self.assertEqual(result["model_answers_generated_in_audit"], 0)
        self.assertFalse(result["exact_response_gain_over_strong_frozen_organizer_proven"])
        self.assertFalse(result["production_accepted"])

    def test_one_real_selection_disagreement_is_recorded_not_marked_as_success(self):
        args = list(deepcopy(fixture()))
        next(r for r in args[2]["predictions"] if r["arm"] == "teacher_sgd")["selected"] = [args[0]["cases"][0]["candidate_ids"][1]]
        report = check(args)
        self.assertEqual(report["matched_choice_tasks"], 7)
        self.assertEqual(report["distinct_choice_tasks"], 1)
        self.assertFalse(report["exact_response_gain_over_strong_frozen_organizer_proven"])

    def test_tampering_with_frozen_organizer_is_not_allowed(self):
        args = list(deepcopy(fixture()))
        args[2]["predictions"][3]["selected"] = [args[0]["cases"][0]["candidate_ids"][1]]
        with self.assertRaisesRegex(ValueError, "source pool drift"):
            check(args)

    def test_missing_or_duplicated_original_prediction_rejected(self):
        for action in ("remove", "duplicate"):
            args = list(deepcopy(fixture()))
            if action == "remove":
                args[2]["predictions"].pop()
            else:
                args[2]["predictions"][1] = deepcopy(args[2]["predictions"][0])
            with self.subTest(action=action), self.assertRaises(ValueError):
                check(args)

    def test_candidate_pool_digest_drift_is_rejected(self):
        args = list(deepcopy(fixture()))
        args[2]["predictions"][0]["evidence_candidate_pool_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "source pool drift"):
            check(args)

    def test_training_update_receipt_cannot_be_missing_or_forged(self):
        for k, v in (("gradient_updates", 0), ("parameter_count", 200), ("actual_update_squared_l2", 0)):
            args = list(deepcopy(fixture()))
            args[1]["training"]["teacher_sgd"][k] = v
            with self.subTest(k=k), self.assertRaisesRegex(ValueError, "provenance"):
                check(args)

    def test_after_gold_or_model_answer_flags_are_rejected(self):
        args = list(deepcopy(fixture()))
        args[2]["heldout_label_bytes_opened"] = True
        with self.assertRaisesRegex(ValueError, "provenance"):
            check(args)
        args = list(deepcopy(fixture()))
        args[2]["predictions"][0]["actual_reader_model_calls"] = 1
        with self.assertRaisesRegex(ValueError, "source pool drift"):
            check(args)

    def test_public_and_trained_identity_mismatch_rejected(self):
        args = list(deepcopy(fixture()))
        args[2]["policy_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "provenance"):
            check(args)
        args = list(deepcopy(fixture()))
        args[0]["source_zip_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "provenance"):
            check(args)

    def test_file_sha_is_checked_before_parsing(self):
        args = list(deepcopy(fixture()))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for name, value in zip(("public", "weights", "predictions"), args[:3], strict=True):
                path = root / f"{name}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                files.append(path)
            with self.assertRaisesRegex(ValueError, "checksum"):
                audit(*files, public_sha="0" * 64, weights_sha="1" * 64, predictions_sha="2" * 64)

    def test_missing_frozen_event_bytes_are_rejected(self):
        args = list(deepcopy(fixture()))
        args[0]["cases"][0]["docs"].pop()
        with self.assertRaisesRegex(ValueError, "frozen source bytes"):
            check(args)

    def test_duplicate_source_identity_and_wrong_scope_are_rejected(self):
        for wrong in ("duplicate", "wrong_scope"):
            args = list(deepcopy(fixture()))
            sources = args[0]["cases"][0]["docs"]
            if wrong == "duplicate":
                sources[1]["identity"] = sources[0]["identity"]
            else:
                sources[0]["scope"] = "other-scope"
            with self.subTest(wrong=wrong):
                with self.assertRaisesRegex(ValueError, "source bytes"):
                    check(args)

    def test_false_source_event_body_identity_cannot_preserve_reader_input(self):
        args = list(deepcopy(fixture()))
        args[0]["cases"][0]["docs"][0]["content"] = json.dumps(
            {"id": "an-unrelated-event", "value": "forged"}
        )
        with self.assertRaisesRegex(ValueError, "body identity"):
            check(args)

    def test_no_answerable_readout_without_actual_reader(self):
        value = check(fixture())
        self.assertFalse(value["reader_capacity_effect_measured"])
        self.assertFalse(value["exact_response_gain_over_strong_frozen_organizer_proven"])
        self.assertEqual(value["prospective_source_family_count"], 0)
        self.assertFalse(value["independent_sufficient_evidence_review"])


if __name__ == "__main__":
    unittest.main()
