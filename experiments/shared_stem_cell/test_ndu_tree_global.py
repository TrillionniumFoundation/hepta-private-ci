"""Exact finite public-belief BSDE checks and global FBSDE obstruction regression.

No pretrained Encoder, real external outcomes, or production authority involved.
"""
import unittest
from dataclasses import replace
from fractions import Fraction as F
from ndu_tree_global import (Edge, Node, StudyError, audit_finite_tree,
                             audit_piecewise_global, exact_global_segments, q, solve)


def e(name, target, probability=0, cost=0):
    return Edge(name, target, F(probability), F(cost))


def t(v, h=()):
    return Node("terminal", h, terminal_utility=F(v))


def sample_tree():
    return {
        "root": Node("or", (), (e("stop", "stop"), e("observe", "coin", cost="1/8"))),
        "stop": t("1/4"),
        "coin": Node("chance", (), (e("heads", "left", "3/4"),
                                    e("tails", "right", "1/4"))),
        "left": t(1, ("heads",)),
        "right": t(0, ("tails",)),
    }


class ExactBeliefTreeTests(unittest.TestCase):
    def test_exact_bernoulli_bsde_and_action_cost(self):
        nodes = sample_tree()
        result = solve(nodes, "root")
        self.assertEqual(result.value, F("5/8"))
        self.assertEqual(result.policy["root"], "observe")
        self.assertEqual(result.covariance["coin"], F("3/16"))
        self.assertEqual(result.z["coin"], -1)
        self.assertEqual(result.cross_moment["coin"], F("-3/16"))
        self.assertTrue(audit_finite_tree(nodes, "root", result)["finite_tree_solved"])
        self.assertFalse(result.general_fbsde_solved)

    def test_stop_is_required_and_tie_prefers_no_cost(self):
        nodes = sample_tree()
        nodes["root"] = Node("or", (), (e("stop", "stop"), e("observe", "coin", cost="1/2")))
        result = solve(nodes, "root")
        self.assertEqual(result.value, F("1/4"))
        self.assertEqual(result.policy["root"], "stop")
        del nodes["stop"]
        with self.assertRaises(StudyError):
            solve(nodes, "root")

    def test_conjunctive_obligations_cannot_be_or(self):
        nodes = {"a": Node("and", (), (e("one", "good"), e("two", "bad"))),
                 "good": t(1), "bad": t(-1)}
        result = solve(nodes, "a")
        self.assertEqual(result.value, -1)
        self.assertTrue(audit_finite_tree(nodes, "a", result)["finite_tree_solved"])
        self.assertNotEqual(result.value, max(result.values["good"], result.values["bad"]))

    def test_public_information_only_chance(self):
        nodes = sample_tree()
        nodes["right"] = t(0, ("hidden-world",))
        with self.assertRaisesRegex(StudyError, "public event"):
            solve(nodes, "root")

    def test_decision_cannot_look_ahead(self):
        nodes = sample_tree()
        nodes["stop"] = t("1/4", ("future",))
        with self.assertRaisesRegex(StudyError, "future/unobserved"):
            solve(nodes, "root")

    def test_bad_probabilities_and_float_rejected(self):
        nodes = sample_tree()
        nodes["coin"] = Node("chance", (), (e("heads", "left", "1/2"),
                                             e("tails", "right", "1/4")))
        with self.assertRaisesRegex(StudyError, "sum"):
            solve(nodes, "root")
        self.assertRaises(StudyError, q, 0.25)
        self.assertRaises(StudyError, q, True)
        self.assertRaises(StudyError, q, "1/0")

    def test_cycle_and_unreachable_rejected(self):
        nodes = sample_tree()
        nodes["orphan"] = t(5)
        with self.assertRaisesRegex(StudyError, "unreachable"):
            solve(nodes, "root")
        del nodes["orphan"]
        nodes["root"] = Node("or", (), (e("stop", "stop"), e("back", "root")))
        with self.assertRaisesRegex(StudyError, "cycle"):
            solve(nodes, "root")

    def test_reject_tampered_policy_and_Z_and_terminal(self):
        nodes = sample_tree()
        sol = solve(nodes, "root")
        bad = replace(sol, policy={"root": "stop"})
        with self.assertRaisesRegex(StudyError, "forward"):
            audit_finite_tree(nodes, "root", bad)
        bad = replace(sol, z={"coin": F(99)})
        with self.assertRaisesRegex(StudyError, "BSDE"):
            audit_finite_tree(nodes, "root", bad)
        bad_values = dict(sol.values, right=F(1))
        with self.assertRaises(StudyError):
            audit_finite_tree(nodes, "root", replace(sol, values=bad_values))
        with self.assertRaisesRegex(StudyError, "authority"):
            audit_finite_tree(nodes, "root", replace(sol, production_accepted=True))

    def test_shared_dag_but_not_cross_history_merge(self):
        # Both public action paths can share a terminal when history matches.
        nodes = {"root": Node("or", (), (e("stop", "stop"), e("act", "inner"))),
                 "inner": Node("and", (), (e("one", "shared"), e("two", "shared"))),
                 "shared": t(1), "stop": t(0)}
        self.assertEqual(solve(nodes, "root").value, 1)
        self.assertTrue(audit_finite_tree(nodes, "root", solve(nodes, "root"))["finite_tree_solved"])
        nodes["shared"] = t(1, ("secret",))
        with self.assertRaises(StudyError):
            solve(nodes, "root")


