"""Mechanism tests are not independent human annotations or model scores."""

from dataclasses import replace
import unittest
from unittest.mock import patch

import torch

from masked_span_training import (
    EvidenceOnlySpanHead,
    SpanLabels,
    masked_loss,
    masked_rows,
)
from native import digest
from selector_head import EvidenceHead, Features, TrainingCut
from selector_windows import WindowBudget, candidate_windows
from test_span_supervision import corpus


def example():
    feature = Features(
        "q",
        "family",
        "encoder",
        "pool",
        ("a", "b", "c"),
        frozenset(["root"]),
        torch.tensor([[1.0, 0.0], [0.0, 1.0], [2.0, 2.0]]),
        torch.tensor([0.2, -0.1, 4.0]),
    )
    cut = TrainingCut(
        frozenset(["q"]),
        frozenset(["family"]),
        feature.roots,
        frozenset(),
        "fixture-not-production-admission",
    )
    return feature, cut, SpanLabels(feature, (0,), (1,), "annotation")


class MaskedSpanTrainingTests(unittest.TestCase):
    def test_unknown_and_null_logits_have_exactly_zero_gradient(self):
        feature, _, row = example()
        logits = torch.tensor([0.2, -0.1, 100.0, 1000.0], requires_grad=True)
        loss = masked_loss(logits, row)
        loss.backward()
        self.assertEqual(logits.grad[2:].tolist(), [0.0, 0.0])
        other = torch.tensor([0.2, -0.1, -100.0, -1000.0])
        self.assertEqual(float(loss.detach()), float(masked_loss(other, row)))
        with self.assertRaises(ValueError):
            masked_loss(logits, SpanLabels(feature, (), (), "annotation"))

    def test_unknown_feature_changes_do_not_change_trained_parameters(self):
        feature, cut, row = example()
        changed = feature.paired.clone()
        changed[2] = torch.tensor([-100.0, 100.0])
        left, right = (
            EvidenceOnlySpanHead(2, "encoder"),
            EvidenceOnlySpanHead(2, "encoder"),
        )
        left.fit((row,), cut, revoked=set(), steps=8)
        right.fit(
            (replace(row, features=replace(feature, paired=changed)),),
            cut,
            revoked=set(),
            steps=8,
        )
        for name, value in left.state_dict().items():
            self.assertTrue(torch.equal(value, right.state_dict()[name]), name)

    def test_real_update_freezes_null_and_restores_exact_logits(self):
        feature, cut, row = example()
        head = EvidenceOnlySpanHead(2, "encoder")
        before = {k: v.clone() for k, v in head.state_dict().items()}
        result = head.fit((row,), cut, revoked=set(), steps=8)
        self.assertGreater(result["delta_squared_norm"], 0)
        self.assertEqual(result["trainable_parameters"], 65)
        self.assertEqual(result["total_head_parameters"], 68)
        for name in ("null.weight", "null.bias"):
            self.assertTrue(torch.equal(before[name], head.state_dict()[name]))
        encoded = head.export()
        restored = EvidenceHead.restore(
            encoded,
            expected_digest=digest(encoded.hex()),
            encoder_identity="encoder",
            allowed_roots={"root"},
            revoked=set(),
        )
        self.assertTrue(torch.equal(head(feature), restored(feature)))
        with self.assertRaises(ValueError):
            restored.decide(feature, revoked={"root"})

    def test_all_admission_and_label_errors_reject_before_updates(self):
        feature, cut, row = example()
        for wrong in (
            replace(row, positive_indices=(0, 0)),
            replace(row, negative_indices=(0,)),
            replace(row, positive_indices=(True,)),
            replace(row, annotation_digest=""),
            replace(row, features=replace(feature, question_id="test-question")),
            replace(row, features=replace(feature, roots=frozenset(["test-root"]))),
        ):
            head = EvidenceOnlySpanHead(2, "encoder")
            original = {k: v.clone() for k, v in head.state_dict().items()}
            with self.assertRaises(ValueError):
                head.fit((row, wrong), cut, revoked=set(), steps=2)
            self.assertTrue(
                all(torch.equal(v, head.state_dict()[k]) for k, v in original.items())
            )
        with self.assertRaises(ValueError):
            EvidenceOnlySpanHead(2, "encoder").fit((row,), cut, revoked={"root"})

    def test_nonfinite_optimizer_quarantines_and_cannot_export(self):
        _, cut, row = example()
        head = EvidenceOnlySpanHead(2, "encoder")

        def poison(*args, **kwargs):
            with torch.no_grad():
                head.residual.bias.fill_(float("nan"))

        with patch.object(torch.optim.AdamW, "step", poison):
            with self.assertRaises(ValueError):
                head.fit((row,), cut, revoked=set(), steps=1)
        self.assertTrue(head.quarantined)
        with self.assertRaises(ValueError):
            head.export()

    def test_external_answer_spans_keep_other_windows_unknown(self):
        data = corpus()
        pools, features = {}, {}
        for query in data.queries:
            pool = candidate_windows(
                (data.documents[query.scope],),
                query,
                revoked=set(),
                budget=WindowBudget(window_bytes=192, stride_bytes=96),
            )
            pools[query.identity] = pool
            features[query.identity] = Features(
                query.identity,
                query.family,
                "encoder",
                pool.seal(),
                tuple(w.identity() for w in pool.windows),
                frozenset([query.scope]),
                torch.ones(len(pool.windows), 2),
                torch.zeros(len(pool.windows)),
            )
        cut = TrainingCut(
            frozenset(q.identity for q in data.queries),
            frozenset(q.family for q in data.queries),
            frozenset(q.scope for q in data.queries),
            frozenset(),
            "fixture",
        )
        rows, notes = masked_rows(data.queries, data, pools, features, cut)
        self.assertTrue(rows[0].positive_indices)
        self.assertEqual(rows[0].negative_indices, ())
        self.assertTrue(notes[0]["unknown_ids"])
        self.assertEqual(rows[1].positive_indices, ())
        self.assertEqual(
            rows[1].negative_indices,
            tuple(range(len(pools[data.queries[1].identity].windows))),
        )
        self.assertEqual(notes[1]["unknown_ids"], [])

        class Trap(dict):
            def __getitem__(self, key):
                raise AssertionError("unauthorized labels read")

        with self.assertRaises(ValueError):
            masked_rows(
                data.queries,
                replace(data, targets=Trap()),
                {},
                {},
                replace(cut, question_ids=frozenset()),
            )


if __name__ == "__main__":
    unittest.main()
