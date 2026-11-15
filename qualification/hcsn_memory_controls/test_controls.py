import copy
import unittest

from qualification.hcsn_memory_controls.generate import (
    TASKS,
    encode,
    make_episode,
    oracle,
)


class SymbolicControlTests(unittest.TestCase):
    def test_query_inputs_do_not_reveal_counterfactual_write_values(self):
        for task in TASKS:
            with self.subTest(task=task):
                episode = make_episode(task, 17, 918, delay_events=32)
                changed = copy.deepcopy(episode["events"])
                for event in changed:
                    if event["kind"] == "write":
                        event["value"] = (event["value"] + 1) % 8
                answers = oracle(changed, task)
                delta = 2 if task == "pair_composition" else 1
                for position in episode["query_positions"]:
                    self.assertEqual(encode(changed[position]), episode["x"][position])
                    self.assertEqual(
                        answers[position], (episode["y"][position] + delta) % 8
                    )

    def test_time_changes_do_not_change_symbolic_answer(self):
        for task in TASKS:
            left, right = make_episode(task, 17, 918), make_episode(task, 17, 919)
            self.assertEqual(left["y"], right["y"])
            self.assertNotEqual(left["dt"], right["dt"])
            self.assertEqual([x[:-1] for x in left["x"]], [x[:-1] for x in right["x"]])

    def test_overwrite_copy_and_composition_against_manual_cases(self):
        def event(kind, keys=(), value=None):
            return dict(kind=kind, keys=list(keys), value=value, dt=0.01)

        association = [
            event("write", [0], 1),
            event("write", [1], 2),
            event("write", [0], 5),
            event("distractor", [0], 7),
            event("query", [0]),
        ]
        self.assertEqual(
            oracle(association, "overwrite_retrieval"), [-1, -1, -1, -1, 5]
        )
        association[-1] = event("query", [0, 1])
        self.assertEqual(oracle(association, "pair_composition")[-1], 7)
        copying = [
            event("write", value=3),
            event("write", value=1),
            event("distractor", value=7),
            event("copy_read"),
            event("copy_read"),
        ]
        self.assertEqual(oracle(copying, "delayed_copy"), [-1, -1, -1, 3, 1])
        with self.assertRaises(KeyError):
            oracle([event("query", [0])], "overwrite_retrieval")
