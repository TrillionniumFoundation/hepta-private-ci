"""Tensor tests with an explicit tiny fixture, never pretrained model evidence."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
import types
import unittest
from unittest.mock import patch

import torch
import torch._dynamo

from evidence_preference import fit_preference, preference_loss
from native import Question
from selector_answering import ABSTAIN
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
    source = dict(
        root="root",
        scope="scope",
        label="E1",
        excerpt="Kyoto",
        source_start=0,
        source_end=5,
    )
    positive = Example(q, q.family, "root", (source,), "Kyoto [E1]", "annotation")
    null = replace(positive, question=replace(q, identity="null"), completion=ABSTAIN)
    cut = TrainingCut(
        frozenset({"q", "null"}),
        frozenset({"family"}),
        frozenset({"root"}),
        frozenset(),
        "test-admission",
    )
    return (positive, null), cut


class Tokenizer:
    eos_token_id = 256

    def encode(self, text, **_):
        return list(text.encode())


class Model(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.zeros(2))
        self.enabled = True
        self.seen = []

    @contextmanager
    def disable_adapter(self):
        self.enabled = False
        try:
            yield
        finally:
            self.enabled = True

    def forward(self, input_ids, labels, **_):
        self.seen.append(
            (input_ids.tolist(), labels.tolist(), self.enabled, torch.is_grad_enabled())
        )
        support = 1.0 if input_ids[0, 1] == 2 else -1.0
        sign = -1.0 if labels[labels != -100][0] == ord("I") else 1.0
        score = self.weight[0] + support * self.weight[1]
        if not self.enabled:
            score = score.detach() * 0
        return types.SimpleNamespace(loss=torch.nn.functional.softplus(-sign * score))


def reader():
    return types.SimpleNamespace(
        model=Model(),
        tokenizer=Tokenizer(),
        scope="development",
        roots={"prior"},
        quarantined=False,
        base_digest="base",
        trainable_parameters=2,
    )


def train(r, rows, cut, **kwargs):
    modules = {
        "peft": types.SimpleNamespace(
            get_peft_model_state_dict=lambda m: {"weight": m.weight.detach().clone()}
        ),
        "pretrained": types.SimpleNamespace(frozen_digest=lambda _: "base"),
        "task_answer_learning": types.SimpleNamespace(
            prompt_ids=lambda t, q, s, **_: [1, 2 if s and q.identity == "q" else 3]
        ),
    }
    with patch.dict("sys.modules", modules):
        return fit_preference(r, rows, cut, revoked=set(), **kwargs)


class EvidencePreferenceTests(unittest.TestCase):
    def test_global_answer_or_refusal_bias_does_not_improve_paired_preference(self):
        reference = torch.ones(4)
        base = float(preference_loss(torch.ones(5), reference))
        for shift in (-0.5, 0.5):
            values = torch.tensor([1 - shift, 1.0, 1 - shift, 1.0, 1.0])
            self.assertGreater(float(preference_loss(values, reference)), base)
        conditioned = torch.tensor([0.5, 1.0, 1.0, 0.5, 1.0])
        self.assertLess(float(preference_loss(conditioned, reference)), base)

    def test_gradient_prefers_answer_with_evidence_and_refusal_without_it(self):
        values = torch.ones(5, requires_grad=True)
        preference_loss(values, torch.ones(4)).backward()
        self.assertGreater(float(values.grad[0]), 0)
        self.assertLess(float(values.grad[1]), 0)
        self.assertLess(float(values.grad[2]), 0)
        self.assertGreater(float(values.grad[3]), 0)
        self.assertEqual(float(values.grad[4]), 0)
        with self.assertRaises(ValueError):
            preference_loss(values, torch.ones(4, requires_grad=True))

    def test_real_updates_charge_detached_reference_and_all_actor_work(self):
        rows, cut = fixture()
        r = reader()
        receipt = train(r, rows, cut, updates=3)
        self.assertEqual(receipt["steps"], 3)
        self.assertEqual(receipt["reference_forwards"], 4)
        self.assertEqual(receipt["actor_forwards"], 15)
        self.assertEqual(len(r.model.seen), 19)
        self.assertEqual(
            receipt["tokens"], sum(len(x[0]) for x, _, _, _ in r.model.seen)
        )
        self.assertEqual(r.roots, {"root", "prior"})
        for _, labels, enabled, grad in r.model.seen:
            self.assertEqual(labels[0][:2], [-100, -100])
            self.assertEqual(labels[0][-1], 256)
            self.assertEqual(enabled, grad)
        self.assertGreater(receipt["adapter_delta_squared_norm"], 0)
        self.assertTrue(
            all(
                x["question_id"] == x["empty_question_id"]
                for x in receipt["paired_steps"]
            )
        )

    def test_invalid_cut_and_budget_reject_before_reference_forward(self):
        rows, cut = fixture()
        for bad in (
            replace(cut, forbidden_roots=frozenset({"prior"})),
            replace(cut, question_ids=frozenset()),
        ):
            r = reader()
            with self.assertRaises(ValueError):
                train(r, rows, bad, updates=1)
            self.assertEqual(r.model.seen, [])
        for options in ({"updates": True}, {"updates": 0}, {"token_ceiling": True}):
            r = reader()
            with self.assertRaises(ValueError):
                train(r, rows, cut, **options)
            self.assertEqual(r.model.seen, [])

    def test_budget_stops_before_partial_reference_actor_step(self):
        rows, cut = fixture()
        r = reader()
        receipt = train(r, rows, cut, updates=64, token_ceiling=1120)
        self.assertLess(receipt["steps"], 64)
        self.assertLessEqual(receipt["tokens"], 1120)
        self.assertEqual(receipt["actor_forwards"], 5 * receipt["steps"])

    def test_reference_failure_quarantines_candidate(self):
        rows, cut = fixture()
        r = reader()
        with patch.object(r.model, "forward", side_effect=ValueError("failed")):
            with self.assertRaises(ValueError):
                train(r, rows, cut, updates=1)
        self.assertTrue(r.quarantined)
        self.assertIsNone(r.scope)
        self.assertTrue(r.model.enabled)

    def test_nan_and_wrong_reference_shape_reject(self):
        for reference in (torch.ones(3), torch.tensor([1.0, 1.0, 1.0, float("nan")])):
            with self.assertRaises(ValueError):
                preference_loss(torch.ones(5), reference)


if __name__ == "__main__":
    unittest.main()
