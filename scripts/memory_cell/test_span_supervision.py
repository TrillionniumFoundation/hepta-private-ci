"""Authored fixtures test external-span transport, not human model performance."""

from dataclasses import replace
import hashlib
import json
import unittest

import torch

from native import digest
from selector_head import Features, TrainingCut
from selector_windows import WindowBudget, candidate_windows
from span_supervision import parse_corpus, sample_families, supervised_rows


def raw_fixture():
    context = (
        "東京 café. "
        + "The first paragraph gives no date. " * 8
        + "The launch happened in 2024."
    )
    answer = "2024"
    return dict(
        version="v2.0",
        data=[
            dict(
                title="Launch",
                paragraphs=[
                    dict(
                        context=context,
                        qas=[
                            dict(
                                id="date",
                                question="When did the launch happen?",
                                is_impossible=False,
                                answers=[
                                    dict(
                                        answer_start=context.index(answer), text=answer
                                    )
                                ],
                            ),
                            dict(
                                id="absent",
                                question="Who funded the launch?",
                                is_impossible=True,
                                answers=[],
                                plausible_answers=[dict(answer_start=0, text="東京")],
                            ),
                        ],
                    )
                ],
            )
        ],
    )


def corpus(obj=None):
    raw = json.dumps(obj or raw_fixture(), ensure_ascii=False).encode()
    blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    return parse_corpus(raw, "train", expected_blob=blob)


class ExternalSpanTests(unittest.TestCase):
    def test_unicode_offsets_are_not_character_offsets(self):
        c = corpus()
        q = c.queries[0]
        t, d = c.targets[q.identity], c.documents[q.scope]
        start, end, answer = t.spans[0]
        self.assertEqual(d.content.encode()[start:end].decode(), answer)
        self.assertGreater(start, d.content.index(answer))
        pool = candidate_windows(
            (d,),
            q,
            revoked=set(),
            budget=WindowBudget(window_bytes=192, stride_bytes=96),
        )
        self.assertTrue(t.indices(q, pool))
        self.assertLess(len(t.indices(q, pool)), len(pool.windows))

    def test_plausible_answer_is_not_positive_for_human_unanswerable(self):
        c = corpus()
        q = c.queries[1]
        pool = candidate_windows((c.documents[q.scope],), q, revoked=set())
        self.assertEqual(c.targets[q.identity].indices(q, pool), ())
        self.assertTrue(c.targets[q.identity].unanswerable)

    def test_missing_positive_is_skipped_not_trained_as_null(self):
        c = corpus()
        q = c.queries[0]
        pool = candidate_windows(
            (c.documents[q.scope],),
            q,
            revoked=set(),
            budget=WindowBudget(window_bytes=128, stride_bytes=64),
            profile="prefix",
        )
        f = Features(
            q.identity,
            q.family,
            "test-encoder",
            pool.seal(),
            tuple(w.identity() for w in pool.windows),
            frozenset([q.scope]),
            torch.ones(len(pool.windows), 2),
            torch.zeros(len(pool.windows)),
        )
        cut = TrainingCut(
            frozenset([q.identity]),
            frozenset([q.family]),
            f.roots,
            frozenset(),
            "test-only-cut",
        )
        rows, notes = supervised_rows((q,), c, {q.identity: pool}, {q.identity: f}, cut)
        self.assertEqual(rows, ())
        self.assertEqual(
            notes[0]["status"], "annotated_span_not_visible_not_a_null_target"
        )

    def test_forbidden_question_is_rejected_before_annotations(self):
        class Trap(dict):
            def __getitem__(self, key):
                raise AssertionError("heldout annotation read")

        c = corpus()
        cut = TrainingCut(
            frozenset(), frozenset(), frozenset(), frozenset(), "test-cut"
        )
        with self.assertRaisesRegex(ValueError, "outside external training cut"):
            supervised_rows(c.queries, replace(c, targets=Trap()), {}, {}, cut)

    def test_question_source_or_span_mutation_rejects(self):
        c = corpus()
        q = c.queries[0]
        pool = candidate_windows((c.documents[q.scope],), q, revoked=set())
        with self.assertRaises(ValueError):
            c.targets[q.identity].indices(replace(q, content="different"), pool)
        t = c.targets[q.identity]
        start, end, _ = t.spans[0]
        with self.assertRaises(ValueError):
            replace(t, spans=((start, end, "xxxx"),)).indices(q, pool)

    def test_pin_schema_and_annotation_errors_fail_closed(self):
        with self.assertRaises(ValueError):
            parse_corpus(b"{}", "train", expected_blob="0" * 40)
        for change in (
            lambda r: r.update(is_impossible=1),
            lambda r: r.update(answers=[]),
            lambda r: r["answers"][0].update(answer_start=-1),
            lambda r: r["answers"][0].update(text="wrong"),
        ):
            obj = raw_fixture()
            change(obj["data"][0]["paragraphs"][0]["qas"][0])
            with self.assertRaises(ValueError):
                corpus(obj)

    def test_sampling_is_invariant_to_annotations(self):
        c = corpus()
        chosen = sample_families(c.queries, {q.family for q in c.queries}, 2)
        obj = raw_fixture()
        obj["data"][0]["paragraphs"][0]["qas"][0]["answers"][0].update(
            text="東京", answer_start=0
        )
        other = corpus(obj)
        self.assertEqual(
            chosen, sample_families(other.queries, {q.family for q in other.queries}, 2)
        )
        self.assertEqual(
            digest([d.content for d in c.documents.values()]),
            digest([d.content for d in other.documents.values()]),
        )


if __name__ == "__main__":
    unittest.main()