class ExactGlobalObstructionTests(unittest.TestCase):
    def test_two_short_unique_locals_have_no_global_solution(self):
        # Each local h=1/2 and g=1 has a unique local terminal BVP,
        # yet the global T=1, x0=1 boundary is inconsistent.
        wrong = ((F("1/2"), 1, 2, 2, 2),
                 (F("1/2"), 2, 4, 4, 4))
        v = audit_piecewise_global(x0=1, g=1, horizon=1, segments=wrong)
        self.assertEqual(v["max_local_residual"], "0")
        self.assertEqual(v["terminal_residual"], "0")
        self.assertEqual(v["max_interface_jump"], "2")
        self.assertFalse(v["globally_solved"])
        self.assertFalse(v["global_boundary_solution_exists"])
        self.assertFalse(v["global_regular_field_admitted"])

    def test_infinite_global_solutions_not_falsely_certified(self):
        v = audit_piecewise_global(x0=0, g=1, horizon=1,
                                   segments=((F("1/2"), 0, 0, 0, 0),
                                             (F("1/2"), 0, 0, 0, 0)))
        self.assertTrue(v["global_boundary_solution_exists"])
        self.assertFalse(v["global_regular_field_admitted"])
        self.assertFalse(v["globally_solved"])

    def test_correct_global_continuation_and_interface(self):
        pieces = exact_global_segments(x0=1, g=1, horizon=F("4/5"), parts=4)
        self.assertEqual(pieces[0][2], 5)
        self.assertEqual(pieces[-1][3], 5)
        v = audit_piecewise_global(x0=1, g=1, horizon=F("4/5"), segments=pieces)
        self.assertTrue(v["globally_solved"])
        self.assertEqual(v["max_interface_jump"], "0")
        self.assertEqual(v["terminal_residual"], "0")
        self.assertFalse(v["production_accepted"])

    def test_unique_boundary_but_pole_crossing_is_unsupported(self):
        with self.assertRaisesRegex(StudyError, "regular field"):
            exact_global_segments(x0=1, g=1, horizon=F("3/2"), parts=12)
        # Unique algebraic BVP solution, but registered regular field fails.
        x = 1
        y = F(-2)
        v = audit_piecewise_global(x0=x, g=1, horizon=F("3/2"),
                                   segments=((F("3/2"), x, y, x + F("3/2")*y, y),))
        self.assertTrue(v["global_boundary_solution_exists"])
        self.assertFalse(v["globally_solved"])

    def test_local_residual_and_terminal_are_not_sufficient(self):
        correct = exact_global_segments(x0=1, g=1, horizon=F("4/5"), parts=2)
        broken = list(correct)
        h, xa, ya, xb, yb = broken[1]
        broken[1] = (h, xa, ya + 1, xb + h, yb + 1)
        v = audit_piecewise_global(x0=1, g=1, horizon=F("4/5"), segments=broken)
        self.assertFalse(v["globally_solved"])
        self.assertNotEqual(v["max_interface_jump"], "0")

    def test_residual_tamper_and_elapsed_rejected(self):
        base = list(exact_global_segments(x0=1, g=1, horizon=F("1/2"), parts=2))
        a, b, c, d, e0 = base[0]
        base[0] = (a, b, c, d + 1, e0)
        self.assertFalse(audit_piecewise_global(x0=1, g=1, horizon=F("1/2"), segments=base)["globally_solved"])
        base = list(exact_global_segments(x0=1, g=1, horizon=F("1/2"), parts=2))
        h, xa, ya, xb, yb = base[0]
        base[0] = (h+F("1/8"), xa, ya, xb, yb)
        self.assertFalse(audit_piecewise_global(x0=1, g=1, horizon=F("1/2"), segments=base)["globally_solved"])
        with self.assertRaises(StudyError):
            audit_piecewise_global(x0=1, g=1, horizon=1, segments=[])


if __name__ == "__main__":
    unittest.main()
