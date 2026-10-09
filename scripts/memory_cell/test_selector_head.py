"""Real gradient, fixed-candidate, cut and immutable-head regression tests."""

from dataclasses import replace
import json
import unittest

import torch

from native import Document, Question, Target, digest
from selector_evaluation import HARD_KINDS, calibration, train_rows
from selector_head import EvidenceHead, Features, Supervision, TrainingCut
from selector_windows import candidate_windows


class SelectorHeadTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.head = EvidenceHead(8, "encoder")
        generator = torch.Generator().manual_seed(113)
        self.rows = []
        for j in range(12):
            x = torch.randn(4, 8, generator=generator) * 0.1
            x[:, 0] = -1
            positive = () if j % 3 == 0 else (j % 4,)
            if positive:
                x[positive[0], 0] = 1
            f = Features(f"q{j}", f"f{j % 3}", "encoder", f"pool{j}",
                         tuple(f"w{i}" for i in range(4)), frozenset({f"r{j}"}), x, torch.zeros(4))
            self.rows.append(Supervision(f, positive))
        self.rows = tuple(self.rows)
        self.cut = TrainingCut(frozenset(r.features.question_id for r in self.rows),
                               frozenset(r.features.family for r in self.rows),
                               frozenset().union(*(r.features.roots for r in self.rows)),
                               frozenset({"test-root"}), "admission")

    def loss(self):
        values = []
        for row in self.rows:
            scores = self.head(row.features)
            pos = list(row.positive_indices) or [len(scores) - 1]
            values.append(torch.logsumexp(scores, 0) - torch.logsumexp(scores[pos], 0))
        return float(torch.stack(values).mean().detach())

    def test_initial_head_is_frozen_control_then_real_loss_falls(self):
        for r in self.rows:
            self.assertEqual(self.head.decide(r.features, revoked=set()),
                             self.head.decide(r.features, revoked=set(), mode="frozen"))
        before, original = self.loss(), [r.features.paired.clone() for r in self.rows]
        receipt = self.head.fit(self.rows, self.cut, revoked=set(), steps=192)
        self.assertLess(self.loss(), before)
        self.assertGreater(receipt["delta_squared_norm"], 0)
        self.assertEqual(receipt["encoder_updates"], 0)
        self.assertTrue(all(torch.equal(a, r.features.paired) for a, r in zip(original, self.rows)))
        self.assertTrue(any(self.head.decide(r.features, revoked=set())[0] is None for r in self.rows))

    def test_every_training_row_validated_before_any_update(self):
        original = {k: v.clone() for k, v in self.head.state_dict().items()}
        bad = replace(self.rows[-1], features=replace(self.rows[-1].features, family="held-out"))
        with self.assertRaises(ValueError):
            self.head.fit(self.rows[:-1] + (bad,), self.cut, revoked=set())
        self.assertTrue(all(torch.equal(original[k], v) for k, v in self.head.state_dict().items()))
        with self.assertRaises(ValueError):
            self.head.fit(self.rows, self.cut, revoked={"r0"})
        with self.assertRaises(ValueError):
            self.head.fit(self.rows + (self.rows[0],), self.cut, revoked=set())

    def test_restore_has_no_corpus_is_exact_and_obeys_ancestor_withdrawal(self):
        self.head.fit(self.rows, self.cut, revoked=set(), steps=32)
        payload = self.head.export()
        digest_value = digest(payload.hex())
        restored = EvidenceHead.restore(payload, expected_digest=digest_value,
            encoder_identity="encoder", allowed_roots=set(self.cut.allowed_roots), revoked=set())
        for r in self.rows:
            self.assertEqual(self.head.decide(r.features, revoked=set()), restored.decide(r.features, revoked=set()))
        self.assertNotIn(b'"paired"', payload)
        for roots, encoder, revoked in ((set(), "encoder", set()), (set(self.cut.allowed_roots), "other", set()),
                                         (set(self.cut.allowed_roots), "encoder", {"r0"})):
            with self.assertRaises(ValueError):
                EvidenceHead.restore(payload, expected_digest=digest_value, encoder_identity=encoder,
                                     allowed_roots=roots, revoked=revoked)
        with self.assertRaises(ValueError):
            restored.decide(self.rows[-1].features, revoked={"r0"})
        obj = json.loads(payload)
        obj["state"]["null.bias"] = [float("nan")]
        corrupted = json.dumps(obj).encode()
        with self.assertRaises(ValueError):
            EvidenceHead.restore(corrupted, expected_digest=digest(corrupted.hex()),
                encoder_identity="encoder", allowed_roots=set(self.cut.allowed_roots), revoked=set())

    def test_nonfinite_encoder_features_and_empty_candidates(self):
        bad = replace(self.rows[0].features, paired=torch.full((4, 8), float("nan")))
        with self.assertRaises(ValueError):
            self.head.decide(bad, revoked=set())
        empty = replace(self.rows[0].features, candidate_ids=(), paired=torch.empty(0, 8), frozen_scores=torch.empty(0))
        self.assertIsNone(self.head.decide(empty, revoked=set())[0])

    def test_order_does_not_change_decision_identity(self):
        batch = self.rows[1].features
        indices = torch.tensor([3, 0, 2, 1])
        other = replace(batch, paired=batch.paired[indices], frozen_scores=batch.frozen_scores[indices],
                        candidate_ids=tuple(batch.candidate_ids[i] for i in indices))
        for mode in ("frozen", "forced", "learned"):
            a, _ = self.head.decide(batch, revoked=set(), offset=-1.0, mode=mode)
            b, _ = self.head.decide(other, revoked=set(), offset=-1.0, mode=mode)
            self.assertEqual(batch.candidate_ids[a], other.candidate_ids[b])


