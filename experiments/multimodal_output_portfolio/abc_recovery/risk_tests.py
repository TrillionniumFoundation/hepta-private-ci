"""Enumerated finite-process checks; no empirical neural-performance claims."""

from decimal import Decimal, localcontext
import itertools
import math
import unittest

from .risk import Decision, Outcome, TerminalLaw, conditional_ce, conditional_policy_loss_bound, solve_finite_tree


def decimal_ce(outcomes, gamma):
    with localcontext() as ctx:
        ctx.prec = 70
        g = Decimal(str(gamma))
        atoms = [(Decimal(str(p)), Decimal(str(u))) for p, u in outcomes]
        if g == 0:
            return float(sum(p * u for p, u in atoms))
        return float(-sum(p * (-g * u).exp() for p, u in atoms).ln() / g)


def trajectories(nodes, policy, history="root", probability=Decimal(1), spent=Decimal(0)):
    node = nodes[history]
    if isinstance(node, TerminalLaw):
        return [(probability * Decimal(str(p)), Decimal(str(u)) - spent) for p, u in zip(node.probabilities, node.utilities)]
    result = []
    for outcome in node.actions[policy[history]]:
        result.extend(trajectories(nodes, policy, outcome.next_history, probability * Decimal(str(outcome.probability)), spent + Decimal(str(outcome.cost))))
    return result


def branching_process():
    return {
        "root": Decision({"safe": (Outcome(1.0, "safe_end"),), "branch": (Outcome(0.4, "left", 0.1), Outcome(0.6, "right"))}),
        "left": Decision({"keep": (Outcome(1.0, "left_keep"),), "adjust": (Outcome(1.0, "left_adjust", 0.04),)}),
        "right": Decision({"keep": (Outcome(1.0, "right_keep"),), "adjust": (Outcome(1.0, "right_adjust", 0.03),)}),
        "safe_end": TerminalLaw((0.35,), (1.0,)),
        "left_keep": TerminalLaw((0.1, 0.7), (0.7, 0.3)),
        "left_adjust": TerminalLaw((0.6, 0.2), (0.8, 0.2)),
        "right_keep": TerminalLaw((0.9, 0.5), (0.3, 0.7)),
        "right_adjust": TerminalLaw((0.65,), (1.0,)),
    }


