"""Independent closed-form composition and impossible-statistic controls."""
import copy
from types import SimpleNamespace
import unittest

import numpy as np

from profile_io import canonical, sha
from peer_equations import COMMON_SCHEMA, OBJECTIVE, SHARED_FIELDS, contribute, solve_common


class PeerEquationTests(unittest.TestCase):
    def setUp(self):
        layout = [{"name": "matrix_fixture", "flat_index": i, "scale": 1.,
                   "shape": [2], "dtype": "float64"} for i in range(2)]
        self.common = {"schema": COMMON_SCHEMA, "round": "synthetic-algebra-fixture",
            "roster": ["fixture_a", "fixture_b"], "profile_sha256": "1" * 64,
            "candidate_sha256": "2" * 64, "source_binding_sha256": "3" * 64,
            "runtime": {"fixture": "algebra only; no physical model or participant"},
            "linearization": {"parent_state_sha256": "4" * 64,
                "coordinate_sha256": sha(canonical(layout)), "coordinate_layout": layout,
                "objective_state": "known matrix fixture", "output": "matrix product",
                "derivative": "exact given matrix", "second_order_autograd": False},
            "objective": OBJECTIVE, "ridge": .25}
        base = np.array([.1, .2, .3])
        jacobian = np.array([[1., 2.], [0., 1.], [2., -1.]])
        target = base + [1., -2., .5]
        self.rows = []
        for node, indices, weights in (("fixture_a", [0, 1], [1., 2.]), ("fixture_b", [2], [.5])):
            metadata = copy.deepcopy(self.common["linearization"])
            metadata["linearization_sha256"] = sha(canonical({"fixture_node": node}))
            linearization = SimpleNamespace(metadata=metadata, jacobian=jacobian[indices], base_output=base[indices])
            self.rows.append(contribute(self.common, linearization, target[indices], node=node,
                batch_sha256=sha(canonical({"fixture_rows": indices})), observation_weights=weights))

    def test_known_weighted_solution_and_arrival_order(self):
        result = solve_common(self.common, self.rows)
        # Exact independent inverse of [[3.25,1],[1,6.75]] @ alpha = [1.5,-2.25].
        expected = np.array([12.375, -8.8125]) / 20.9375
        np.testing.assert_allclose(result["delta"], expected, rtol=1e-12, atol=1e-12)
        self.assertEqual(result["observation_count"], 3)
        self.assertEqual(result["ridge_applications"], 1)
        self.assertEqual(result, solve_common(self.common, list(reversed(self.rows))))

    def test_incompatible_replayed_and_impossible_contributions(self):
        with self.assertRaises(ValueError):
            solve_common(self.common, [self.rows[0], self.rows[0]])
        changed = copy.deepcopy(self.common)
        changed["runtime"]["fixture"] = "different runtime"
        with self.assertRaises(ValueError):
            solve_common(changed, self.rows)
        changed = copy.deepcopy(self.rows)
        changed[1]["body"].update(gram=np.eye(2).tolist(), moment=[0., 0.], residual_square=0.)
        changed[1]["sha256"] = sha(canonical(changed[1]["body"]))
        with self.assertRaises(ValueError):
            solve_common(self.common, changed)
        changed = copy.deepcopy(self.rows)
        changed[0]["body"]["moment"][0] += 1.
        with self.assertRaises(ValueError):
            solve_common(self.common, changed)


if __name__ == "__main__":
    unittest.main()
