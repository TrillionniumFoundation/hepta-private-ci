"""Mechanism checks before the immutable experiment, independent of its outcome."""

import unittest
import numpy as np

from tools.hcsn.round8_20261031.value_calibration import finite
from tools.hcsn.round8_20261031.value_calibration.head import CalibratedHead
from .head import CostFactoredHead, PreservedNominalHead
from .protocol import contracts


class ValueMechanisms(unittest.TestCase):
    def test_exact_cost_decoder_and_stop(self):
        x = np.asarray([finite.task.features(finite.task.State(p, remaining_budget=p.budget))
                        for p in contracts("blind")])
        head = CostFactoredHead(np.zeros(18), np.ones(18), np.zeros((18, 2)), np.zeros(2),
                                np.zeros((2, 3)), np.array([.1, .2, .3]))
        quality = abs(2 * x[:, 0] - 1)
        stop = quality - x[:, 16] - finite.COMPUTE
        expected = quality[:, None] + np.array([.1, .2, .3, 0.]) - x[:, 13:17] - finite.COMPUTE
        np.testing.assert_allclose(head.predict(x, stop), expected, atol=1e-15)
        changed = x.copy(); changed[:, 13] += .123
        delta = head.predict(changed, stop) - head.predict(x, stop)
        np.testing.assert_allclose(delta, np.tile([-.123, 0, 0, 0], (len(x), 1)), atol=1e-15)

    def test_router_executes_both_domains(self):
        args = (np.zeros(18), np.ones(18), np.zeros((18, 2)), np.zeros(2), np.zeros((2, 3)))
        old = CalibratedHead(*args, np.array([.2, .4, .6]))
        new = CostFactoredHead(*args, np.array([.1, .2, .3]))
        x = np.ones((2, 3, 18)); x[1, :, 0] = .6
        stop = np.zeros((2, 3))
        routed = PreservedNominalHead(old, new, x[:1, 0])
        q = routed.predict(x, stop)
        np.testing.assert_array_equal(q[0], old.predict(x[0], stop[0]))
        np.testing.assert_array_equal(q[1], new.predict(x[1], stop[1]))
        np.testing.assert_array_equal(routed.predict(x[1, 0], stop[1, 0]), q[1, 0])

    def test_task_costs_and_deadline_against_execution(self):
        for p in contracts("blind"):
            graph = finite.build_graph([p])
            for s in graph["states"]:
                for a in finite.task.legal_actions(s):
                    expected = sum(m * r for m, _, r in finite.execution_branches(s, a))
                    feature = finite.task.features(s)
                    value = (abs(2 * s.posterior - 1) if a == "STOP" else 0.) - feature[13 + finite.ACTIONS.index(a)]
                    self.assertAlmostEqual(expected, value, places=12)
                if s.remaining_ticks == 1:
                    self.assertEqual(finite.task.legal_actions(s), ("STOP",))


if __name__ == "__main__":
    unittest.main()
