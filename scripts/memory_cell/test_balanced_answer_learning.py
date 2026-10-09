"""Real tensor/gradient regressions with explicit non-pretrained test fixtures."""

from dataclasses import dataclass, replace
import types
import unittest
from unittest.mock import patch

import torch
import torch._dynamo  # Load optimizer registrations before dependency substitution.

from balanced_answer_learning import (ABSTAIN, admitted_groups, update_examples,
                                     paired_loss, fit_balanced)
from native import Question
from selector_head import TrainingCut


@dataclass(frozen=True)
class Example:
    question: object
    family: str
    root: str
    sources: tuple
    completion: str
    annotation_digest: str


def fixture():
    q = Question("q", "family", "scope", "Where?", "2026")
    source = dict(root="root", scope="scope", label="E1", excerpt="Kyoto",
                  source_start=0, source_end=5)
    positive = Example(q, q.family, "root", (source,), "Kyoto [E1]", "annotation")
    null = replace(positive, question=replace(q, identity="null"), completion=ABSTAIN)
    empty = replace(positive, sources=(), completion=ABSTAIN)
    cut = TrainingCut(frozenset({"q", "null"}), frozenset({"family"}),
                      frozenset({"root"}), frozenset(), "fixture-admission")
    return (positive, null, empty), cut


class Tokenizer:
    eos_token_id = 256

    def encode(self, text, **_):
        return list(text.encode())


class Model(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor(0.0))
        self.seen = []

    def forward(self, input_ids, labels, **_):
        self.seen.append((input_ids.tolist(), labels.tolist()))
        target = labels[labels != -100][0]
        refusal = target == ord("I")
        supported = input_ids[0, 1] == 2
        value = self.weight if refusal and supported else -self.weight
        return types.SimpleNamespace(loss=torch.nn.functional.softplus(value))


def train(reader, rows, cut, **kwargs):
    stubs = {
        "peft": types.SimpleNamespace(get_peft_model_state_dict=lambda m:
            {"weight": m.weight.detach().clone()}),
        "pretrained": types.SimpleNamespace(frozen_digest=lambda _: "frozen"),
        "task_answer_learning": types.SimpleNamespace(prompt_ids=lambda t, q, s,
            **_: [1, 2 if s and q.identity == "q" else 3]),
    }
    with patch.dict("sys.modules", stubs):
        return fit_balanced(reader, rows, cut, revoked=set(), **kwargs)


def reader():
    return types.SimpleNamespace(model=Model(), tokenizer=Tokenizer(),
        scope="development", roots={"prior-root"}, quarantined=False,
        base_digest="frozen", trainable_parameters=1)


class BalancedAnswerTests(unittest.TestCase):
    def test_same_question_counterfactual_and_order_invariant_schedule(self):
        rows, cut = fixture()
        a = admitted_groups(rows, cut, revoked=set())
        b = admitted_groups(tuple(reversed(rows)), cut, revoked=set())
        for step in range(10):
            support, null, empty = update_examples(a, step)
            self.assertEqual(update_examples(a, step), update_examples(b, step))
            self.assertEqual(support.question, empty.question)
            self.assertEqual(empty.sources, ())
            self.assertEqual(null.completion, ABSTAIN)
            self.assertEqual(empty.completion, ABSTAIN)

    def test_duplicate_rows_and_invented_support_cannot_change_sampling_weight(self):
        rows, cut = fixture()
        for bad in (rows + rows[:1], (replace(rows[0], completion="Tokyo [E1]"), *rows[1:]),
                    (replace(rows[0], family="different"), *rows[1:])):
            with self.assertRaises(ValueError):
                admitted_groups(bad, cut, revoked=set())
        with self.assertRaises(ValueError):
            admitted_groups(rows, cut, revoked={"root"})

    def test_missing_class_is_not_silently_renormalized(self):
        rows, cut = fixture()
        with self.assertRaises(ValueError):
            admitted_groups((rows[0], rows[2]), cut, revoked=set())
        with self.assertRaises(ValueError):
            admitted_groups((rows[1], rows[2]), cut, revoked=set())

    def test_contrastive_gradient_prefers_answer_over_refusal_on_same_evidence(self):
        answer = torch.tensor(2.0, requires_grad=True)
        refusal = torch.tensor(1.0, requires_grad=True)
        paired_loss(answer, refusal).backward()
        self.assertGreater(float(answer.grad), 0)
        self.assertLess(float(refusal.grad), 0)

    def test_real_update_charges_all_forwards_and_masks_every_prompt(self):
        rows, cut = fixture()
        model = reader()
        result = train(model, rows, cut, updates=3)
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["forward_passes"], 12)
        self.assertEqual(len(model.model.seen), 12)
        self.assertEqual(result["tokens"], sum(len(x[0]) for x, _ in model.model.seen))
        self.assertEqual(model.roots, {"root", "prior-root"})
        self.assertGreater(result["adapter_delta_squared_norm"], 0)
        for _, labels in model.model.seen:
            self.assertEqual(labels[0][:2], [-100, -100])
            self.assertEqual(labels[0][-1], 256)
        self.assertTrue(all(s["support"] == s["empty"] for s in result["paired_steps"]))
        self.assertFalse(result["production_accepted"])

    def test_withdrawn_ancestor_or_invalid_row_reject_before_update(self):
        rows, cut = fixture()
        model = reader()
        bad = replace(cut, forbidden_roots=frozenset({"prior-root"}))
        with self.assertRaises(ValueError):
            train(model, rows, bad, updates=3)
        self.assertEqual(model.model.seen, [])
        self.assertEqual(float(model.model.weight.detach()), 0)

    def test_failing_forward_quarantines_candidate_without_exporting_partial_result(self):
        rows, cut = fixture()
        model = reader()
        with patch.object(model.model, "forward", side_effect=ValueError("failed")):
            with self.assertRaises(ValueError):
                train(model, rows, cut, updates=2)
        self.assertTrue(model.quarantined)
        self.assertIsNone(model.scope)

    def test_step_and_token_limits_do_not_admit_bool_or_partial_batches(self):
        rows, cut = fixture()
        for kwargs in ({"updates": True}, {"updates": 0}, {"token_ceiling": True}):
            with self.assertRaises(ValueError):
                train(reader(), rows, cut, **kwargs)
        model = reader()
        result = train(model, rows, cut, updates=64, token_ceiling=1120)
        self.assertEqual(len(model.model.seen) % 4, 0)
        self.assertLessEqual(result["tokens"], 1120)
        self.assertLess(result["steps"], 64)


if __name__ == "__main__":
    unittest.main()
