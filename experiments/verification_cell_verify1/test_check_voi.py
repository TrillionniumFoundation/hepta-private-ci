"""Exact decision-value cases, correlated evidence and admission boundaries."""

from dataclasses import replace
import unittest

from .check_voi import (
    CheckerChannel,
    DecisionProblem,
    OutcomeDecision,
    evaluate_check,
    select_check_voi,
)


def problem(probability=0.2):
    return DecisionProblem(
        ("correct", "error"),
        (1 - probability, probability),
        ("accept", "reject"),
        ((0, 100), (5, 5)),
    )


def channel(sensitivity=1, false_positive=0, cost=1, checker_id="checker"):
    return CheckerChannel(
        checker_id,
        ("positive", "negative"),
        ((false_positive, 1 - false_positive), (sensitivity, 1 - sensitivity)),
        cost,
    )


class CheckVoiTests(unittest.TestCase):
    def test_exact_bayes_values_include_false_positives_and_cost(self):
        cases = (
            (1, 0, 1, 1, 3),
            (0.9, 0.05, 1, 3.1, 0.9),
            (0.5, 0.5, 1, 5, -1),
            (0, 1, 1, 1, 3),
            (1, 0, 5, 1, -1),
        )
        for sensitivity, false_positive_rate, cost, after, net in cases:
            with self.subTest(
                sensitivity=sensitivity,
                false_positive_rate=false_positive_rate,
                cost=cost,
            ):
                result = evaluate_check(
                    problem(), channel(sensitivity, false_positive_rate, cost)
                )
                self.assertEqual(
                    (result.before_action, result.before_loss), ("reject", 5)
                )
                self.assertAlmostEqual(result.expected_after_loss, after)
                self.assertAlmostEqual(result.net_value, net)
                self.assertAlmostEqual(sum(x.probability for x in result.outcomes), 1)

    def test_perfect_check_outcome_decisions_are_auditable(self):
        result = evaluate_check(problem(), channel())
        self.assertEqual(
            result.outcomes,
            (
                OutcomeDecision("positive", 0.2, "reject", 5, (0, 1)),
                OutcomeDecision("negative", 0.8, "accept", 0, (1, 0)),
            ),
        )

    def test_no_legal_response_change_has_no_information_value(self):
        constrained = replace(problem(), actions=("reject",), losses=((5, 5),))
        result = evaluate_check(constrained, channel())
        self.assertEqual(
            (
                result.before_loss,
                result.expected_after_loss,
                result.gross_value,
                result.net_value,
            ),
            (5, 5, 0, -1),
        )
        self.assertEqual(
            select_check_voi(constrained, (channel(),), 10).status, "defer"
        )

    def test_zero_probability_outcome_and_state(self):
        result = evaluate_check(problem(0), channel())
        self.assertEqual(
            result.outcomes[0], OutcomeDecision("positive", 0, None, None, None)
        )
        self.assertEqual((result.expected_after_loss, result.gross_value), (0, 0))

    def test_unknown_is_a_modeled_outcome_not_a_pass(self):
        check = CheckerChannel("timeout", ("unknown", "pass"), ((0, 1), (1, 0)), 1)
        result = evaluate_check(problem(), check)
        self.assertEqual(tuple(x.action for x in result.outcomes), ("reject", "accept"))
        self.assertEqual(result.net_value, 3)

    def test_shared_latent_failure_makes_repeat_uninformative(self):
        prior = DecisionProblem(
            (
                "correct_positive",
                "correct_negative",
                "error_positive",
                "error_negative",
            ),
            (0.04, 0.76, 0.18, 0.02),
            ("accept", "reject"),
            ((0, 0, 100, 100), (5, 5, 5, 5)),
        )
        shared = CheckerChannel(
            "shared", ("positive", "negative"), ((1, 0), (0, 1), (1, 0), (0, 1)), 1
        )
        first = evaluate_check(prior, shared)
        self.assertAlmostEqual(first.net_value, 0.9)
        conditioned = replace(prior, probabilities=first.outcomes[1].posterior)
        repeat = evaluate_check(conditioned, shared)
        self.assertEqual((repeat.gross_value, repeat.net_value), (0, -1))
        independent = evaluate_check(problem(0.02 / 0.78), channel(0.9, 0.05))
        self.assertAlmostEqual(independent.net_value, 0.9487179487179485)

    def test_selection_affordability_positive_value_and_unsupported(self):
        checks = (channel(checker_id="z"), channel(0.5, 0.5, checker_id="useless"))
        self.assertEqual(select_check_voi(problem(), checks, 0.9).status, "defer")
        self.assertEqual(select_check_voi(problem(), checks, 1).checker_id, "z")
        self.assertEqual(select_check_voi(problem(), (), 1).status, "unsupported")
        self.assertEqual(
            select_check_voi(problem(), (channel(cost=4),), 4).status, "defer"
        )

    def test_mandatory_never_waived_even_when_negative_value(self):
        checks = (channel(0.5, 0.5, checker_id="owner"), channel(checker_id="schema"))
        for budget in (0, 1.5):
            result = select_check_voi(problem(), checks, budget, ("owner", "schema"))
            self.assertEqual(
                (result.status, result.reason), ("blocked", "mandatory_budget_exceeded")
            )
        result = select_check_voi(problem(), checks, 2, ("owner", "schema"))
        self.assertEqual(
            (result.status, result.checker_id, result.reason),
            ("check", "owner", "mandatory_check"),
        )
        self.assertEqual(
            select_check_voi(problem(), checks, 20, ("missing",)).status, "blocked"
        )

    def test_deterministic_ties(self):
        checks = (channel(checker_id="z"), channel(checker_id="a"))
        for ordered in (checks, checks[::-1]):
            self.assertEqual(select_check_voi(problem(), ordered, 1).checker_id, "a")
        tied = replace(problem(), actions=("first", "second"), losses=((5, 5), (5, 5)))
        self.assertEqual(evaluate_check(tied, channel()).before_action, "first")

    def test_rejects_bad_numeric_values_and_bool(self):
        for value in (True, False, -1, float("nan"), float("inf"), 1e13, 10**400, "1"):
            with self.subTest(value=value):
                for factory in (
                    lambda: channel(cost=value),
                    lambda: select_check_voi(problem(), (), value),
                    lambda: replace(problem(), losses=((0, value), (5, 5))),
                ):
                    with self.assertRaises(ValueError):
                        factory()
        for probabilities in ((True, 0), (0.7, 0.4), (0, 0), (0.5,), (-0.1, 1.1)):
            with self.assertRaises(ValueError):
                replace(problem(), probabilities=probabilities)

    def test_rejects_shapes_duplicates_and_unbounded_inputs(self):
        invalid = (
            lambda: replace(problem(), states=("same", "same")),
            lambda: replace(problem(), states=("x" * 129, "e")),
            lambda: replace(problem(), states=tuple(str(i) for i in range(129))),
            lambda: replace(problem(), actions=()),
            lambda: replace(problem(), losses=((0,), (5, 5))),
            lambda: replace(channel(), likelihoods=((0, 1),)),
            lambda: replace(channel(), outcomes=("same", "same")),
            lambda: replace(channel(), likelihoods=((0, 0.9), (1, 0))),
            lambda: select_check_voi(problem(), (channel(), channel()), 10),
            lambda: select_check_voi(problem(), (channel(),) * 65, 10),
            lambda: select_check_voi(problem(), (), 10, ("owner", "owner")),
            lambda: select_check_voi(problem(), (), 10, True),
        )
        for factory in invalid:
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    value = factory()
                    if type(value) is CheckerChannel:
                        evaluate_check(problem(), value)

    def test_supported_small_roundoff_and_immutable_vectors(self):
        probabilities = [0.8, 0.2 - 2e-13]
        admitted = replace(problem(), probabilities=probabilities)
        probabilities[0] = 0
        self.assertAlmostEqual(sum(admitted.probabilities), 1)
        self.assertGreater(admitted.probabilities[0], 0.79)
        self.assertEqual(evaluate_check(admitted, channel(0.5, 0.5, 0)).gross_value, 0)


if __name__ == "__main__":
    unittest.main()
