"""Independent conditional-execution and decision-contract checks."""

import unittest

import numpy as np

from experiments.hcsn_regeneration_content_20261031 import policy, policy_audit
from . import audit, calibration, run


class Fixture:
    def initial(self, batch):
        return np.zeros((batch, 2))

    def step(self, x, h, dt):
        z = x[:, 1] - x[:, 0] + x[:, 2]
        return np.tanh(np.exp(-.2 * dt) * h + z[:, None] * np.array([[.7, -.3]]))

    def logits(self, h):
        return np.stack([-h[:, 0], h[:, 0]], axis=1)


def support(modality, qa, qb):
    if modality == "A":
        return np.array([[1., 0., 0.], [0., 1., 0.]]), np.array([[qa, 1-qa], [1-qa, qa]])
    return np.array([[0., 0., -1.], [0., 0., 1.]]), np.array([[qb, 1-qb], [1-qb, qb]])


class Validation(unittest.TestCase):
    def setUp(self):
        self.model = Fixture()
        self.config = policy.Config("development_fixture", ("A", "B", "A"), (1., .5, 1.5),
                                    .7, .75, .035, .004, budget=2)
        self.graph = policy.TeacherGraph(self.model, self.config, support)
        self.graph.solve()

    def test_prefix_suffix_expectations_include_past_fee_correction(self):
        following = policy.Lightweight("fixed", 2)
        fitted, _ = calibration.DeployedRidge.fit_following([self.graph], following, 1., .75)
        for control in (following, policy.RidgeValue.fit([self.graph]), fitted):
            result = calibration.evaluate_policy(self.graph, control)
            for history in ((), (0,), (-1,), (1, -1), (-1, 1)):
                for action in self.graph.nodes[history]["q"]:
                    actual = audit.conditional_execution(self.graph, control, history, action,
                                result["q"][history][action], support=support)
                    self.assertLess(max(actual["errors"].values()), 2e-10)
                    self.assertEqual(actual["guard_fallbacks"], 0)

    def test_root_lazy_enumeration_matches_full_world_executor(self):
        control = policy.Lightweight("fixed", 2)
        expected = policy_audit.independent_expectation(self.model, self.config, support, control, self.graph)
        actual = audit.conditional_execution(self.graph, control, (), "READ",
                                             expected["actual_expected_return"], support=support)
        self.assertAlmostEqual(actual["actual_suffix_return"], expected["actual_expected_return"], places=12)
        self.assertLess(actual["complete_worlds"], expected["worlds"])

    def test_no_information_skip_is_strictly_dominated(self):
        fitted, _ = calibration.DeployedRidge.fit_following([self.graph], policy.Lightweight("fixed", 2), 1., .75)
        for node in self.graph.nodes.values():
            state = node["state"]
            action, scores = fitted.choose(self.model, state, self.config)
            if not state.budget or state.slot == len(self.config.dts) - 1:
                self.assertEqual(scores["SKIP"], -self.config.skip_cost)
                self.assertNotEqual(action, "SKIP")

    def test_existing_causal_and_invalid_action_contracts(self):
        result = policy_audit.contract_checks(self.model, self.config, support)
        self.assertTrue(result["hidden_label_invariance"])
        self.assertTrue(result["unread_future_invariance"])
        self.assertTrue(result["invalid_attempt_fee_charged"])

    def test_original_manifest_and_all_candidate_identities(self):
        result = run.upstream()
        self.assertEqual(result["candidate_files_verified"], 60)
        self.assertGreater(result["source_files_verified"], 10)


if __name__ == "__main__":
    unittest.main()
