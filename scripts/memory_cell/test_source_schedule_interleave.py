"""Source-only curriculum interleave: exposure, not a learned task gain."""

from copy import deepcopy
import unittest

from native import digest
from source_write_coverage import TWO_HOP, audit_coverage
from source_write_schedule import (
    interleave_source_kinds,
    prepare,
)


class Tokenizer:
    eos_token_id = 99

    def apply_chat_template(self, messages, **kwargs):
        return [1, 2, 3]

    def encode(self, text, **kwargs):
        return [10]


def examples_for(scope="scope-a", *, hops=6, direct=2):
    return tuple(
        dict(
            query=dict(
                identity=f"{scope}-{index}",
                family="source-only",
                scope=scope,
                content=f"At revision 2, what is the recorded relation {index}?",
                observed_at="2026-10-13T00:00:00+00:00",
            ),
            target=f"site_{index:08x}",
            sources=[f"original-{index}"],
            source_digest=digest((scope, index)),
            **({"curriculum": TWO_HOP} if index < hops else {}),
        )
        for index in range(hops + direct)
    )


class InterleavedWriteTests(unittest.TestCase):
    def test_identical_training_examples_budget_and_more_direct_exposure(self):
        examples = examples_for()
        tokenizer = Tokenizer()
        original, before = prepare(
            tokenizer, examples, maximum_steps=4, token_ceiling=20
        )
        updated, after = prepare(
            tokenizer,
            examples,
            maximum_steps=4,
            token_ceiling=20,
            strategy="direct_interleave",
        )
        self.assertEqual(original, updated)
        self.assertEqual(before["entries"], [0, 1, 2, 3])
        self.assertEqual(after["entries"], [6, 0, 7, 1])
        self.assertEqual(before["planned_steps"], after["planned_steps"])
        self.assertEqual(before["planned_input_tokens"], after["planned_input_tokens"])
        self.assertEqual(
            before["planned_supervised_tokens"], after["planned_supervised_tokens"]
        )
        self.assertEqual(after["original_groups_digest"], before["groups_digest"])
        old_coverage = audit_coverage(
            examples, original, before, curriculum="source_two_hop"
        )
        new_coverage = audit_coverage(
            examples, updated, after, curriculum="source_two_hop"
        )
        self.assertEqual(old_coverage["by_kind"]["direct"]["planned_updates"], 0)
        self.assertEqual(new_coverage["by_kind"]["direct"]["planned_updates"], 2)
        self.assertEqual(new_coverage["by_kind"]["two_hop"]["planned_updates"], 2)
        self.assertEqual(new_coverage["planned_optimizer_updates"], 4)
        self.assertFalse(new_coverage["production_accepted"])

    def test_two_scopes_stratify_without_redistributing_source_ids(self):
        cases = examples_for("scope-a", hops=2, direct=1) + examples_for(
            "scope-b", hops=2, direct=1
        )
        prepared, plan = prepare(
            Tokenizer(),
            cases,
            maximum_steps=4,
            token_ceiling=20,
            strategy="direct_interleave",
        )
        self.assertEqual(plan["entries"], [2, 5, 0, 3])
        self.assertEqual(set(plan["entries"]), {0, 2, 3, 5})
        self.assertEqual(plan["source_only_order_intervention"], True)
        self.assertEqual(
            audit_coverage(cases, prepared, plan, curriculum="source_two_hop")[
                "by_kind"
            ]["direct"]["source_scopes_with_exposure"],
            2,
        )

    def test_legacy_default_is_byte_equivalent(self):
        cases = examples_for()
        original = prepare(Tokenizer(), cases, maximum_steps=4, token_ceiling=20)
        explicit = prepare(
            Tokenizer(),
            cases,
            maximum_steps=4,
            token_ceiling=20,
            strategy="original",
        )
        self.assertEqual(original, explicit)
        self.assertNotIn("strategy", original[1])
        self.assertNotIn("original_groups_digest", original[1])

    def test_fail_closed_on_unrelated_curriculum_or_wrong_scope(self):
        with self.assertRaises(ValueError):
            prepare(
                Tokenizer(),
                examples_for(hops=0, direct=4),
                maximum_steps=4,
                token_ceiling=20,
                strategy="direct_interleave",
            )
        with self.assertRaises(ValueError):
            prepare(
                Tokenizer(),
                examples_for(),
                maximum_steps=4,
                token_ceiling=20,
                strategy="unknown",
            )
        rows = list(examples_for())
        rows[1] = dict(rows[1], curriculum="publisher_gold")
        with self.assertRaises(ValueError):
            prepare(
                Tokenizer(),
                rows,
                maximum_steps=4,
                token_ceiling=20,
                strategy="direct_interleave",
            )
        with self.assertRaises(ValueError):
            interleave_source_kinds(
                examples_for(), {"scope-a": [0, 1], "other": [2, 3, 4, 5, 6, 7]}
            )

    def test_mutated_source_order_pins_cannot_be_laundered(self):
        examples = examples_for()
        prepared, plan = prepare(
            Tokenizer(),
            examples,
            maximum_steps=4,
            token_ceiling=20,
            strategy="direct_interleave",
        )
        for key, value in (
            ("groups_digest", "wrong"),
            ("original_groups_digest", "wrong"),
            ("source_only_order_intervention", False),
            ("strategy", "unauthorized"),
            ("entries", [0, 1, 2, 3]),
        ):
            changed = deepcopy(plan)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_coverage(examples, prepared, changed, curriculum="source_two_hop")
        with self.assertRaises(ValueError):
            audit_coverage(examples, prepared, plan, curriculum="single_hop")


if __name__ == "__main__":
    unittest.main()
