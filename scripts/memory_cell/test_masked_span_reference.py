"""Authored inputs verify score provenance, not pretrained answer quality."""

from dataclasses import asdict, replace
import unittest

from masked_span_reference import original_pool, score_fields, training_fields
from native import Target
from selector_answer_metrics import answer_scores
from selector_windows import WindowBudget, candidate_windows
from test_span_supervision import corpus


class PublisherReferenceTests(unittest.TestCase):
    def setUp(self):
        self.corpus = corpus()
        self.query = self.corpus.queries[0]
        self.doc = self.corpus.documents[self.query.scope]
        self.budget = WindowBudget(window_bytes=192, stride_bytes=96)
        self.pool = candidate_windows(
            (self.doc,), self.query, revoked=set(), budget=self.budget
        )
        self.target = self.corpus.targets[self.query.identity]

    def record(self, *, null=False):
        query = self.corpus.queries[int(null)]
        target = self.corpus.targets[query.identity]
        pool = candidate_windows((self.doc,), query, revoked=set(), budget=self.budget)
        indices = target.indices(query, pool)
        row = dict(
            status="succeeded",
            answer="2024",
            selected=indices[0] if indices else None,
            target_unanswerable=null,
            selected_window_contains_annotated_answer=bool(indices),
            annotated_answer_visible_in_pool=bool(indices) if not null else None,
            **answer_scores("2024", tuple(s[2] for s in target.spans), null),
        )
        return row, target, query, pool

    def test_scores_recomputed_from_original_labels_not_claimed_summary(self):
        row, target, query, pool = self.record()
        self.assertEqual(
            score_fields(row, target, query, pool, external=True)["f1"], 1.0
        )
        for key, value in (
            ("f1", 0.5),
            ("exact_match", True),
            ("target_unanswerable", True),
            ("selected_window_contains_annotated_answer", False),
            ("annotated_answer_visible_in_pool", False),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                score_fields(
                    dict(row, **{key: value}), target, query, pool, external=True
                )
        changed = replace(target, spans=((0, len("東京".encode()), "東京"),))
        with self.assertRaises(ValueError):
            score_fields(row, changed, query, pool, external=True)

    def test_unanswerable_unsupported_generation_does_not_become_success(self):
        row, target, query, pool = self.record(null=True)
        self.assertEqual(
            score_fields(row, target, query, pool, external=True)["f1"], 0.0
        )
        with self.assertRaises(ValueError):
            score_fields(dict(row, f1=1.0), target, query, pool, external=True)

    def test_native_unscored_cases_stay_unscored_without_invented_spans(self):
        row = dict(
            status="succeeded",
            answer="2024",
            selected=None,
            target_unanswerable=None,
            selected_window_contains_annotated_answer=None,
            annotated_answer_visible_in_pool=None,
            exact_match=None,
            f1=None,
        )
        target = Target(None, "unscored", (), False)
        self.assertIsNone(
            score_fields(row, target, self.query, self.pool, external=False)["f1"]
        )
        with self.assertRaises(ValueError):
            score_fields(
                dict(row, f1=0.0), target, self.query, self.pool, external=False
            )
        with self.assertRaises(ValueError):
            score_fields(
                dict(row, status="failed"),
                target,
                self.query,
                self.pool,
                external=False,
            )

    def test_original_unicode_source_and_query_reconstruct_exact_windows(self):
        self.assertEqual(
            original_pool(
                self.query,
                (self.doc,),
                asdict(self.pool),
                [asdict(self.doc)],
                self.budget,
            ),
            self.pool,
        )
        for key, value in (
            ("content", self.doc.content + " changed"),
            ("observed_at", "2099"),
            ("identity", "replacement"),
        ):
            damaged = dict(asdict(self.doc), **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                original_pool(
                    self.query, (self.doc,), asdict(self.pool), [damaged], self.budget
                )
        with self.assertRaises(ValueError):
            original_pool(
                replace(self.query, content="changed query"),
                (self.doc,),
                asdict(self.pool),
                [asdict(self.doc)],
                self.budget,
            )

    def test_candidate_rewrite_rejected_even_with_recomputed_transport_hashes(self):
        for change in (
            lambda p: p["windows"][0].update(start=-2),
            lambda p: p["windows"].pop(),
            lambda p: p.update(enumerated_windows=0),
        ):
            serialized = asdict(self.pool)
            serialized["windows"] = [dict(w) for w in serialized["windows"]]
            change(serialized)
            with self.assertRaises(ValueError):
                original_pool(
                    self.query, (self.doc,), serialized, [asdict(self.doc)], self.budget
                )

    def test_source_membership_and_duplicates_cannot_be_relabelled(self):
        with self.assertRaises(ValueError):
            original_pool(
                self.query, (), asdict(self.pool), [asdict(self.doc)], self.budget
            )
        with self.assertRaises(ValueError):
            original_pool(
                self.query,
                (self.doc, self.doc),
                asdict(self.pool),
                [asdict(self.doc)],
                self.budget,
            )

    def test_window_labels_recomputed_from_external_span_not_document_membership(self):
        ids = [w.identity() for w in self.pool.windows]
        positive = self.target.indices(self.query, self.pool)
        note = dict(
            question_id=self.query.identity,
            annotation_digest=self.target.annotation_digest,
            pool_digest=self.pool.seal(),
            positive_ids=[ids[i] for i in positive],
            negative_ids=[],
            unknown_ids=[ids[i] for i in range(len(ids)) if i not in positive],
            unanswerable=False,
            negative_scope="only the externally annotated unanswerable paragraph",
            status="external_tri_state_window_supervision",
        )
        training_fields(note, self.query, self.target, self.pool)
        self.assertTrue(note["unknown_ids"])
        for field, value in (
            ("positive_ids", ids),
            ("negative_ids", note["unknown_ids"]),
            ("annotation_digest", "forged"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                training_fields(
                    dict(note, **{field: value}), self.query, self.target, self.pool
                )


if __name__ == "__main__":
    unittest.main()
