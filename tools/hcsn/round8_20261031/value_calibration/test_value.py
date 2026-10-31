"""Independent likelihood, full-return and actual optimizer derivative checks."""

from dataclasses import replace
import unittest

import numpy as np

from . import finite
from .head import objective


class ValueCalibrationTests(unittest.TestCase):
    def test_gradient_with_legal_action_gaps_and_mask(self):
        rng = np.random.default_rng(811)
        x = rng.normal(size=(9, 5))
        target = rng.normal(size=(9, 3))
        mask = rng.random((9, 3)) > .3
        weights = rng.random(9)
        hidden = 4
        parameters = rng.normal(0, .2, size=5 * hidden + hidden + hidden * 3 + 3)
        direction = rng.normal(size=len(parameters))
        direction /= np.linalg.norm(direction)
        _, gradient = objective(parameters, x, target, mask, weights, hidden)
        h = 1e-5
        plus = objective(parameters + h * direction, x, target, mask, weights, hidden)[0]
        minus = objective(parameters - h * direction, x, target, mask, weights, hidden)[0]
        self.assertLess(abs((plus - minus) / (2 * h) - gradient @ direction), 1e-8)

    def test_independent_worlds_and_public_oracle_agree(self):
        configs = finite.configurations()
        graph = finite.build_graph(configs)
        independent = finite.build_graph(configs, independent=True)
        self.assertEqual(set(graph["states"]), set(independent["states"]))
        def distribution(g, index, action):
            groups = {}
            for p, j, r in g["edges"][index, action]:
                key = g["states"][j] if j >= 0 else None
                old = groups.get(key, (0., 0.))
                groups[key] = (old[0] + p, old[1] + p * r)
            return groups
        for i, state in enumerate(graph["states"]):
            j = independent["ids"][state]
            for action in np.flatnonzero(graph["legal"][i]):
                a, b = distribution(graph, i, action), distribution(independent, j, action)
                self.assertEqual(a.keys(), b.keys())
                for successor in a:
                    np.testing.assert_allclose(a[successor], b[successor], atol=1e-13, rtol=0)

    def test_deadline_cost_and_cell_future_are_retained(self):
        p = replace(finite.task.TaskParameters(), horizon=2, budget=0)
        graph = finite.build_graph([p])
        independent = finite.build_graph([p], independent=True)
        # Deliberately nontrivial switching and state-dependent event costs.
        matrix = np.broadcast_to([[.7, .3], [.2, .8]], (len(graph["states"]), 2, 2)).copy()
        events = np.broadcast_to([.3, .0], (len(graph["states"]), 2)).copy()
        q, values = finite.targets(graph, matrix, events)
        alignment = [independent["ids"][s] for s in graph["states"]]
        reference = finite.reference(independent, matrix, events)
        np.testing.assert_allclose(values, reference[alignment], atol=1e-13, rtol=0)
        start = graph["starts"][0]
        self.assertEqual(q[start].argmax(-1).tolist(), [3, 3])
        self.assertTrue(np.all(q[start, :, 1] < q[start, :, 3]))
        self.assertAlmostEqual(float(q[start, 0, 3]), -p.stop_cost - p.latency_cost - finite.COMPUTE)


if __name__ == "__main__":
    unittest.main()
