"""Adversarial and analytic tests for the isolated SNG-R shadow numerical profile."""

import json
import math
import subprocess
import sys
import unittest
from pathlib import Path

from hepta_sngr_shadow import (
    ActionEdge,
    AffineBoundary,
    ChanceEdge,
    ChanceNode,
    DecisionNode,
    IllPosedError,
    MAX_GRAPH_NODES,
    ShadowError,
    TerminalNode,
    backup_dag,
    continuation_at_left,
    continuation_fields,
    naive_reset_baseline,
    solve_chain,
    stochastic_manufactured_fixture,
)


class MultipleShootingTests(unittest.TestCase):
    def test_two_segment_continuation_matches_exact_global_solution(self):
        report = solve_chain(1.0, (0.5, 0.5), AffineBoundary(0.5, 0.0))
        self.assertTrue(report.accepted)
        self.assertAlmostEqual(report.initial_utility, 1.0)
        self.assertAlmostEqual(report.final_state, 2.0)
        self.assertAlmostEqual(report.slices[0].final_state, 1.5)
        self.assertLess(report.max_interface_residual, 1e-12)
        self.assertLess(report.terminal_residual, 1e-12)

    def test_bad_local_terminal_reset_fails_global_gluing(self):
        terminal = AffineBoundary(0.5, 0.0)
        correct = solve_chain(1.0, (0.5, 0.5), terminal)
        wrong = naive_reset_baseline(1.0, (0.5, 0.5), terminal)
        self.assertTrue(correct.accepted)
        self.assertFalse(wrong.accepted)
        # A perfect final-terminal residual alone is NOT a global certificate.
        self.assertLess(wrong.terminal_residual, 1e-12)
        self.assertGreater(wrong.max_interface_residual, 0.2)

    def test_one_segment_and_split_are_consistent(self):
        terminal = AffineBoundary(0.25, 0.75)
        single = solve_chain(0.2, (1.0,), terminal)
        many = solve_chain(0.2, (0.1,) * 10, terminal)
        self.assertTrue(single.accepted)
        self.assertTrue(many.accepted)
        self.assertAlmostEqual(single.initial_utility, many.initial_utility, places=12)
        self.assertAlmostEqual(single.final_state, many.final_state, places=12)

    def test_local_unique_does_not_imply_global_existence(self):
        # dX=Ydt, dY=0, X0=0, Y1=X1+1 has no global solution.
        local = continuation_at_left(AffineBoundary(1.0, 1.0), 0.25)
        self.assertAlmostEqual(local.evaluate(0.0), 4.0 / 3.0)
        with self.assertRaises(IllPosedError):
            solve_chain(0.0, (0.25,) * 4, AffineBoundary(1.0, 1.0))

    def test_affine_field_blowup_and_positive_domain_guard(self):
        with self.assertRaises(IllPosedError):
            continuation_at_left(AffineBoundary(2.0, 0.0), 0.5)
        with self.assertRaises(IllPosedError):
            continuation_at_left(AffineBoundary(2.0, 0.0), 1.0)

    def test_nonzero_intercept_and_negative_slope(self):
        terminal = AffineBoundary(-0.7, 1.9)
        fields = continuation_fields((0.1, 0.2, 0.3), terminal)
        self.assertEqual(len(fields), 4)
        result = solve_chain(1.3, (0.1, 0.2, 0.3), terminal)
        self.assertTrue(result.accepted)
        self.assertLess(result.max_interface_residual, 1e-12)

    def test_reject_nan_inf_invalid_dt_and_budget(self):
        invalid = [(0.0,), (-1.0,), (math.nan,), (math.inf,), (), (0.01,) * 65]
        for durations in invalid:
            with self.subTest(durations=durations), self.assertRaises(ShadowError):
                solve_chain(0.0, durations, AffineBoundary(0.1, 0.2))
        with self.assertRaises(ShadowError):
            solve_chain(math.nan, (0.1,), AffineBoundary(0.1, 0.2))
        with self.assertRaises(ShadowError):
            solve_chain(0.0, (0.1,), AffineBoundary(math.inf, 0.2))
        with self.assertRaises(ShadowError):
            solve_chain(0.0, (0.1,), AffineBoundary(0.1, 0.2), tolerance=0.0)

    def test_zero_noise_manufactured_path_matches_deterministic(self):
        terminal = AffineBoundary(0.5, 0.25)
        exact = solve_chain(1.0, (0.5, 0.5), terminal)
        noisy = stochastic_manufactured_fixture(1.0, (0.5, 0.5), terminal, 0.0, 64, 7)
        self.assertAlmostEqual(noisy.initial_utility, exact.initial_utility, places=12)
        self.assertLess(noisy.backward_euler_residual_rms, 1e-12)
        self.assertLess(noisy.terminal_residual, 1e-12)

    def test_stochastic_euler_residual_refines_aggregate(self):
        # Independent seeded sample paths: RMS of LOCAL residuals should shrink
        # under finer dt. This is not an empirical learned-FBSDE performance claim.
        terminal = AffineBoundary(0.4, 0.3)

        def aggregate(steps):
            values = []
            for seed in range(48):
                r = stochastic_manufactured_fixture(
                    1.0, (0.4, 0.6), terminal, 0.3, steps, seed
                )
                self.assertLess(r.terminal_residual, 1e-12)
                self.assertLess(r.max_boundary_residual, 1e-12)
                values.append(r.backward_euler_residual_rms)
            return sum(values) / len(values)

        self.assertLess(aggregate(64), aggregate(8) * 0.3)

    def test_noise_and_seed_guards(self):
        for sigma, steps, seed in [
            (-0.1, 8, 1),
            (math.nan, 8, 1),
            (0.1, 0, 1),
            (0.1, 5000, 1),
            (0.1, 8, -1),
        ]:
            with (
                self.subTest(sigma=sigma, steps=steps, seed=seed),
                self.assertRaises(ShadowError),
            ):
                stochastic_manufactured_fixture(
                    0.0, (0.1,), AffineBoundary(0.3, 0.1), sigma, steps, seed
                )


