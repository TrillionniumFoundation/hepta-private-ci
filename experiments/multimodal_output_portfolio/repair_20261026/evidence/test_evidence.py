"""Analytic, synthetic-training and existing-source regression tests; no new cohort."""

import hashlib
import json
from pathlib import Path
import unittest

import numpy as np

from .dynamic import plan
from .joint import JointObservationLaw, PairObservation, arrived_receipts
from .prior import JointPrior


class EvidenceTests(unittest.TestCase):
    def test_actual_historical_alias_support_and_unidentified_couplings(self):
        source = Path(__file__).resolve().parents[2] / "advance_20261026/control/AUDIO_LIKELIHOOD.json"
        raw = source.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "1fff72a9ad1470b1ead327a82811642f0b14c45ca61f454b2f60292e246d5946")
        record = json.loads(raw)
        old = np.asarray(record["pair_observation_by_target"])
        fixed = JointObservationLaw.from_components(record["digit_observation_by_target"])
        for digit in range(10):
            impossible = sum(old[o, 11 * digit] for o in range(100) if o // 10 != o % 10)
            self.assertGreater(impossible, .23)
            self.assertEqual(float(fixed.likelihood[10:, 11 * digit].sum()), 0.)
        with self.assertRaisesRegex(ValueError, "Unidentified"):
            fixed.forecast(np.full(100, .01))
        restored = JointObservationLaw.load(json.loads(json.dumps(fixed.export(), allow_nan=False)))
        np.testing.assert_array_equal(fixed.known_targets, restored.known_targets)
        np.testing.assert_allclose(fixed.likelihood, restored.likelihood, equal_nan=True)

    def test_joint_fit_keeps_distinct_event_dependence_and_reuse(self):
        rows = [PairObservation("a", "s1", 1, ("left-a", "right-a"), (0, 0)),
                PairObservation("b", "s2", 1, ("left-b", "right-b"), (1, 1)),
                PairObservation("repeated-view", "s1", 1, ("left-a", "right-a"), (0, 0))]
        law = JointObservationLaw.fit_paired(rows, alpha=0.)
        self.assertEqual(law.provenance["physical_pairs"], 2)
        self.assertEqual(law.likelihood[10, 1], .5)
        self.assertEqual(law.likelihood[21, 1], .5)
        self.assertEqual(law.likelihood[11, 1], 0.)
        with self.assertRaisesRegex(ValueError, "reserved"):
            JointObservationLaw.fit_paired(rows, alpha=0., excluded_groups=["s1"])
        conflict = PairObservation("conflict", "s1", 1, ("left-a", "right-a"), (1, 0))
        with self.assertRaisesRegex(ValueError, "conflicting"):
            JointObservationLaw.fit_paired([*rows, conflict], alpha=0.)

    def test_arrival_alias_is_counted_once_and_not_exposed_before_arrival(self):
        single = np.eye(10)
        single[:, 0] = 0.; single[0, 0], single[1, 0] = .8, .2
        single[:, 1] = 0.; single[0, 1], single[1, 1] = .1, .9
        law = JointObservationLaw.from_components(single)
        prior = np.zeros(100); prior[[0, 11]] = .5
        session = law.start_filter(prior)
        self.assertEqual(session.posterior(), {0: .5, 11: .5})
        receipts = arrived_receipts(("opaque-a", "opaque-a"), (0, 0))
        result = session.update(receipts)
        self.assertAlmostEqual(result[0], 8 / 9)
        self.assertEqual(session.update([*receipts, *receipts]), result)
        before = session.history
        with self.assertRaises(ValueError):
            session.update(arrived_receipts(("opaque-a", "opaque-a"), (0, 1)))
        self.assertEqual(session.history, before)

    def test_joint_event_law_executes_existing_dynamic_terminal_rule(self):
        # Synthetic exact oracle: acquiring one aliased observation identifies T.
        law = JointObservationLaw.from_components(np.eye(10))
        prior = np.zeros(100); prior[[0, 11]] = .5
        endpoints = np.eye(100)
        result = plan(endpoints, endpoints, prior, law, acquire_cost=.01,
                      future_resource_rejection=0., emit_cost=.01, minimum_confidence=0.)
        self.assertEqual(result["action"], 101)
        self.assertAlmostEqual(result["moment"], np.exp(-2 * (1 - .02)))
        self.assertAlmostEqual(result["acquire_success_probability"], 1.)
        denied = plan(endpoints, endpoints, prior, law, acquire_cost=.01,
                      future_resource_rejection=1., emit_cost=.01, minimum_confidence=0.)
        self.assertNotEqual(denied["action"], 101)

    def test_joint_gradient_against_independent_finite_differences(self):
        rng = np.random.default_rng(8)
        parameters = {"w1": rng.normal(0, .2, (3, 2)), "b1": rng.normal(0, .2, 3),
                      "w2": rng.normal(0, .2, (100, 3)), "b2": rng.normal(0, .2, 100)}
        model = JointPrior([0., 0.], [1., 1.], parameters)
        x, y, w = np.array([[.1, .5], [-.4, .2]]), np.array([1, 11]), np.array([.4, .6])
        _, gradient = model.loss_and_gradient(x, y, w, .01)
        for key, index in (("w1", (1, 0)), ("w2", (11, 1)), ("b1", (0,)), ("b2", (1,))):
            old = model.parameters[key][index]
            model.parameters[key][index] = old + 1e-6
            plus = model.loss_and_gradient(x, y, w, .01)[0]
            model.parameters[key][index] = old - 1e-6
            minus = model.loss_and_gradient(x, y, w, .01)[0]
            model.parameters[key][index] = old
            self.assertAlmostEqual((plus - minus) / 2e-6, gradient[key][index], places=7)

    def test_joint_forecast_connects_to_explicit_owner_cost_branches(self):
        from ..control.execution import Outcome, attach_observations
        law = JointObservationLaw.from_components(np.eye(10))
        prior = np.zeros(100); prior[[0, 11]] = .5
        forecast = law.forecast(prior)
        owner = {event["event"]: [Outcome(1., .1, (1,), "owner-refused",
                                         utility=-1., strict_success=0., resource_rejected=True)]
                 for event in forecast}
        outcomes = attach_observations(forecast, owner)
        self.assertAlmostEqual(sum(o.probability for o in outcomes), 1.)
        self.assertTrue(all(o.resource_rejected for o in outcomes))
        with self.assertRaisesRegex(ValueError, "Every supported"):
            attach_observations(forecast, {})

    def test_train_full_joint_dependence_with_identical_marginals(self):
        # Constructed mechanism test, not a held-out source efficacy experiment.
        features = np.repeat([[-1.], [1.]], 40, axis=0)
        targets = np.array([0, 11] * 20 + [1, 10] * 20)
        groups = [f"synthetic-{i}" for i in range(80)]
        model = JointPrior.fit(features, targets, groups, steps=180, learning_rate=.04, seed=17, hidden=4)
        q = model.predict([[-1.], [1.]])
        self.assertGreater(float(q[0, [0, 11]].sum()), .97)
        self.assertGreater(float(q[1, [1, 10]].sum()), .97)
        np.testing.assert_allclose(q.sum(1), 1., atol=1e-12)
        restored = JointPrior.load(json.loads(json.dumps(model.export(), allow_nan=False)))
        np.testing.assert_array_equal(q, restored.predict([[-1.], [1.]]))
        self.assertLess(model.provenance["final_objective"], 1.)


if __name__ == "__main__":
    unittest.main()
