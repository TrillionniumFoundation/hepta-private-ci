"""Negative controls for a real-model runner; these do NOT generate answers."""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from native import digest
from reader_bottleneck_ablation import (
    ARMS,
    QWEN_INVENTORY,
    _commit,
    _paired,
    freeze_case,
    selection,
    validate_row,
)


def fixture():
    ids = [f"event_{i}" for i in range(6)]
    case = {
        "query": {"identity": "q1", "scope": "q1"},
        "kind": "composition",
        "candidate_ids": ids,
        "candidate_digest": digest(tuple(ids)),
        "frontier": "2026-10-12",
        "controls": {
            "hybrid": {"selected": ids[:4]},
            "program_support": {"selected": [ids[2], ids[3]]},
            "without_prerequisite": {"selected": [ids[3]]},
            "empty": {"selected": []},
        },
    }
    originals = {key: SimpleNamespace(scope="q1") for key in ids}
    return case, originals


def answer(arm, selected, *, identity=QWEN_INVENTORY):
    return dict(
        question_id="q1",
        kind="composition",
        arm=arm,
        candidate_digest=digest(tuple(f"event_{i}" for i in range(6))),
        selected=list(selected),
        status="succeeded",
        receipt=dict(
            reader_identity=identity,
            trainable_parameters=0,
            answer_postprocessed=False,
            semantic_citation_precision=None,
            independent_semantic_review=False,
            delivered_evidence=[{"original_id": key} for key in selected],
            input_tokens=128,
        ),
    )