class SelectorLabelTests(unittest.TestCase):
    def setUp(self):
        self.q = Question("train", "family", "scope", "Where did Mara live in 2024?", "2024")
        self.docs = (Document("good", "r", "scope", "s", "2024", "Mara lived in Kyoto in 2024."),
                     Document("old", "r", "scope", "s", "2020", "Mara lived in Osaka in 2020."),
                     Document("relation", "r", "scope", "s", "2024", "Mara worked in Tokyo in 2024."),
                     Document("superseded", "r", "scope", "s", "2023", "Mara had moved to Nara before the correction."),
                     Document("nearby", "r", "scope", "s", "2024", "Mara enjoys reading and cooking."))
        self.pool = candidate_windows(self.docs, self.q, revoked=set())
        n = len(self.pool.windows)
        self.features = Features("train", "family", "encoder", self.pool.seal(),
            tuple(w.identity() for w in self.pool.windows), frozenset({"r"}), torch.zeros(n, 8), torch.zeros(n))
        self.cut = TrainingCut(frozenset({"train"}), frozenset({"family"}), frozenset({"r"}), frozenset(), "cut")
        self.target = Target("Kyoto", "single", ("good",), False)

    def make(self, target=None, reviewed=None):
        return train_rows([self.q], {"train": target or self.target}, {"train": self.pool},
                          {"train": self.features}, self.cut, reviewed_negatives=reviewed)

    def test_four_explicit_reviewed_hard_negative_categories(self):
        # These semantic labels are authored fixtures, not falsely claimed model reviews.
        labels = dict(old="same_person_different_time", relation="same_entity_different_relation",
                      superseded="superseded_fact", nearby="nearby_irrelevant")
        reviewed = {"train": {w.identity(): labels[w.source_id] for w in self.pool.windows if w.source_id != "good"}}
        rows, note = self.make(reviewed=reviewed)
        self.assertEqual(set(rows[0].negative_kinds), HARD_KINDS)
        self.assertEqual(set(note["reviewed_negative_counts"]), HARD_KINDS)
        wrong = {"train": {next(w.identity() for w in self.pool.windows if w.source_id == "good"): "nearby_irrelevant"}}
        with self.assertRaises(ValueError):
            self.make(reviewed=wrong)

    def test_missing_positive_is_not_null_and_answer_text_not_training_signal(self):
        rows, _ = self.make()
        poisoned, _ = self.make(replace(self.target, answer="poisoned evaluation answer"))
        self.assertEqual(rows[0].positive_indices, poisoned[0].positive_indices)
        self.assertEqual(rows[0].features.seal(), poisoned[0].features.seal())
        missing, note = self.make(replace(self.target, evidence=("not_retrieved",)))
        self.assertEqual(missing, ())
        self.assertEqual(len(note["skipped_training"]), 1)
        unanswerable, _ = self.make(replace(self.target, unanswerable=True, evidence=()))
        self.assertEqual(unanswerable[0].positive_indices, ())

    def test_test_annotations_are_never_read_for_training_or_calibration(self):
        class Forbidden(dict):
            def __getitem__(self, key):
                raise AssertionError("held-out answer was read")
        with self.assertRaises(ValueError):
            train_rows([replace(self.q, identity="test")], Forbidden(), {}, {}, self.cut)
        head = EvidenceHead(8, "encoder")
        with self.assertRaises(ValueError):
            calibration(head, [(self.q, "family", self.pool, self.features)], Forbidden(), mode="frozen",
                        permitted_questions={"other"}, permitted_families={"family"})


if __name__ == "__main__":
    unittest.main()
