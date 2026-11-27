"""Synthetic contract tests; no model results or validation claim."""

from types import SimpleNamespace as Obj
import unittest

import numpy as np

from stem_lexical_terms import content_terms, query_filtered
from stem_lexical_probe import PHASES, ARMS, census, choose_from_train, assess


def sample():
    groups = {"train": [f"train-{i}" for i in range(48)]}
    groups.update({p: [f"{p}-{i}" for i in range(8)] for p in PHASES[1:]})
    plan = dict(
        questions=groups,
        question_families={
            q: f"family-{i % 5}"
            for group in groups.values()
            for i, q in enumerate(group)
        },
    )
    rows, labels = [], {}
    for phase in PHASES:
        for qid in groups[phase]:
            labels[qid] = Obj(
                unanswerable=False, unresolved_evidence=(), evidence=("supported",)
            )
            for arm in ARMS:
                positive = arm == "filtered" or qid.endswith("-7")
                rows.append(
                    dict(
                        phase=phase,
                        question_id=qid,
                        arm=arm,
                        source_family=plan["question_families"][qid],
                        index_sha256="a" * 64,
                        encoder_identity="pinned",
                        top_k=8,
                        channel_k=64,
                        lexical_weight=0.5,
                        original_pool_sha256="b" * 64,
                        pool_sha256="b" * 64 if arm == "legacy" else "c" * 64,
                        pool_matches_original=True if arm == "legacy" else None,
                        retrieved_source_ids=["supported", "distractor"],
                        window_source_ids=["supported"] if positive else ["distractor"],
                        labels_unread=True,
                        reader_calls=0,
                    )
                )
    return plan, rows, labels


class QueryTermTests(unittest.TestCase):
    def test_function_words_are_removed_but_entities_and_dates_stay(self):
        self.assertEqual(
            content_terms("What was Alice's account in 2026?"),
            ("alice", "s", "account", "2026"),
        )
        self.assertEqual(content_terms("the and or"), ("the", "and", "or"))
        self.assertEqual(content_terms("明天在东京"), ("明天在东京",))
        self.assertEqual(content_terms("?!"), ())

    def test_invalid_content_fails_instead_of_creating_unbounded_fts(self):
        for text in ("", " ", "a" * 16385, None):
            with self.subTest(text=str(text)[:12]), self.assertRaises(ValueError):
                content_terms(text)

    def test_bound_finite_same_vector_retains_index_and_scope(self):
        class DB:
            def execute(self, sql, args):
                self.sql, self.args = sql, args
                return [(2,), (1,)]

        class FakeIndex:
            meta = {"scope": "scope", "encoder": "pinned"}
            documents = [Obj(identity="d0"), Obj(identity="d1")]
            vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
            file_digest = "a" * 64
            db = DB()

            def revalidate(self, cut, revoked):
                if cut != "cut" or revoked:
                    raise ValueError("invalid cut")

        obj = FakeIndex()
        policy = Obj(
            top_k=2,
            channel_k=2,
            lexical_weight=0.5,
            rrf_constant=60,
            validate=lambda: None,
        )
        docs, receipt = query_filtered(
            obj,
            Obj(scope="scope", content="What was ALICE in 2026?"),
            np.array([1.0, 0.0]),
            policy,
            current_cut="cut",
            revoked=set(),
        )
        self.assertEqual(len(docs), 2)
        self.assertEqual(receipt["lexical_term_count"], 2)
        self.assertEqual(obj.db.args[0], '"alice" OR "2026"')
        self.assertEqual(receipt["original_index_sha256"], "a" * 64)
        obj.db.sql = None
        docs, _ = query_filtered(
            obj,
            Obj(scope="scope", content="?!"),
            np.array([1.0, 0.0]),
            policy,
            current_cut="cut",
            revoked=set(),
        )
        self.assertEqual(len(docs), 2)
        self.assertIsNone(obj.db.sql)
        with self.assertRaises(ValueError):
            query_filtered(
                obj,
                Obj(scope="other", content="alice"),
                np.array([1.0, 0.0]),
                policy,
                current_cut="cut",
                revoked=set(),
            )
        with self.assertRaises(ValueError):
            query_filtered(
                obj,
                Obj(scope="scope", content="alice"),
                np.array([float("nan"), 0.0]),
                policy,
                current_cut="cut",
                revoked=set(),
            )

    def test_all_160_original_source_records_must_exist(self):
        plan, rows, labels = sample()
        self.assertEqual(len(census(plan, rows)), 160)
        for mutation in ("missing", "duplicate", "index", "gold"):
            p, items, _ = sample()
            if mutation == "missing":
                items.pop()
            elif mutation == "duplicate":
                items[-1] = items[0]
            elif mutation == "index":
                items[1]["index_sha256"] = "b" * 64
            else:
                items[1]["labels_unread"] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                census(p, items)

    def test_partial_two_hop_support_is_not_full_coverage(self):
        from stem_lexical_probe import weak_hit

        target = Obj(
            unanswerable=False,
            unresolved_evidence=(),
            evidence=("supported", "other"),
        )
        self.assertFalse(weak_hit({"window_source_ids": ["supported"]}, target))
        self.assertTrue(weak_hit({"window_source_ids": ["supported", "other"]}, target))
        self.assertIsNone(
            weak_hit(
                {"window_source_ids": ["supported"]},
                Obj(unanswerable=True, unresolved_evidence=(), evidence=()),
            )
        )

    def test_train_select_only_and_holdout_outcomes_are_distinct(self):
        plan, rows, targets = sample()
        records = census(plan, rows)
        with self.assertRaises(ValueError):
            choose_from_train(plan, records, targets)
        train = {q: targets[q] for q in plan["questions"]["train"]}
        selected = choose_from_train(plan, records, train)
        self.assertEqual(selected["selected"], "filtered")
        heldout = {q: targets[q] for p in PHASES[1:] for q in plan["questions"][p]}
        report = assess(plan, records, heldout, selected)
        self.assertEqual(report["by_phase"]["test"]["gains"], 7)
        self.assertEqual(report["by_phase"]["test"]["losses"], 0)
        self.assertFalse(report["production_accepted"])
        with self.assertRaises(ValueError):
            assess(plan, records, targets, selected)

    def test_no_train_advantage_keeps_the_frozen_legacy_policy(self):
        plan, rows, targets = sample()
        for row in rows:
            if row["phase"] == "train" and row["arm"] == "filtered":
                row["window_source_ids"] = (
                    ["supported"]
                    if row["question_id"].endswith("-7")
                    else ["distractor"]
                )
        selected = choose_from_train(
            plan,
            census(plan, rows),
            {q: targets[q] for q in plan["questions"]["train"]},
        )
        self.assertEqual(selected["selected"], "legacy")
        self.assertTrue(selected["no_heldout_question_labels_seen"])


if __name__ == "__main__":
    unittest.main()
