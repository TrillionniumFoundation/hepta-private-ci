"""Actual Torch loss gradients and source-fact pairing; NOT pretrained gains."""

import copy
import json
import unittest

import torch

from source_binding_margin import binding_margin_loss, source_hard_negatives
from test_source_completion_loss import CausalFixture
from test_source_composition_curriculum import event


class SourceTokenizer:
    eos_token_id = 1

    def encode(self, text, add_special_tokens=False):
        if add_special_tokens or not isinstance(text, str):
            raise ValueError("source-only tokenization")
        return [ord(char) for char in text]


def sources():
    return (
        event("a0", "service", "location", "mode_11112222"),
        event("a1", "service", "version", "mode_33334444"),
        event("a2", "other", "location", "mode_55556666"),
        event("b0", "service", "location", "mode_77778888", scope="private"),
        event("b1", "other", "location", "mode_99990000", scope="private"),
    )


def examples():
    return [
        dict(
            query=dict(identity="q" + x.identity, scope=x.scope),
            sources=[x.identity],
            target=json.loads(x.content)["value"],
        )
        for x in sources()
    ]


class SourceBindingTests(unittest.TestCase):
    def test_source_only_pairs_prefer_same_entity_different_relation(self):
        docs = sources()
        pair, missing = source_hard_negatives(
            examples(),
            docs,
            SourceTokenizer(),
            allowed_roots={x.root for x in docs},
            revoked=set(),
        )
        self.assertEqual(missing, ())
        self.assertEqual(pair[0]["negative_value"], "mode_33334444")
        self.assertEqual(pair[0]["negative_category"], "same_entity_different_relation")
        self.assertEqual(pair[2]["negative_category"], "same_relation_different_entity")
        self.assertEqual(pair[3]["negative_value"], "mode_99990000")
        self.assertEqual(
            source_hard_negatives(
                list(reversed(examples())),
                tuple(reversed(docs)),
                SourceTokenizer(),
                allowed_roots={x.root for x in docs},
                revoked=set(),
            )[1],
            (),
        )

    def test_verified_superseded_value_precedes_other_hard_negatives(self):
        from experience_memory import source_examples

        docs = (
            event("old", "service", "location", "mode_11112222", 1, scope="s"),
            event(
                "new",
                "service",
                "location",
                "mode_33334444",
                2,
                ("old",),
                scope="s",
            ),
            event("noise", "other", "location", "mode_55556666", 1, scope="s"),
            event(
                "future",
                "service",
                "location",
                "mode_77778888",
                3,
                ("new",),
                scope="s",
            ),
        )
        examples, _ = source_examples(
            docs,
            revision=2,
            allowed_roots={d.root for d in docs},
            revoked=set(),
        )
        current = next(i for i, x in enumerate(examples) if x["sources"] == ["new"])
        chosen, _ = source_hard_negatives(
            list(examples),
            docs,
            SourceTokenizer(),
            allowed_roots={d.root for d in docs},
            revoked=set(),
        )
        item = chosen[current]
        self.assertEqual(item["negative_category"], "same_entity_relation_superseded")
        self.assertEqual(item["negative_value"], "mode_11112222")
        self.assertEqual(item["negative_roots"], ("root_old",))
        self.assertEqual(item["positive_roots"], ("root_new",))
        self.assertNotEqual(item["negative_value"], "mode_77778888")

    def test_multihop_correction_prefers_nearest_stale_revision(self):
        from experience_memory import source_examples

        docs = (
            event("aold", "service", "location", "mode_11112222", 1, scope="s"),
            event(
                "zmiddle",
                "service",
                "location",
                "mode_33334444",
                2,
                ("aold",),
                scope="s",
            ),
            event(
                "new",
                "service",
                "location",
                "mode_55556666",
                3,
                ("zmiddle",),
                scope="s",
            ),
        )
        cases, _ = source_examples(
            docs,
            revision=3,
            allowed_roots={d.root for d in docs},
            revoked=set(),
        )
        chosen, unmatched = source_hard_negatives(
            list(cases),
            docs,
            SourceTokenizer(),
            allowed_roots={d.root for d in docs},
            revoked=set(),
        )
        self.assertEqual(unmatched, ())
        self.assertEqual(
            chosen[0]["negative_category"], "same_entity_relation_superseded"
        )
        self.assertEqual(chosen[0]["negative_value"], "mode_33334444")
        self.assertEqual(chosen[0]["negative_roots"], ("root_zmiddle",))

    def test_unlinked_newer_event_is_not_a_stale_negative(self):
        from experience_memory import source_examples

        docs = (
            event("old", "service", "location", "mode_11112222", 1, scope="s"),
            event("unlinked", "service", "location", "mode_33334444", 2, scope="s"),
        )
        with self.assertRaises(ValueError):
            source_examples(
                docs,
                revision=2,
                allowed_roots={d.root for d in docs},
                revoked=set(),
            )
        # Do not rescue the unresolved conflict by assuming latest-wins.
        claims = [
            dict(
                query=dict(identity="qold", scope="s"),
                sources=["old"],
                target="mode_11112222",
            )
        ]
        pairs, missing = source_hard_negatives(
            claims,
            docs,
            SourceTokenizer(),
            allowed_roots={d.root for d in docs},
            revoked=set(),
        )
        self.assertEqual(pairs, {})
        self.assertEqual(missing, ("qold",))

    def test_revoked_cross_scope_and_altered_target_reject(self):
        docs = sources()
        args = dict(
            tokenizer=SourceTokenizer(),
            allowed_roots={x.root for x in docs},
            revoked={"root_a0"},
        )
        with self.assertRaises(ValueError):
            source_hard_negatives(examples(), docs, **args)
        changed = copy.deepcopy(examples())
        changed[0]["target"] = "mode_deadbeef"
        with self.assertRaises(ValueError):
            source_hard_negatives(
                changed,
                docs,
                SourceTokenizer(),
                allowed_roots={x.root for x in docs},
                revoked=set(),
            )
        changed = copy.deepcopy(examples())
        changed[3]["query"]["scope"] = "a"
        with self.assertRaises(ValueError):
            source_hard_negatives(
                changed,
                docs,
                SourceTokenizer(),
                allowed_roots={x.root for x in docs},
                revoked=set(),
            )

    def test_zero_available_negatives_do_not_turn_into_synthetic_null(self):
        docs = sources()
        one = examples()[:1]
        pair, missing = source_hard_negatives(
            one,
            docs,
            SourceTokenizer(),
            allowed_roots={x.root for x in docs},
            revoked=set(),
        )
        self.assertEqual(pair, {})
        self.assertEqual(missing, ("qa0",))

    def test_actual_two_forward_margin_loss_and_gradients(self):
        tokenizer = SourceTokenizer()
        model = CausalFixture(vocab=257, width=32)
        prompt = [7, 11, 13, 17]
        loss, receipt = binding_margin_loss(
            model, tokenizer, prompt, "A", "B", backend="supervised_positions"
        )
        self.assertEqual(model.calls, 2)
        self.assertEqual(receipt["actual_input_tokens"], 12)
        self.assertEqual(receipt["actual_supervised_tokens"], 4)
        self.assertEqual(receipt["actual_projection_positions"], 4)
        self.assertFalse(receipt["production_accepted"])
        loss.backward()
        self.assertTrue(
            any(
                p.grad is not None and p.grad.abs().sum().item() > 0
                for p in model.parameters()
                if p.requires_grad
            )
        )
        self.assertTrue(torch.isfinite(loss))
        model_b = CausalFixture(vocab=257, width=32)
        loss_b, _ = binding_margin_loss(
            model_b, tokenizer, prompt, "A", "C", backend="supervised_positions"
        )
        loss_b.backward()
        grads = [
            (a.grad - b.grad).abs().sum().item()
            for a, b in zip(
                (p for p in model.parameters() if p.requires_grad),
                (p for p in model_b.parameters() if p.requires_grad),
            )
        ]
        self.assertGreater(sum(grads), 0)

    def test_invalid_pair_fails_before_forward(self):
        model = CausalFixture(vocab=257, width=32)
        for target, negative, prompt in (
            ("A", "A", [2]),
            ("AA", "B", [2]),
            ("", "A", [2]),
            ("A", "B", []),
            ("A", "B", [True]),
        ):
            with (
                self.subTest(target=target, negative=negative),
                self.assertRaises(ValueError),
            ):
                binding_margin_loss(
                    model,
                    SourceTokenizer(),
                    prompt,
                    target,
                    negative,
                    backend="supervised_positions",
                )
        self.assertEqual(model.calls, 0)


if __name__ == "__main__":
    unittest.main()
