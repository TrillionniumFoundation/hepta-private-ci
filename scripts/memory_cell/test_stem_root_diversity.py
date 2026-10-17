"""Pure root-diverse ablation contracts; synthetic rows never model results."""

import unittest

from stem_root_diversity import (
    root_distinct,
    validate_diverse_receipts,
    compare_diversity,
)
from stem_frozen_retrieval_grid import BASELINE, label_key, validate_unlabelled
from test_stem_frozen_retrieval_grid import fixture
from sessions import source_id


def varied_fixture():
    plan, rows, targets = fixture()
    for row in rows:
        if row["policy"] == label_key(BASELINE):
            row["retrieved_source_ids"] = ["source-distractor", "source-duplicate"]
            row["window_source_ids"] = ["source-distractor"]
    registered = validate_unlabelled(plan, rows)
    alternative = []
    for phase, ids in plan["questions"].items():
        for qid in ids:
            top = registered[(phase, qid, label_key(BASELINE))]
            ranked = [
                {"id": "source-distractor", "root": "same-root"},
                {"id": "source-duplicate", "root": "same-root"},
                {"id": "source-positive", "root": "new-root"},
            ]
            chosen = root_distinct(ranked, 2)
            alternative.append(
                dict(
                    phase=phase,
                    question_id=qid,
                    source_family=top["source_family"],
                    original_as_of_index_sha256=top["original_as_of_index_sha256"],
                    original_baseline_source_ids=top["retrieved_source_ids"],
                    ranked_original_source_roots=ranked,
                    selected_original_identities=chosen,
                    retrieved_source_ids=[source_id(x) for x in chosen],
                    window_source_ids=[source_id(x) for x in chosen],
                    pool_sha256="f" * 64,
                    source_text_exported=False,
                    read_targets_for_retrieval=False,
                    pretrained_reader_calls=0,
                )
            )
    return plan, registered, alternative, targets


class RootDiversityTests(unittest.TestCase):
    def test_preserves_identity_and_first_root_representatives(self):
        ranked = [
            {"id": "A", "root": "one"},
            {"id": "B", "root": "one"},
            {"id": "C", "root": "two"},
            {"id": "D", "root": "two"},
            {"id": "E", "root": "three"},
        ]
        self.assertEqual(root_distinct(ranked, 3), ["A", "C", "E"])
        self.assertEqual(root_distinct(ranked, 4), ["A", "C", "E", "B"])
        self.assertEqual(root_distinct(ranked[:2], 2), ["A", "B"])

    def test_duplicate_ids_or_invalid_source_roots_fail_closed(self):
        for ranked in (
            [{"id": "x", "root": "r"}, {"id": "x", "root": "r"}],
            [{"id": "x", "root": ""}],
            [{"id": "x", "root": "r", "answer": "leaked"}],
        ):
            with self.subTest(ranked=ranked), self.assertRaises(ValueError):
                root_distinct(ranked, 2)
        with self.assertRaises(ValueError):
            root_distinct([{"id": "x", "root": "r"}], 9)

    def test_80_question_census_evaluates_only_after_candidate_freeze(self):
        plan, original, raw, targets = varied_fixture()
        diverse = validate_diverse_receipts(plan, original, raw)
        report = compare_diversity(plan, original, diverse, targets)
        self.assertEqual(len(diverse), 80)
        self.assertEqual(report["results"]["test"]["planned"], 8)
        self.assertEqual(report["results"]["test"]["document_rescues"], 8)
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["statistical_superiority_established"])

    def test_cannot_smuggle_reordered_topk_labels_or_changed_cut(self):
        for mode in ("rank", "selected", "pool", "source", "review", "duplicate"):
            plan, original, raw, _ = varied_fixture()
            if mode == "rank":
                raw[0]["ranked_original_source_roots"][0]["id"] = "wrong"
            elif mode == "selected":
                raw[0]["selected_original_identities"] = ["source-positive"]
            elif mode == "pool":
                raw[0]["pool_sha256"] = ""
            elif mode == "source":
                raw[0]["original_as_of_index_sha256"] = "a" * 64
            elif mode == "review":
                raw[0]["read_targets_for_retrieval"] = True
            else:
                raw[-1] = raw[0]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_diverse_receipts(plan, original, raw)

    def test_unknown_labels_preserved_and_test_labels_not_used_for_choice(self):
        from types import SimpleNamespace

        plan, original, raw, targets = varied_fixture()
        diverse = validate_diverse_receipts(plan, original, raw)
        targets["test-0"] = SimpleNamespace(
            unanswerable=True, unresolved_evidence=(), evidence=()
        )
        x = compare_diversity(plan, original, diverse, targets)
        self.assertEqual(x["results"]["test"]["unscored_native_label"], 1)
        with self.assertRaises(ValueError):
            compare_diversity(
                plan,
                original,
                diverse,
                {k: v for k, v in targets.items() if k != "test-0"},
            )


if __name__ == "__main__":
    unittest.main()
