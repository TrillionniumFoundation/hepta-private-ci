"""Source schedule equivalence, not pretrained model quality evidence."""

from copy import deepcopy
import unittest

from source_write_schedule import prepare, schedule
from test_experience_memory import project, source


def example(size):
    return list(range(size)), [-100] * (size - 1) + [size - 1]


class ScheduleTests(unittest.TestCase):
    def test_same_order_and_token_stop_as_existing_writer(self):
        prepared = [example(n) for n in (5, 7, 11, 13, 17)]
        groups = {"scope_z": [0, 1, 2], "scope_a": [3, 4]}
        for ceiling in (1, 13, 14, 25, 64, 1024, 65536):
            for maximum in (1, 9, 128):
                old, tokens = [], 0
                scopes = sorted(groups)
                for step in range(maximum):
                    group = groups[scopes[step % len(scopes)]]
                    index = group[(step // len(scopes)) % len(group)]
                    if tokens + len(prepared[index][0]) > ceiling:
                        break
                    old.append(index)
                    tokens += len(prepared[index][0])
                plan = schedule(
                    prepared, groups, maximum_steps=maximum, token_ceiling=ceiling
                )
                self.assertEqual(plan["entries"], old)
                self.assertEqual(plan["planned_input_tokens"], tokens)
                self.assertEqual(sum(plan["visits_per_example"]), len(old))
                self.assertEqual(plan["actual_optimizer_steps"], 0)

    def test_unvisited_facts_and_partial_cycle_are_not_hidden(self):
        prepared = [example(4), example(8), example(6)]
        plan = schedule(
            prepared, {"a": [0, 1], "b": [2]}, maximum_steps=128, token_ceiling=10
        )
        self.assertEqual(plan["entries"], [0, 2])
        self.assertEqual(plan["unvisited_examples"], [1])
        self.assertEqual(plan["stop_reason"], "token_ceiling_before_next_example")
        self.assertEqual(plan["planned_supervised_tokens"], 2)
        self.assertEqual(plan["planned_input_tokens"], 10)

    def test_group_order_does_not_change_predeclared_schedule(self):
        prepared = [example(5), example(6)]
        one = schedule(
            prepared, {"a": [0], "b": [1]}, maximum_steps=10, token_ceiling=100
        )
        two = schedule(
            prepared, {"b": [1], "a": [0]}, maximum_steps=10, token_ceiling=100
        )
        self.assertEqual(one, two)

    def test_missing_duplicate_and_cross_group_examples_reject(self):
        for groups in (
            {"a": [0]},
            {"a": [0, 0, 1]},
            {"a": [0], "b": [0, 1]},
            {"a": [True, 0]},
            {"a": []},
        ):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                schedule(
                    [example(4), example(5)],
                    groups,
                    maximum_steps=10,
                    token_ceiling=100,
                )

    def test_invalid_label_alignment_and_all_masked_rows_reject(self):
        for row in (
            ([1, 2], [-100]),
            ([1, 2], [-100, 3]),
            ([1, 2], [-100, -100]),
            ([True], [True]),
        ):
            with self.subTest(row=row), self.assertRaises(ValueError):
                schedule([row], {"a": [0]}, maximum_steps=10, token_ceiling=100)

    def test_bool_negative_and_oversized_budgets_are_not_valid(self):
        for steps, ceiling in (
            (True, 100),
            (0, 100),
            (129, 100),
            (1, True),
            (1, -1),
            (1, 65537),
        ):
            with (
                self.subTest(steps=steps, ceiling=ceiling),
                self.assertRaises(ValueError),
            ):
                schedule(
                    [example(4)], {"a": [0]}, maximum_steps=steps, token_ceiling=ceiling
                )

    def test_preparation_uses_source_targets_and_same_empty_prompt(self):
        class Tokenizer:
            eos_token_id = 99

            def __init__(self):
                self.prompts = []

            def apply_chat_template(self, messages, **kwargs):
                self.prompts.append(deepcopy(messages))
                return [1, 2, 3]

            def encode(self, text, **kwargs):
                self.target = text
                return [4, 5]

        examples, _ = project(
            (source("a", "site_old"), source("b", "site_new", 2, ("a",)))
        )
        tokenizer = Tokenizer()
        prepared, plan = prepare(
            tokenizer, examples, maximum_steps=128, token_ceiling=65536
        )
        self.assertEqual(tokenizer.target, "site_new")
        self.assertEqual(
            prepared, [([1, 2, 3, 4, 5, 99], [-100, -100, -100, 4, 5, 99])]
        )
        self.assertEqual(plan["entries"], [0] * 128)
        self.assertNotIn("site_new", tokenizer.prompts[0][1]["content"])


if __name__ == "__main__":
    unittest.main()
