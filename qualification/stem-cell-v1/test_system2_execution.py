import math
import unittest

from system2_execution import (PublicTask, Verification, aggregate_children,
                               discounted_segments, run_reasoning)


class System2ExecutionTests(unittest.TestCase):
    def task(self):
        return PublicTask("Compute the sum of the supplied pair", 10, (("2, 3", 9),))

    def test_real_callback_generation_feedback_and_revision_are_executed(self):
        calls = []
        def propose(task, previous, feedback):
            calls.append((previous, feedback))
            return "4" if previous is None else str(sum(map(int, task.observations[0][0].split(","))))
        def verify(task, candidate):
            expected = sum(map(int, task.observations[0][0].split(",")))
            return Verification(int(candidate) == expected, "Recompute the sum of both inputs")
        report = run_reasoning(self.task(), propose=propose, verify=verify,
                               continue_values=lambda *args: (1., 0.), value_profile="test-linear")
        self.assertEqual(report["candidate"], "5")
        self.assertEqual([e["kind"] for e in report["trace"]], ["propose", "verify", "value", "propose", "verify"])
        self.assertEqual(calls, [(None, None), ("4", "Recompute the sum of both inputs")])
        self.assertEqual(report["calls"], 5)
        self.assertFalse(report["independent_success_established"])
        self.assertFalse(report["general_fbsde_solved"])

    def run_rejecting(self, **overrides):
        args = dict(propose=lambda *args: "candidate", verify=lambda *args: Verification(False, "revise"),
                    continue_values=lambda *args: (1., 0.), value_profile="test-linear")
        args.update(overrides)
        return run_reasoning(self.task(), **args)

    def test_compute_budget_includes_value_callback(self):
        report = self.run_rejecting(max_calls=4)
        self.assertEqual(report["status"], "budget_exhausted")
        self.assertEqual(report["calls"], 2)
        self.assertIsNone(report["measured_flops"])

    def test_negative_continuation_value_stops_without_extra_generation(self):
        report = self.run_rejecting(continue_values=lambda *args: (-1., 0.))
        self.assertEqual(report["status"], "utility_stop")
        self.assertEqual(report["calls"], 3)

    def test_invalid_or_failed_callbacks_are_charged_and_not_retried(self):
        report = self.run_rejecting(propose=lambda *args: None)
        self.assertEqual(report["status"], "callback_failed")
        self.assertEqual(report["calls"], 1)
        self.assertEqual(report["trace"][0]["status"], "failed")
        report = self.run_rejecting(continue_values=lambda *args: (float("nan"), 0.))
        self.assertEqual(report["status"], "callback_failed")
        self.assertEqual(report["calls"], 3)

    def test_depth_and_causal_input_limits(self):
        self.assertEqual(self.run_rejecting(max_rounds=1)["status"], "depth_exhausted")
        with self.assertRaises(ValueError):
            PublicTask("prompt", 10, (("future answer", 11),)).validate()
        with self.assertRaises(TypeError):
            PublicTask(prompt="prompt", as_of_ns=10, final_eval_label="answer")

    def test_backward_segments_preserve_nonzero_continuation(self):
        result = discounted_segments([(1., 1.), (2., 2.)], terminal_value=10., discount_rate=math.log(2))
        self.assertEqual(result, [3.25, 4.5, 10.])
        # Splitting the same zero-reward horizon must preserve terminal discount.
        split = discounted_segments([(0., 1.), (0., 2.)], terminal_value=8., discount_rate=math.log(2))
        whole = discounted_segments([(0., 3.)], terminal_value=8., discount_rate=math.log(2))
        self.assertAlmostEqual(split[0], whole[0])

    def test_chance_is_expectation_not_optimistic_max(self):
        self.assertEqual(aggregate_children([0., 10.], node_kind="chance", probabilities=[.9, .1]), 1.)
        self.assertEqual(aggregate_children([0., 10.], node_kind="choice"), 10.)
        with self.assertRaises(ValueError):
            aggregate_children([0., 10.], node_kind="chance", probabilities=[.9, .9])
        with self.assertRaises(ValueError):
            aggregate_children([0., 10.], node_kind="join")

    def test_and_requires_complete_externally_named_boolean_obligations(self):
        required = ("independent_source", "retained_old_tasks", "authorized_effect")
        complete = [("authorized_effect", True), ("independent_source", True),
                    ("retained_old_tasks", True)]
        self.assertIs(aggregate_children(complete, node_kind="and",
                                         required_ids=required), True)
        incomplete_success = [("authorized_effect", True), ("independent_source", True),
                              ("retained_old_tasks", False)]
        self.assertIs(aggregate_children(incomplete_success, node_kind="and",
                                         required_ids=required), False)

        violations = (
            complete[:2],  # dropped a necessary condition
            [complete[0], complete[0], complete[1]],  # repeated favorable branch
            [complete[0], complete[1], ("unregistered", True)],  # substituted evidence
            [(key, 1) for key, _ in complete],  # integer 1 is not verified Boolean
            [("authorized_effect", 0.999), *complete[1:]],  # confidence is not proof
        )
        for observed in violations:
            with self.subTest(observed=observed), self.assertRaises(ValueError):
                aggregate_children(observed, node_kind="and", required_ids=required)
        for kwargs in ({"required_ids": None}, {"required_ids": ("x", "x", "y")},
                       {"required_ids": required, "probabilities": [1., 0., 0.]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                aggregate_children(complete, node_kind="and", **kwargs)
        with self.assertRaises(ValueError):
            aggregate_children([True, True], node_kind="choice")
        with self.assertRaises(ValueError):
            aggregate_children([0., 1.], node_kind="chance", probabilities=[0.5, 0.5],
                               required_ids=("a", "b"))

    def test_nonfinite_discount_or_invalid_duration_rejected(self):
        for rate, duration in ((float("nan"), 1), (-1, 1), (0, 0), (0, True)):
            with self.assertRaises(ValueError):
                discounted_segments([(0, duration)], terminal_value=1, discount_rate=rate)


if __name__ == "__main__":
    unittest.main()