class ConditionalRiskTests(unittest.TestCase):
    def test_zero_limit_large_offsets_and_large_exponents(self):
        atoms = [(0.2, -3.0), (0.3, 2.0), (0.5, 7.0)]
        for gamma in (0.0, 1e-12, 1e-7, 2.0, 1000.0):
            actual = conditional_ce([u for _, u in atoms], [p for p, _ in atoms], gamma)
            self.assertAlmostEqual(actual, decimal_ce(atoms, gamma), places=11)
        shifted = [(p, u + 1e6) for p, u in atoms]
        self.assertAlmostEqual(conditional_ce([u for _, u in shifted], [p for p, _ in shifted]), decimal_ce(shifted, 2.0), places=9)

    def test_conditional_tower_and_hidden_terminal_target(self):
        left, right = [(0.2, -0.3), (0.8, 0.9)], [(0.6, 0.2), (0.4, 0.7)]
        for gamma in (0.0, 1e-9, 2.0):
            child_values = [conditional_ce([u for _, u in law], [p for p, _ in law], gamma) for law in (left, right)]
            flattened = [(outer * p, u) for outer, law in ((0.25, left), (0.75, right)) for p, u in law]
            self.assertAlmostEqual(conditional_ce(child_values, (0.25, 0.75), gamma), decimal_ce(flattened, gamma), places=11)
        nodes = {"root": Decision({"safe": (Outcome(1, "s"),), "gamble": (Outcome(1, "g"),)}), "s": TerminalLaw((0.4,), (1,)), "g": TerminalLaw((0, 1), (0.5, 0.5))}
        self.assertEqual(solve_finite_tree(nodes, "root").policy, {"root": "safe"})
        self.assertEqual(solve_finite_tree(nodes, "root", gamma=0).policy, {"root": "gamble"})

    def test_dynamic_program_matches_all_causal_policies_enumerated(self):
        nodes = branching_process()
        policies = [dict(zip(("root", "left", "right"), acts)) for acts in itertools.product(("safe", "branch"), ("keep", "adjust"), ("keep", "adjust"))]
        for gamma in (0.0, 1e-8, 2.0, 20.0):
            exact = [decimal_ce(trajectories(nodes, policy), gamma) for policy in policies]
            self.assertAlmostEqual(solve_finite_tree(nodes, "root", gamma).root_value, max(exact), places=11)
            for policy, value in zip(policies, exact):
                self.assertAlmostEqual(solve_finite_tree(nodes, "root", gamma, policy).root_value, value, places=11)
            # Randomizing between complete causal policies cannot beat the best.
            for alpha in (0.1, 0.35, 0.9):
                alpha = Decimal(str(alpha))
                mixture = [(alpha * p, u) for p, u in trajectories(nodes, policies[0])]
                mixture += [((1 - alpha) * p, u) for p, u in trajectories(nodes, policies[-1])]
                self.assertLessEqual(decimal_ce(mixture, gamma), max(exact) + 1e-12)

    def test_random_cost_is_not_replaced_by_mean_cost(self):
        nodes = {"root": Decision({"emit": (Outcome(0.5, "end", 0.0), Outcome(0.5, "end", 0.4))}), "end": TerminalLaw((0.7,), (1,))}
        value = solve_finite_tree(nodes, "root").root_value
        self.assertAlmostEqual(value, decimal_ce([(0.5, 0.7), (0.5, 0.3)], 2), places=12)
        self.assertLess(value, 0.7 - 0.2)

    def test_new_public_information_has_value_without_target_leakage(self):
        hidden = {"root": Decision({"guess0": (Outcome(1, "g0"),), "guess1": (Outcome(1, "g1"),)}), "g0": TerminalLaw((1, 0), (0.5, 0.5)), "g1": TerminalLaw((0, 1), (0.5, 0.5))}
        revealed = {"root": Decision({"observe": (Outcome(0.5, "seen0", 0.1), Outcome(0.5, "seen1", 0.1))}), "seen0": Decision({"guess0": (Outcome(1, "win"),), "guess1": (Outcome(1, "lose"),)}), "seen1": Decision({"guess0": (Outcome(1, "lose"),), "guess1": (Outcome(1, "win"),)}), "win": TerminalLaw((1,), (1,)), "lose": TerminalLaw((0,), (1,))}
        blind = solve_finite_tree(hidden, "root")
        informed = solve_finite_tree(revealed, "root")
        self.assertAlmostEqual(blind.root_value, decimal_ce([(0.5, 0), (0.5, 1)], 2))
        self.assertAlmostEqual(informed.root_value, 0.9)
        self.assertEqual(informed.policy, {"seen0": "guess0", "seen1": "guess1", "root": "observe"})
        self.assertGreater(informed.root_value, blind.root_value)

    def test_log_target_regression_changes_the_risk_decision(self):
        samples = (1.0, 9.0)
        candidates = (3.0, 4.0, 5.0)
        arithmetic_fit = min(candidates, key=lambda z: sum((z - y) ** 2 for y in samples))
        log_fit = min(candidates, key=lambda z: sum((math.log(z) - math.log(y)) ** 2 for y in samples))
        self.assertEqual((arithmetic_fit, log_fit), (5.0, 3.0))
        self.assertGreater(arithmetic_fit, 4.0)  # Correctly prefer a sure moment 4.
        self.assertLess(log_fit, 4.0)  # The log-target shortcut reverses that choice.

    def test_joint_task_ce_and_mean_conditional_ce_reverse_ranking(self):
        conditional_a = sum(conditional_ce((u,)) for u in (0.0, 1.0)) / 2
        conditional_b = conditional_ce((0.4,))
        joint_a = decimal_ce([(0.5, 0.0), (0.5, 1.0)], 2)
        joint_b = decimal_ce([(1.0, 0.4)], 2)
        self.assertGreater(conditional_a, conditional_b)
        self.assertLess(joint_a, joint_b)

    def test_policy_loss_bound_requires_uniform_errors_on_true_q(self):
        nodes = branching_process()
        optimum = solve_finite_tree(nodes, "root")
        delta = 0.1
        approximate = {h: {a: q + (-delta if a == optimum.policy[h] else delta) for a, q in scores.items()} for h, scores in optimum.action_values.items()}
        policy = {h: max(scores, key=scores.get) for h, scores in approximate.items()}
        actual_errors = [abs(q - optimum.action_values[h][a]) for h, scores in approximate.items() for a, q in scores.items()]
        self.assertLessEqual(max(actual_errors), delta + 1e-12)
        self.assertNotEqual(policy["root"], optimum.policy["root"])
        realized = decimal_ce(trajectories(nodes, policy), 2)
        self.assertLessEqual(optimum.root_value - realized, conditional_policy_loss_bound((delta, delta)) + 1e-12)

    def test_invalid_laws_cycles_and_infeasible_actions_fail(self):
        for values, probabilities, gamma in (((), (), 2), ((0, 1), (0.2, 0.2), 2), ((0, 1), (-0.1, 1.1), 2), ((math.nan,), (1,), 2), ((0,), (1,), -1)):
            with self.assertRaises(ValueError):
                conditional_ce(values, probabilities, gamma)
        cyclic = {"root": Decision({"loop": (Outcome(1, "root"),)})}
        with self.assertRaisesRegex(ValueError, "cycle"):
            solve_finite_tree(cyclic, "root")
        with self.assertRaisesRegex(ValueError, "infeasible"):
            solve_finite_tree(branching_process(), "root", policy={"root": "unknown"})


if __name__ == "__main__":
    unittest.main()