class DagBackupTests(unittest.TestCase):
    def test_control_max_but_chance_expectation(self):
        graph = {
            "root": DecisionNode(
                (
                    ActionEdge("guess", "guess", 0.0),
                    ActionEdge("inspect", "chance", 0.5),
                )
            ),
            "guess": TerminalNode(1.0),
            "chance": ChanceNode((ChanceEdge("good", 0.5), ChanceEdge("bad", 0.5))),
            "good": TerminalNode(5.0),
            "bad": TerminalNode(1.0),
        }
        report = backup_dag(graph, "root", frozenset({"guess", "inspect"}))
        self.assertAlmostEqual(report.root_utility, 2.5)
        self.assertEqual(report.selected_actions["root"], "inspect")

    def test_legal_action_mask_and_order_invariance(self):
        actions = (ActionEdge("a", "first", 0.1), ActionEdge("b", "second", 0.1))
        graph = {
            "root": DecisionNode(actions),
            "first": TerminalNode(3.0),
            "second": TerminalNode(3.0),
        }
        reversed_graph = dict(graph, root=DecisionNode(tuple(reversed(actions))))
        allowed = frozenset({"a", "b"})
        self.assertEqual(
            backup_dag(graph, "root", allowed).selected_actions["root"], "a"
        )
        self.assertEqual(
            backup_dag(reversed_graph, "root", allowed).selected_actions["root"], "a"
        )
        masked = backup_dag(graph, "root", frozenset({"b"}))
        self.assertEqual(masked.selected_actions["root"], "b")
        with self.assertRaises(ShadowError):
            backup_dag(graph, "root", frozenset())

    def test_dag_shared_descendants_are_evaluated_once(self):
        nodes = {
            "root": ChanceNode((ChanceEdge("left", 0.5), ChanceEdge("right", 0.5))),
            "left": DecisionNode((ActionEdge("a", "shared", 0.2),)),
            "right": DecisionNode((ActionEdge("a", "shared", 0.4),)),
            "shared": TerminalNode(3.0),
        }
        report = backup_dag(nodes, "root", frozenset({"a"}))
        self.assertEqual(report.unique_evaluated_nodes, 4)
        self.assertEqual(report.memoized_references, 1)
        self.assertAlmostEqual(report.root_utility, 2.7)

    def test_unknown_target_cycle_and_overbudget_fail(self):
        with self.assertRaisesRegex(ShadowError, "missing"):
            backup_dag(
                {"root": DecisionNode((ActionEdge("a", "gone", 0.0),))},
                "root",
                frozenset({"a"}),
            )
        with self.assertRaisesRegex(ShadowError, "cycle"):
            backup_dag(
                {"root": DecisionNode((ActionEdge("a", "root", 0.0),))},
                "root",
                frozenset({"a"}),
            )
        with self.assertRaisesRegex(ShadowError, "size"):
            backup_dag(
                {str(n): TerminalNode(1.0) for n in range(MAX_GRAPH_NODES + 1)},
                "0",
                frozenset(),
            )

    def test_bad_probabilities_missing_evidence_and_cost_fail(self):
        for probs in ((0.3, 0.3), (-0.1, 1.1), (math.nan, 1.0)):
            graph = {
                "root": ChanceNode(
                    (ChanceEdge("a", probs[0]), ChanceEdge("b", probs[1]))
                ),
                "a": TerminalNode(1.0),
                "b": TerminalNode(2.0),
            }
            with self.subTest(probs=probs), self.assertRaises(ShadowError):
                backup_dag(graph, "root", frozenset())
        with self.assertRaises(ShadowError):
            backup_dag({"root": TerminalNode(math.nan)}, "root", frozenset())
        with self.assertRaises(ShadowError):
            backup_dag(
                {
                    "root": DecisionNode((ActionEdge("a", "t", -1.0),)),
                    "t": TerminalNode(1.0),
                },
                "root",
                frozenset({"a"}),
            )

    def test_duplicate_action_identifier_rejected(self):
        with self.assertRaisesRegex(ShadowError, "duplicate"):
            backup_dag(
                {
                    "root": DecisionNode(
                        (ActionEdge("a", "x", 0.0), ActionEdge("a", "x", 0.0))
                    ),
                    "x": TerminalNode(1.0),
                },
                "root",
                frozenset({"a"}),
            )

    def test_missing_zero_weight_chance_branch_rejected(self):
        # Do not silently erase possible unsupported graph state by a zero weight.
        with self.assertRaisesRegex(ShadowError, "missing"):
            backup_dag(
                {
                    "root": ChanceNode(
                        (ChanceEdge("safe", 1.0), ChanceEdge("missing", 0.0))
                    ),
                    "safe": TerminalNode(1.0),
                },
                "root",
                frozenset(),
            )


class CommandLineTests(unittest.TestCase):
    def test_demo_is_deterministic_and_json(self):
        script = Path(__file__).with_name("hepta_sngr_shadow.py")
        command = [sys.executable, str(script), "--demo"]
        first = subprocess.check_output(command, text=True)
        second = subprocess.check_output(command, text=True)
        self.assertEqual(first, second)
        payload = json.loads(first)
        self.assertEqual(
            payload["evidence_class"], "synthetic_analytic_fixture_not_learned_fbsde"
        )
        self.assertTrue(payload["correct"]["accepted"])
        self.assertFalse(payload["naive_reset"]["accepted"])


if __name__ == "__main__":
    unittest.main()
