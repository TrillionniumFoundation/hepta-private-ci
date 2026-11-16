"""Independent finite differences and adjoint identities for actual Adam responses."""

import unittest

import numpy as np

from cell_field_response_v5 import AdamDerivative, HeadDerivative, build_response, compress_response
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


def example(mode, clip=5.0):
    rng = np.random.default_rng(73)
    train = (rng.normal(size=(24, 8)), np.arange(24) % 4)
    probes = tuple((rng.normal(size=(20, 8)), np.arange(20) % 4) for _ in range(2))
    state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=17),
        bindings={"test": "analytic response"}, protocol={"gradient_clip": clip},
        contexts={"train": dataset_digest(*train)})
    for _ in range(12):
        state.advance(*train)
    return state, train, probes


class ResponseTests(unittest.TestCase):
    def test_head_hessian_matches_independent_gradient_differences(self):
        for mode in ("linear", "gated"):
            state, train, _ = example(mode)
            derivative = HeadDerivative(state.head, *train, state.protocol["l2"])
            d = np.random.default_rng(9).normal(size=(state.parameter_count, 3))
            actual = derivative.hvp(d)
            finite = []
            for direction in d.T:
                values = []
                for sign in (1, -1):
                    x = state.vector()
                    x[:state.parameter_count] += sign*1e-5*direction
                    _, g = state.head_from_vector(x).loss_gradients(normalize_features(train[0]), train[1], state.protocol["l2"])
                    values.append(np.concatenate([g[k].ravel() for k in state.names]))
                finite.append((values[0] - values[1]) / 2e-5)
            np.testing.assert_allclose(actual, np.asarray(finite).T, rtol=2e-6, atol=2e-9)
            np.testing.assert_allclose(d.T @ actual, (d.T @ actual).T, rtol=1e-10, atol=1e-10)

    def test_adam_jvp_vjp_and_actual_transition_include_clipping(self):
        for mode in ("linear", "gated"):
            for clip in (5.0, 0.001):
                state, train, _ = example(mode, clip)
                p = state.parameter_count
                derivative = AdamDerivative(state, state.vector(), state.step_count, train)
                rng = np.random.default_rng(23)
                # A fixed v perturbation is a large nonlinear move for the
                # deliberately clipped-gradient case. Scale to its own moments.
                scales = np.r_[np.ones(p), np.maximum(np.abs(state.vector()[p:2*p]), 1e-9),
                               np.maximum(state.vector()[2*p:], 1e-20)]
                d = rng.normal(size=3*p) * scales
                dual = rng.normal(size=3*p)
                np.testing.assert_allclose(dual @ derivative.jvp(d), derivative.vjp(dual) @ d,
                                           rtol=1e-10, atol=1e-10)
                eps = 1e-5
                finite = (state.transition_vector(state.vector()+eps*d, state.step_count, *train)
                          - state.transition_vector(state.vector()-eps*d, state.step_count, *train)) / (2*eps)
                np.testing.assert_allclose(derivative.jvp(d), finite, rtol=5e-5, atol=2e-7)

    def test_h8_impulse_and_sequence_maps_match_actual_rollouts(self):
        for mode in ("linear", "gated"):
            state, train, probes = example(mode)
            origin = state.digest()
            response = build_response(state, train, probes, horizon=8)
            rng = np.random.default_rng(33)
            directions = rng.normal(size=(8, state.parameter_count))
            maps = response.terminal_sequence_maps()
            for single in (True, False):
                actions = directions.copy()
                if single:
                    actions[1:] = 0
                outcomes = []
                for sign in (1, -1):
                    current, rows = state.clone(), []
                    for action in actions:
                        current.advance(*train, intervention=sign*1e-4*.02*action)
                        rows.append([HeadDerivative(current.head, *probe).loss for probe in probes])
                    outcomes.append(np.asarray(rows))
                finite = (outcomes[0]-outcomes[1]) / 2e-4
                if single:
                    expected = np.einsum("kip,p->ki", response.impulse_maps(), actions[0])[1:]
                    np.testing.assert_allclose(expected, finite, rtol=2e-5, atol=2e-9)
                expected_terminal = np.einsum("kip,kp->i", maps, actions)
                np.testing.assert_allclose(expected_terminal, finite[-1], rtol=2e-5, atol=2e-9)
            self.assertEqual(state.digest(), origin)

    def test_compression_preserves_action_responses_with_declared_bound(self):
        state, train, probes = example("gated")
        maps = build_response(state, train, probes).impulse_maps()
        reduced = compress_response(maps, relative_tolerance=1e-6)
        self.assertLessEqual(reduced["rank"], 16)
        rng = np.random.default_rng(2)
        for _ in range(16):
            action = rng.normal(size=state.parameter_count)
            full = maps @ action
            actual = reduced["coefficients"] @ (reduced["basis"].T @ action)
            error = np.linalg.norm((actual-full).ravel())
            self.assertLessEqual(error, reduced["spectral_residual"] * np.linalg.norm(action) + 1e-14)

    def test_nondifferentiable_clip_boundary_fails_explicitly(self):
        state, train, _ = example("linear")
        gradient = HeadDerivative(state.head, *train, state.protocol["l2"]).gradient
        state._protocol["gradient_clip"] = float(np.linalg.norm(gradient))
        with self.assertRaisesRegex(ValueError, "clip boundary"):
            AdamDerivative(state, state.vector(), state.step_count, train)


if __name__ == "__main__":
    unittest.main()
