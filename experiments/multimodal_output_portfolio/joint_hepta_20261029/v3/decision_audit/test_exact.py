"""Behavioral counterexamples and independent complete-world policy replay."""

from dataclasses import replace
from fractions import Fraction as F
import unittest

from .exact import (
    Problem, World, adaptive_problem, best_fixed, brute_force, clairvoyant,
    public_policy, replay, risk_crosscheck, solve, xor_problem,
)


class ExactTests(unittest.TestCase):
    def test_online_dp_matches_independent_information_tree_enumeration(self):
        expected = {"xor": (F(2, 5), F(2, 5), F(7, 10)),
                    "adaptive": (F(2, 5), F(11, 20), F(7, 10))}
        for name, factory in (("xor", xor_problem), ("adaptive", adaptive_problem)):
            for horizon, gold in zip((3, 4, 5), expected[name]):
                with self.subTest(name=name, horizon=horizon):
                    problem = factory(horizon)
                    self.assertEqual((solve(problem)["value"], brute_force(problem)["value"],
                                      replay(problem, public_policy(problem))["value"]), (gold,) * 3)

    def test_fixed_schedule_uses_observed_semantics(self):
        # XOR is NOT evidence that adaptive allocation beats strong fixed work.
        self.assertEqual(best_fixed(xor_problem())["value"], F(7, 10))
        fixed = best_fixed(adaptive_problem())
        self.assertEqual(fixed, {"value": F(3, 5), "schedule": ("sense", "zoom", "text", "image", "stop")})
        self.assertEqual(solve(adaptive_problem())["value"] - fixed["value"], F(1, 10))

    def test_nonmyopic_information_not_artificially_weak_completion(self):
        p = xor_problem()
        self.assertEqual(replay(p, public_policy(p, 1))["value"], F(2, 5))
        self.assertEqual(replay(p, public_policy(p, 2))["value"], F(7, 10))
        p = adaptive_problem()
        # Receding one-signal lookahead can use zoom after a real ambiguous signal.
        self.assertEqual(replay(p, public_policy(p, 1))["value"], F(7, 10))

    def test_probe_names_cannot_alias_generation_schedule_kinds(self):
        original = adaptive_problem()
        for renamed in ("detail", "text", "image"):
            worlds = tuple(replace(w, signals=tuple((renamed if n == "zoom" else n, v)
                                                    for n, v in w.signals)) for w in original.worlds)
            probes = tuple((renamed if n == "zoom" else n, cost, dep)
                           for n, cost, dep in original.probes)
            if renamed == "detail":
                self.assertEqual(best_fixed(replace(original, worlds=worlds, probes=probes))["value"], F(3, 5))
            else:
                with self.assertRaises(ValueError):
                    replace(original, worlds=worlds, probes=probes, revisions=True)

    def test_fixed_content_feasibility_preserves_all_outcome_branches(self):
        for target in (0, 1):
            with self.subTest(target=target):
                world = World(F(1), target, (), (f"text:{1 - target}",))
                problem = Problem((world,), (), horizon=3)
                self.assertEqual(best_fixed(problem),
                                 {"value": F(9, 10), "schedule": ("text", "image", "stop")})
                self.assertEqual((solve(problem)["value"], brute_force(problem)["value"]),
                                 (F(9, 10), F(9, 10)))
        # No single initial text choice completes this fixed schedule in both
        # worlds. Its failed branch cannot be dropped from the expectation.
        problem = Problem((World(F(1, 2), 1, (), ("text:0",)),
                           World(F(1, 2), 1, (), ("text:1",))), (), horizon=3)
        self.assertEqual(best_fixed(problem), {"value": F(0), "schedule": ("stop",)})
        self.assertEqual(solve(problem)["value"], F(17, 40))

    def test_clairvoyant_is_upper_only_and_same_world_law(self):
        for factory in (xor_problem, adaptive_problem):
            for horizon in (3, 4, 5):
                p = factory(horizon)
                upper = clairvoyant(p)
                self.assertEqual((upper["value"], upper["deployable"]), (F(9, 10), False))
                self.assertLessEqual(solve(p)["value"], upper["value"])
                self.assertEqual(sum(w.mass for w in p.worlds), F(1))

    def test_horizon_expiry_never_implicitly_delivers(self):
        p = xor_problem(3)
        actions = iter(("sense_a", "text:0", "image:0"))
        w = p.worlds[0]
        h = ()
        for a in actions:
            self.assertIn(a, p.legal(h))
            h += ((a, w.observe(a)),)
        self.assertEqual((p.legal(h), p.reward(h, w)), ((), F(0)))

    def test_budget_and_dependency_are_checked_before_work(self):
        p = adaptive_problem(budget=F(9, 100))
        self.assertNotIn("sense", p.legal(()))
        self.assertNotIn("zoom", p.legal(()))
        self.assertNotIn("image:0", p.legal(()))
        self.assertEqual(solve(p)["value"], F(0))
        with self.assertRaises(ValueError):
            p.branches((), "zoom")
        for amount in (F(0), F(1, 10), F(1, 5), F(2, 5), F(1)):
            self.assertLessEqual(solve(adaptive_problem(budget=amount))["value"], F(7, 10))

    def test_failed_and_unselected_candidates_remain_charged(self):
        w = World(F(1), 1, (), ("text:0",))
        p = Problem((w,), (), revisions=True)
        seq = ("text:0", "text:1", "image:1", "stop")
        result = replay(p, lambda h: seq[len(h)])
        self.assertEqual((result["value"], result["paths"][0]["cost"]), (F(17, 20), F(3, 20)))
        self.assertEqual(result["paths"][0]["history"][0], ("text:0", "failed"))
        p = replace(p, worlds=(replace(w, failures=()),))
        result = replay(p, lambda h: seq[len(h)])
        # The successful text:0 candidate is superseded, but never refunded.
        self.assertEqual((result["value"], result["paths"][0]["cost"]), (F(17, 20), F(3, 20)))

    def test_policy_has_same_action_at_identical_public_histories(self):
        p = adaptive_problem()
        choose = public_policy(p)
        histories = replay(p, choose)["paths"]
        self.assertEqual({path["history"][0][0] for path in histories}, {"sense"})
        roots = iter(("stop", "text:0", "stop", "stop"))
        with self.assertRaisesRegex(ValueError, "nonanticipating"):
            replay(p, lambda h: next(roots) if not h else "stop")

    def test_world_order_does_not_leak_into_public_policy(self):
        p = adaptive_problem()
        other = replace(p, worlds=tuple(reversed(p.worlds)))
        self.assertEqual(solve(p)["value"], solve(other)["value"])
        choose, alternate = public_policy(p), public_policy(other)
        for path in replay(p, choose)["paths"]:
            h = ()
            for event in path["history"]:
                self.assertEqual(choose(h), alternate(h))
                h += (event,)

    def test_cost_increases_cannot_increase_online_value(self):
        p = adaptive_problem()
        expensive = replace(p, probes=(("sense", F(3, 10), None), ("zoom", F(2, 5), "sense")))
        self.assertLessEqual(solve(expensive)["value"], solve(p)["value"])
        self.assertEqual(solve(replace(p, generation_cost=F(1)))["value"], F(0))

    def test_inherited_entropic_oracle_matches_actual_policy_law(self):
        for factory in (xor_problem, adaptive_problem):
            for horizon in (3, 4, 5):
                with self.subTest(model=factory.__name__, horizon=horizon):
                    result = risk_crosscheck(factory(horizon))
                    self.assertLessEqual(result["absolute_error"], 1e-12)
        self.assertAlmostEqual(risk_crosscheck(xor_problem())["dp_ce"], 0.7)
        # Adaptive cost is stochastic; its CE must not be replaced by E[return].
        self.assertLess(risk_crosscheck(adaptive_problem())["dp_ce"], 0.7)

    def test_enumeration_limits_and_missing_mass_reject(self):
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            brute_force(xor_problem(), max_trees=1)
        p = adaptive_problem()
        with self.assertRaises(ValueError):
            replace(p, worlds=p.worlds[:-1])
        with self.assertRaises(ValueError):
            replace(p, generation_cost=F(-1))
        with self.assertRaises(ValueError):
            replace(p, worlds=(replace(p.worlds[0], mass=F(1), signals=()),))


if __name__ == "__main__":
    unittest.main()
