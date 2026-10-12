"""Development fixtures, never independent pretrained knowledge evidence."""

from dataclasses import replace
import json
import unittest

import torch

from event_projection import PROFILE
from experience_memory import source_examples
from native import Document
from source_relation_margin import relation_loss, schedule_cost, source_negatives
from source_write_schedule import prepare
from test_source_completion_loss import CausalFixture


class Tokens:
    eos_token_id = 1

    def apply_chat_template(self, messages, **kwargs):
        return [3, 4, 5, 6]

    def encode(self, text, *, add_special_tokens=False):
        return [ord(c) + 3 for c in text]


def fact(identity, entity, attribute, value, scope="alpha"):
    obj = dict(
        schema=PROFILE,
        id=identity,
        entity=entity,
        attribute=attribute,
        value=value,
        revision=2,
        supersedes=[],
    )
    return Document(
        identity,
        "root_" + identity,
        scope,
        scope,
        "2026-10-10T00:00:00+00:00",
        json.dumps(obj),
    )


def sample():
    return (
        fact("one", "service_a", "location", "site_aaaa1111"),
        fact("two", "service_b", "location", "site_bbbb2222"),
        fact("three", "service_a", "owner", "site_cccc3333"),
        fact("four", "service_x", "location", "site_dddd4444", "beta"),
    )


def prepared(rows):
    examples, _ = source_examples(
        rows,
        revision=2,
        allowed_roots={r.root for r in rows},
        revoked=set(),
    )
    tasks, plan = prepare(Tokens(), examples, maximum_steps=12, token_ceiling=65536)
    negatives, review = source_negatives(rows, examples, tasks, Tokens())
    return examples, tasks, plan, negatives, review


class RelationLossTests(unittest.TestCase):
    def test_hard_negatives_are_original_equal_length_facts(self):
        examples, pos, schedule, negative, review = prepared(sample())
        self.assertEqual(len(examples), 4)
        self.assertEqual(review["eligible_source_questions"], 4)
        self.assertEqual(review["unavailable_source_questions"], 0)
        self.assertGreaterEqual(
            review["categories"]["same_scope_same_attribute_other_entity"], 2
        )
        for a, b in zip(pos, negative, strict=True):
            self.assertIsNotNone(b)
            self.assertEqual(a[0][:4], b[0][:4])
            self.assertEqual(len(a[0]), len(b[0]))
            self.assertNotEqual(a[1][4:], b[1][4:])
        charged = schedule_cost(pos, schedule, negative)
        self.assertEqual(
            charged["all_model_forward_input_tokens"],
            charged["additional_distractor_input_tokens"]
            + schedule["planned_input_tokens"],
        )
        self.assertFalse(review["downstream_question_or_answer_inputs_used"])

    def test_absent_alternatives_are_unknown(self):
        _, pos, plan, negative, review = prepared(sample()[:1])
        self.assertEqual(negative, (None,))
        self.assertEqual(review["eligible_source_questions"], 0)
        with self.assertRaisesRegex(ValueError, "unbound or unvisited"):
            schedule_cost(pos, plan, negative)

    def test_short_wrong_completion_is_not_automatically_negative(self):
        rows = (
            fact("a", "a", "location", "x"),
            fact("b", "b", "location", "different"),
        )
        self.assertEqual(prepared(rows)[3], (None, None))

    def test_corrupted_source_target_and_scope_reject(self):
        examples, pos, _, _, _ = prepared(sample())
        changed = list(examples)
        changed[0] = changed[0] | {"target": "site_ffff0000"}
        with self.assertRaises(ValueError):
            source_negatives(sample(), changed, pos, Tokens())
        docs = list(sample())
        docs[0] = replace(docs[0], scope="forbidden")
        with self.assertRaises(ValueError):
            source_negatives(docs, examples, pos, Tokens())

    def test_real_autograd_improves_source_relation_margin(self):
        _, tasks, _, negative, _ = prepared(sample())
        model = CausalFixture(vocab=257)
        from source_completion_loss import completion_loss

        def margin():
            p, _ = completion_loss(model, *tasks[0], backend="supervised_positions")
            n, _ = completion_loss(model, *negative[0], backend="supervised_positions")
            return float((n - p).detach())

        before = margin()
        opt = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad], lr=0.02
        )
        for _ in range(20):
            opt.zero_grad(set_to_none=True)
            loss, receipt = relation_loss(model, tasks[0], negative[0])
            loss.backward()
            opt.step()
        self.assertTrue(torch.isfinite(loss))
        self.assertGreater(margin(), before)
        self.assertEqual(receipt["input_tokens"], len(tasks[0][0]) * 2)
        self.assertTrue(receipt["pair_used"])

    def test_bad_pair_fails_before_any_model_forward(self):
        _, tasks, _, negatives, _ = prepared(sample())
        model = CausalFixture(vocab=257)
        wrong = ([99] + negatives[0][0][1:], negatives[0][1])
        with self.assertRaises(ValueError):
            relation_loss(model, tasks[0], wrong)
        self.assertEqual(model.calls, 0)

    def test_optimizer_budget_cannot_hide_negative_forward(self):
        _, tasks, plan, negative, _ = prepared(sample())
        with self.assertRaisesRegex(ValueError, "forward token ceiling"):
            schedule_cost(tasks, plan, negative, ceiling=plan["planned_input_tokens"])
        with self.assertRaises(ValueError):
            schedule_cost(tasks, dict(plan, planned_input_tokens=0), negative)


if __name__ == "__main__":
    unittest.main()