class BottleneckAblationTests(unittest.TestCase):
    def test_premise_removed_from_declared_support_not_retrieval(self):
        case, docs = fixture()
        arms, critical = selection(case, docs)
        self.assertEqual(tuple(arms), ARMS)
        self.assertEqual(critical, "event_2")
        self.assertEqual(arms["minus_one"], ("event_3",))
        self.assertEqual(arms["declared_support"], ("event_2", "event_3"))
        self.assertEqual(arms["selected_k"], ("event_0",))
        self.assertEqual(arms["hybrid_k4"], tuple(f"event_{i}" for i in range(4)))
        self.assertEqual(arms["none"], ())

    def test_one_source_ablation_becomes_empty(self):
        case, docs = fixture()
        case["controls"]["program_support"]["selected"] = ["event_4"]
        case["controls"]["without_prerequisite"]["selected"] = []
        arms, critical = selection(case, docs)
        self.assertEqual(critical, "event_4")
        self.assertEqual(arms["minus_one"], ())

    def test_critical_source_is_never_chosen_from_answers(self):
        case, docs = fixture()
        original = deepcopy(case)
        first = selection(case, docs)
        second = selection(case, docs)
        self.assertEqual(first, second)
        self.assertEqual(case, original)

    def test_reject_candidate_order_or_digest_drift(self):
        case, docs = fixture()
        case["candidate_ids"].reverse()
        with self.assertRaisesRegex(ValueError, "retrieval candidates"):
            selection(case, docs)

    def test_reject_hybrid_replaced_with_weak_control(self):
        case, docs = fixture()
        case["controls"]["hybrid"]["selected"] = ["event_0"]
        with self.assertRaisesRegex(ValueError, "declared support"):
            selection(case, docs)

    def test_reject_unavailable_or_cross_scope_declared_source(self):
        for source, docs_change in (
            ("unknown", False),
            ("event_2", True),
        ):
            with self.subTest(source=source):
                case, docs = fixture()
                if docs_change:
                    docs[source] = SimpleNamespace(scope="other")
                else:
                    case["controls"]["program_support"]["selected"] = [source]
                with self.assertRaisesRegex(ValueError, "declared support"):
                    selection(case, docs)

    def test_reject_duplicate_critical_premises(self):
        case, docs = fixture()
        case["controls"]["program_support"]["selected"] = ["event_2", "event_2"]
        with self.assertRaises(ValueError):
            selection(case, docs)

    def test_reject_empty_declared_evidence(self):
        case, docs = fixture()
        case["controls"]["program_support"]["selected"] = []
        with self.assertRaises(ValueError):
            selection(case, docs)

    def test_no_reference_identity_drift_or_evidence_leak(self):
        case, docs = fixture()
        arms, _ = selection(case, docs)
        base = answer("declared_support", arms["declared_support"])
        validate_row(base, case, arms, QWEN_INVENTORY)
        for field, value in (
            ("reader_identity", "wrong"),
            ("trainable_parameters", 5),
            ("answer_postprocessed", True),
            ("semantic_citation_precision", 1.0),
            ("independent_semantic_review", True),
            ("input_tokens", 9999),
        ):
            with self.subTest(field=field):
                changed = deepcopy(base)
                changed["receipt"][field] = value
                with self.assertRaisesRegex(ValueError, "identity"):
                    validate_row(changed, case, arms, QWEN_INVENTORY)

    def test_uses_original_registered_prerequisite_deletion(self):
        case, docs = fixture()
        case["controls"]["without_prerequisite"]["selected"] = ["event_2"]
        with self.assertRaisesRegex(ValueError, "declared support"):
            selection(case, docs)

    def test_rejects_authored_empty_control_with_hidden_source(self):
        case, docs = fixture()
        case["controls"]["empty"]["selected"] = ["event_0"]
        with self.assertRaisesRegex(ValueError, "declared support"):
            selection(case, docs)

    def test_original_reader_requires_explicit_negative_semantic_review_flag(self):
        case, docs = fixture()
        arms, _ = selection(case, docs)
        row = answer("declared_support", arms["declared_support"])
        validate_row(row, case, arms, QWEN_INVENTORY)
        missing = deepcopy(row)
        missing["receipt"].pop("independent_semantic_review")
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_row(missing, case, arms, QWEN_INVENTORY)
        row["receipt"]["independent_semantic_review"] = True
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_row(row, case, arms, QWEN_INVENTORY)

    def test_delivered_ids_must_match_actual_selection_and_order(self):
        case, docs = fixture()
        arms, _ = selection(case, docs)
        base = answer("declared_support", arms["declared_support"])
        base["receipt"]["delivered_evidence"].reverse()
        with self.assertRaisesRegex(ValueError, "actual delivery"):
            validate_row(base, case, arms, QWEN_INVENTORY)

    def test_unexpected_arm_and_wrong_selected_set_fail(self):
        case, docs = fixture()
        arms, _ = selection(case, docs)
        for key, value in (
            ("arm", "invented"),
            ("selected", ["event_5"]),
            ("candidate_digest", "f" * 64),
        ):
            with self.subTest(key=key):
                changed = answer("selected_k", arms["selected_k"])
                changed[key] = value
                with self.assertRaises(ValueError):
                    validate_row(changed, case, arms, QWEN_INVENTORY)

    def test_failed_original_attempt_is_not_silent_success(self):
        case, docs = fixture()
        arms, _ = selection(case, docs)
        row = answer("selected_k", arms["selected_k"])
        row["status"] = "failed"
        validate_row(row, case, arms, QWEN_INVENTORY)
        group = {
            "q1": {
                "left": {"status": "failed", "strict_task_success": False},
                "right": {"status": "succeeded", "strict_task_success": True},
            }
        }
        self.assertEqual(_paired(group, "left", "right")["missing"], 1)

    def test_paired_direction_and_unknown_denominator(self):
        group = {
            "q1": {
                "small": {"status": "succeeded", "strict_task_success": False},
                "large": {"status": "succeeded", "strict_task_success": True},
            },
            "q2": {
                "small": {"status": "succeeded", "strict_task_success": True},
                "large": {"status": "succeeded", "strict_task_success": False},
            },
            "q3": {
                "small": {"status": "succeeded", "strict_task_success": True},
                "large": {"status": "succeeded", "strict_task_success": True},
            },
        }
        self.assertEqual(
            _paired(group, "small", "large"),
            dict(wins=1, losses=1, ties=1, missing=0),
        )

    def test_freeze_has_no_targets_and_no_review_attestation(self):
        case, originals = fixture()
        locked = {"cases": [case] * 8}
        with patch(
            "reader_bottleneck_ablation._plan", return_value=(locked, originals)
        ):
            _, _, _, frozen = freeze_case("does-not-open", 0)
        self.assertFalse(frozen["target_labels_exposed"])
        self.assertFalse(frozen["independent_semantic_review"])
        self.assertTrue(frozen["declared_support_not_human_reviewed"])
        self.assertFalse(frozen["production_accepted"])
        self.assertNotIn("expected_answer", frozen)

    def test_commit_must_be_exact_git_sha(self):
        with patch.dict("os.environ", {"HEPTA_MEMORY_TESTED_COMMIT": "fake"}):
            with self.assertRaisesRegex(ValueError, "commit"):
                _commit()


if __name__ == "__main__":
    unittest.main()
