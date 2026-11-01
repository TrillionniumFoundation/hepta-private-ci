"""Behavioral tests of the public-state transformation and its exact scope."""

import unittest
from dataclasses import replace

from experiments.hcsn_regeneration_content_20261031 import policy, policy_audit
from experiments.hcsn_validation_r12_20261031.value import audit, calibration
from experiments.hcsn_validation_r12_20261031.value.tests import Fixture, support
from .guard import TailStop, trajectory_dominance
from .dominance import all_history_dominance


class Schedule:
    def __init__(self, actions):
        self.actions, self.slots = actions, []

    def choose(self, model, state, config):
        self.slots.append(state.slot)
        return self.actions[state.slot], {}


class Validation(unittest.TestCase):
    def setUp(self):
        self.model = Fixture()
        self.config = policy.Config("r13_development_only", ("A", "B", "A"),
                                    (.8, 1.3, .9), .67, .79, .039, .007, budget=2)

    def execute(self, control, label=0, outcomes=(0, 0, 0)):
        return policy_audit.execute(self.model, self.config, support, control,
               policy_audit.World("fixture", label, outcomes, self.config, support))

    def test_skip_tail_preserves_real_content_and_saves_exact_fee(self):
        base = Schedule(("READ", "SKIP", "SKIP", "STOP"))
        guarded = TailStop(base)
        for outcomes in ((0, 1, 0), (1, 0, 1)):
            for label in (0, 1):
                a, b = self.execute(base, label, outcomes), self.execute(guarded, label, outcomes)
                result = trajectory_dominance(a, b, self.config.skip_cost)
                self.assertEqual(result["eliminated_skips"], 2)
                self.assertAlmostEqual(result["saved_task_fee"], .014)
                self.assertEqual([s["executed"] for s in b["steps"]], ["READ", "STOP"])

    def test_root_stop_never_reads_any_raw_or_hidden_label(self):
        guard = TailStop(Schedule(("SKIP", "SKIP", "STOP", "STOP")))
        a = self.execute(guard, 0, (0, 0, 0))
        b = self.execute(guard, 1, (1, 1, 1))
        self.assertEqual(a["steps"], b["steps"])
        self.assertEqual(a["raw_accesses"], [])
        self.assertEqual(a["fee"], 0)
        self.assertEqual(a["prediction"], b["prediction"])

    def test_lookahead_stops_at_first_read_without_executing_it(self):
        base = Schedule(("SKIP", "READ", "SKIP", "STOP"))
        guarded = TailStop(base)
        state = policy.PublicState(self.model.initial(1), 0, 2, 0.)
        before = policy.state_digest(state)
        action, _ = guarded.choose(self.model, state, self.config)
        self.assertEqual(action, "SKIP")
        self.assertEqual(base.slots, [0, 1])
        self.assertEqual(policy.state_digest(state), before)
        self.assertEqual(guarded.counts, dict(actor_calls=1, base_calls=2,
                         simulated_skips=1, replacements=0, max_simulated_skips=1))

    def test_idempotence_and_zero_cost_tails(self):
        base = Schedule(("READ", "SKIP", "SKIP", "STOP"))
        once, twice = TailStop(base), TailStop(TailStop(base))
        self.assertIs(twice.following, base)
        self.assertEqual(self.execute(once)["steps"], self.execute(twice)["steps"])
        self.assertEqual(once.counts, twice.counts)
        self.config = replace(self.config, skip_cost=0.)
        a, b = self.execute(base), self.execute(once)
        self.assertEqual(a["return"], b["return"])
        self.assertEqual(trajectory_dominance(a, b, 0.)["saved_task_fee"], 0.)

    def test_negative_cost_rejected_and_read_policies_unmodified(self):
        guard = TailStop(policy.Lightweight("fixed", 2))
        self.assertEqual(self.execute(guard)["steps"], self.execute(guard.following)["steps"])
        self.config = replace(self.config, skip_cost=-.01)
        with self.assertRaises(ValueError):
            self.execute(guard)

    def test_all_prefix_actual_suffix_values_and_regret_identity(self):
        graph = policy.TeacherGraph(self.model, self.config, support)
        graph.solve()
        fitted, _ = calibration.DeployedRidge.fit_following(
            [graph], policy.Lightweight("fixed", 2), 1., .75)
        controls = [Schedule(("SKIP", "READ", "SKIP", "STOP")), fitted,
                    policy.RidgeValue.fit([graph]), policy.Lightweight("confidence", .8)]
        for base in controls:
            control = TailStop(base)
            result = calibration.evaluate_policy(graph, control)
            original = calibration.evaluate_policy(graph, base)
            check, before, after = all_history_dominance(graph, original, result)
            self.assertEqual(check["histories_checked"], len(graph.nodes))
            self.assertLess(max(check["errors"].values()), 2e-10)
            self.assertEqual(before.keys(), after.keys())
            self.assertGreaterEqual(result["values"][()], original["values"][()]-2e-10)
            for history in ((), (-1,), (0,), (-1, 1)):
                for action in graph.nodes[history]["q"]:
                    check = audit.conditional_execution(graph, control, history, action,
                                result["q"][history][action], support=support)
                    self.assertLess(max(check["errors"].values()), 2e-10)
            self.assertLess(max(result["errors"].values()), 2e-10)

    def test_eight_inherited_policies_have_equal_raw_worlds_and_count_extra_calls(self):
        from .run import controllers, counters, paired
        from experiments.hcsn_regeneration_content_20261031.content_tasks import multimodal_support
        model, controls, _ = controllers("ordinary", 11)
        config = policy.Config("r13_seen_development_only", ("A", "B")*3,
                               (1.,)*6, .70, .75, .035, .004)
        graph = policy.TeacherGraph(model, config, multimodal_support)
        graph.solve()
        retained = []
        measured, checks = paired(graph, controls, 4, 13100001, retained.append)
        self.assertEqual(len(checks), 16)
        self.assertEqual(len(retained), 32)
        self.assertEqual(len(measured), 8)
        for counts in counters(controls).values():
            self.assertGreater(counts["actor_calls"], 0)
            self.assertGreaterEqual(counts["base_calls"], counts["actor_calls"])
        self.assertTrue(all(value["actor_cpu"] > 0 for value in measured.values()))


if __name__ == "__main__":
    unittest.main()
