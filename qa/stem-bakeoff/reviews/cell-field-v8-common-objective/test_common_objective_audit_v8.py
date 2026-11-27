"""Independent recurrence checks on a synthetic known linear system."""

import unittest
import numpy as np
from audit_common_objective_v8 import forward_coefficients


class ForwardAuditTests(unittest.TestCase):
    def test_forward_maps_equal_direct_state_and_mealy_rollouts(self):
        rng, h, p = np.random.default_rng(3810), 5, 3
        gradients = rng.normal(size=(h+1, 8, p))
        matrices = [.7*np.eye(3*p)+rng.normal(size=(3*p, 3*p))*.03 for _ in range(h)]
        maps = forward_coefficients(gradients, matrices)
        actions, state, retained = rng.normal(size=(h, p)), np.zeros(3*p), np.zeros(2)
        for k, matrix in enumerate(matrices):
            state = matrix @ state
            state[:p] += .02*actions[k]
            observation = np.hstack((gradients[k].reshape(2, 4, p).mean(axis=1), np.zeros((2, 2*p))))
            reconstructed = np.linalg.lstsq(observation, retained, rcond=1e-10)[0]
            reconstructed = matrix @ reconstructed
            reconstructed[:p] += .02*actions[k]
            reduced_output = gradients[k+1] @ reconstructed[:p]
            retained = reduced_output.reshape(2, 4).mean(axis=1)
        np.testing.assert_allclose(np.einsum("kqp,kp->q", maps["full"], actions), gradients[-1] @ state[:p], atol=1e-14)
        np.testing.assert_allclose(np.einsum("kqp,kp->q", maps["loss2"], actions), reduced_output, atol=1e-14)
        np.testing.assert_array_equal(maps["full"][-1], .02*gradients[-1])
        np.testing.assert_array_equal(maps["loss2"][-1], .02*gradients[-1])

    def test_future_field_preserves_arbitrary_initial_state_and_every_action(self):
        rng, h, p = np.random.default_rng(892), 4, 5
        gradients = rng.normal(size=(h+1, 8, p))
        matrices = [.8*np.eye(3*p)+rng.normal(size=(3*p, 3*p))*.01 for _ in range(h)]
        maps = forward_coefficients(gradients, matrices)
        state, actions = rng.normal(size=3*p), rng.normal(size=(h, p))
        retained = maps["field_initial"] @ state
        np.testing.assert_allclose(retained[:8], gradients[0] @ state[:p], atol=1e-14)
        for k, matrix in enumerate(matrices):
            state = matrix @ state
            state[:p] += .02*actions[k]
            retained = retained[8:]+maps["field_inputs"][k] @ actions[k]
            np.testing.assert_allclose(retained[:8], gradients[k+1] @ state[:p], atol=1e-14)


if __name__ == "__main__":
    unittest.main()
