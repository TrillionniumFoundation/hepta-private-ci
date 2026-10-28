"""Nontrivial mathematical checks for the declared finite-window experiment."""

from dataclasses import replace
import json
import unittest

import numpy as np

from experiments.first_passage_cell.kernels import (
    first_passage,
    first_passage_gradients,
)
from experiments.continuous_boundary_flow.math_model import (
    TaskSpec,
    action_values,
    build_model,
    evaluate_policy,
    occupation_time,
    readout,
    sample_policy,
    sample_step,
    solve_dp,
)
from experiments.continuous_boundary_flow.oracle import (
    comparison_report,
    finite_difference_reference,
    independent_integrals,
)


class MathematicalContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_model(n_grid=96)
        cls.dp = solve_dp(cls.model)

    def test_conservative_killed_kernel_keeps_real_failure_mass(self):
        m = self.model
        np.testing.assert_allclose(m.killed.sum(axis=1), m.S, atol=2e-13)
        np.testing.assert_allclose(m.transition.sum(axis=1), 1, atol=2e-13)
        np.testing.assert_allclose(m.F + m.S, 1, atol=2e-13)
        self.assertGreaterEqual(m.killed.min(), 0)
        self.assertGreater(float(m.F[0]), 0.9)
        self.assertLess(float(m.killed[0].sum()), 0.1)

    def test_all_five_existing_kernels_against_independent_integrals(self):
        for mu in [-0.3, 0.0, 0.2]:
            spec = replace(self.model.spec, mu=mu)
            for x in [0.04, 0.3, 1.0]:
                ref = independent_integrals(spec, x)
                actual = first_passage(x, mu, spec.sigma, spec.dt, spec.discount)
                for field in ["F", "S", "f", "H"]:
                    self.assertAlmostEqual(
                        float(actual[field]), float(ref[field]), delta=3e-10
                    )
                self.assertAlmostEqual(
                    float(occupation_time(x, spec)), ref["occupation"], delta=3e-10
                )
                self.assertLess(ref["mass_error"], 1e-10)

    def test_zero_discount_occupation_limit(self):
        spec = replace(self.model.spec, discount=0)
        for x in [0.025, 0.3, 1.0]:
            ref = independent_integrals(spec, x)
            self.assertAlmostEqual(
                float(occupation_time(x, spec)), ref["occupation"], delta=2e-10
            )
        tiny = replace(spec, discount=1e-8)
        self.assertAlmostEqual(
            float(occupation_time(0.3, tiny)),
            float(occupation_time(0.3, spec)),
            delta=1e-8,
        )

    def test_analytic_first_passage_gradients_finite_difference(self):
        args = dict(x=0.37, mu=-0.22, sigma=0.42, horizon=0.5, discount=0.06)
        gradients = first_passage_gradients(**args)
        for parameter in args:
            hi, lo = args.copy(), args.copy()
            eps = 2e-6
            hi[parameter] += eps
            lo[parameter] -= eps
            high, low = first_passage(**hi), first_passage(**lo)
            for field in ["F", "S", "f", "H"]:
                fd = float((high[field] - low[field]) / (2 * eps))
                self.assertAlmostEqual(
                    float(gradients[field][parameter]), fd, delta=2e-7 * max(1, abs(fd))
                )

    def test_reset_continuation_is_not_absorbing(self):
        m = self.model
        continuation = 2 + m.x**2
        wait, repair, stop = action_values(m, continuation)
        absorbing = m.reward + m.gamma * (m.killed @ continuation)
        reinjected = m.gamma * m.F * (m.failure_distribution @ continuation)
        np.testing.assert_allclose(wait - absorbing, reinjected, atol=2e-14)
        self.assertGreater(float(reinjected[0]), 1)
        np.testing.assert_allclose(
            repair, -m.spec.maintenance_cost + m.maintenance_distribution @ wait
        )
        np.testing.assert_array_equal(stop, np.zeros(m.n_states))

    def test_task_channels_reconstruct_continuation_action_value(self):
        m = self.model
        continuation = self.dp["value"][5]
        features = readout(m, continuation, boundary=0.6)
        wait, _, _ = action_values(m, continuation)
        np.testing.assert_allclose(features["C"] - features["P"], wait, atol=1e-14)
        np.testing.assert_allclose(features["margin"], m.x - 0.6)
        altered = readout(m, np.zeros_like(continuation), boundary=0.6)
        self.assertGreater(np.max(np.abs(features["C"] - altered["C"])), 1)
        np.testing.assert_array_equal(features["P"], altered["P"])

    def test_free_boundary_has_value_matching_and_horizon_dependence(self):
        boundaries = self.dp["boundaries"]
        self.assertTrue(all(item["threshold_shape"] for item in boundaries))
        self.assertTrue(
            all(abs(item["value_matching_residual"]) < 1e-12 for item in boundaries)
        )
        self.assertGreater(boundaries[-1]["boundary"], boundaries[0]["boundary"] + 0.05)
        self.assertGreater(boundaries[0]["boundary"], 0.1)

    def test_boundary_responds_to_same_objective_cost(self):
        expensive = build_model(
            replace(self.model.spec, maintenance_cost=0.55), n_grid=96
        )
        candidate = solve_dp(expensive)
        self.assertLess(
            candidate["boundaries"][-1]["boundary"],
            self.dp["boundaries"][-1]["boundary"],
        )
        self.assertLess(candidate["initial_value"], self.dp["initial_value"])

    def test_probability_flow_matches_backward_bellman_and_cost_ledger(self):
        result = evaluate_policy(self.model, self.dp["policy"])
        self.assertAlmostEqual(result["utility"], self.dp["initial_value"], places=12)
        self.assertLess(result["flow_backward_residual"], 2e-12)
        self.assertLess(result["mass_error"], 2e-12)
        self.assertAlmostEqual(
            result["utility"],
            result["production"] - result["failure_cost"] - result["maintenance_cost"],
            places=14,
        )
        self.assertGreater(result["failures"], 0)
        self.assertGreater(result["maintenance"], 0)

    def test_fractional_policy_flows_probabilities_not_mean_state(self):
        m = self.model
        policy = np.broadcast_to([0.55, 0.3, 0.15], (m.spec.horizon, m.n_states, 3))
        result = evaluate_policy(m, policy)
        self.assertLess(result["flow_backward_residual"], 1e-12)
        self.assertLess(result["mass_error"], 1e-12)
        self.assertAlmostEqual(
            result["stopped_probability"], 1 - 0.85**m.spec.horizon, places=12
        )
        self.assertLess(result["utility"], self.dp["initial_value"] + 1e-12)

    def test_stop_is_absorbing_and_can_be_optimal(self):
        m = self.model
        stop = np.broadcast_to([0, 0, 1], (m.spec.horizon, m.n_states, 3))
        flow = evaluate_policy(m, stop)
        events = sample_policy(m, stop, n_paths=128, seed=2, record_trace=True)
        self.assertEqual(flow["utility"], 0)
        self.assertEqual(flow["stopped_probability"], 1)
        self.assertEqual(events["utility"], 0)
        self.assertEqual(len(events["trace"]), 1)
        self.assertTrue(np.all(events["final_states"] == -1))
        hard = build_model(
            replace(
                m.spec,
                mu=-0.8,
                failure_cost=7,
                maintenance_cost=6,
                production_rate=0.1,
                initial=0.15,
                horizon=4,
            ),
            n_grid=64,
        )
        hard_dp = solve_dp(hard)
        self.assertAlmostEqual(hard_dp["initial_value"], 0, places=12)
        self.assertEqual(hard_dp["boundaries"][-1]["boundary"], 0.0)

    def test_event_sampler_agrees_with_flow(self):
        model = self.model
        policy = np.broadcast_to(
            [0.8, 0.15, 0.05], (model.spec.horizon, model.n_states, 3)
        )
        flow = evaluate_policy(model, policy)
        events = sample_policy(model, policy, n_paths=16000, seed=20261028)
        self.assertLess(
            abs(events["utility"] - flow["utility"]),
            5 * events["standard_error"] + 0.005,
        )
        self.assertAlmostEqual(
            events["stopped_probability"], flow["stopped_probability"], delta=0.015
        )

    def test_conditional_event_time_and_endpoint_calibration(self):
        m = self.model
        index = int(np.argmin(abs(m.x - 0.3)))
        n = 24000
        trace = sample_step(
            m, np.full(n, index), np.zeros(n, dtype=int), np.random.default_rng(87)
        )
        failed = trace["failed"]
        empirical_H = np.zeros(n)
        empirical_H[failed] = np.exp(
            -m.spec.discount * np.asarray(trace["tau_hit"][failed], dtype=float)
        )
        self.assertAlmostEqual(failed.mean(), float(m.F[index]), delta=0.02)
        self.assertAlmostEqual(empirical_H.mean(), float(m.H[index]), delta=0.02)
        surviving_bins = trace["next_state_idx"][~failed]
        empirical = np.bincount(surviving_bins, minlength=m.n_states) / len(
            surviving_bins
        )
        cdf_error = np.max(
            np.abs(np.cumsum(empirical) - np.cumsum(m.killed[index] / m.S[index]))
        )
        self.assertLess(cdf_error, 0.025)

    def test_trace_recomputes_episode_reward_without_aggregates(self):
        m = self.model
        policy = np.broadcast_to([0.55, 0.35, 0.1], (m.spec.horizon, m.n_states, 3))
        result = sample_policy(m, policy, n_paths=100, seed=123, record_trace=True)
        recomputed = np.zeros(100)
        for trace in result["trace"]:
            active = trace["active_time"]
            failure = trace["failed"]
            produced = -np.expm1(-m.spec.discount * active) / m.spec.discount
            cost = np.zeros(len(active))
            cost[failure] = m.spec.failure_cost * np.exp(
                -m.spec.discount * np.asarray(trace["tau_hit"][failure], dtype=float)
            )
            reward = (
                m.spec.production_rate * produced
                - cost
                - m.spec.maintenance_cost * (trace["action"] == 1)
            )
            recomputed[trace["path_ids"]] += (
                np.exp(-m.spec.discount * m.spec.dt * trace["elapsed"]) * reward
            )
            self.assertTrue(all(t is None for t in trace["tau_hit"][~failure]))
            self.assertTrue(
                all(p is None for p in trace["F_after_action"][trace["action"] == 2])
            )
            json.dumps(
                {
                    key: value.tolist() if isinstance(value, np.ndarray) else value
                    for key, value in trace.items()
                },
                allow_nan=False,
            )
        np.testing.assert_allclose(recomputed, result["returns"], atol=2e-14)

    def test_common_random_slots_survive_different_actions_and_stops(self):
        m = self.model
        wait = np.broadcast_to([1, 0, 0], (m.spec.horizon, m.n_states, 3))
        mixed = np.broadcast_to([0.4, 0.4, 0.2], (m.spec.horizon, m.n_states, 3))
        a = sample_policy(m, wait, n_paths=80, seed=19, record_trace=True)
        b = sample_policy(m, mixed, n_paths=80, seed=19, record_trace=True)
        for trace_a, trace_b in zip(a["trace"], b["trace"]):
            ids = trace_b["path_ids"]
            np.testing.assert_array_equal(trace_a["uniforms"][ids], trace_b["uniforms"])
            np.testing.assert_array_equal(
                trace_a["action_uniform"][ids], trace_b["action_uniform"]
            )

    def test_independent_generator_oracle_converges(self):
        coarse = finite_difference_reference(self.model.spec, n_grid=80)
        fine = finite_difference_reference(self.model.spec, n_grid=240)
        target = self.dp["initial_value"]
        self.assertLess(
            abs(fine["initial_value"] - target), abs(coarse["initial_value"] - target)
        )
        self.assertLess(abs(fine["initial_value"] - target), 0.006)
        report = comparison_report(self.model, fine)
        self.assertLess(max(report["kernel_max_abs_errors"].values()), 0.001)
        self.assertLess(
            abs(fine["boundaries"][-1] - self.dp["boundaries"][-1]["boundary"]), 0.02
        )

    def test_grid_and_upper_domain_convergence(self):
        coarse = solve_dp(build_model(n_grid=48))["initial_value"]
        fine_model = build_model(n_grid=192)
        fine = solve_dp(fine_model)["initial_value"]
        wide = solve_dp(build_model(n_grid=288, x_max=7.2))["initial_value"]
        self.assertLess(abs(fine - self.dp["initial_value"]), 0.008)
        self.assertLess(abs(fine - wide), 0.001)
        self.assertLess(abs(fine - coarse), 0.02)
        self.assertLess(
            evaluate_policy(fine_model, solve_dp(fine_model)["policy"])[
                "upper_tail_visits"
            ],
            0.001,
        )


if __name__ == "__main__":
    unittest.main()
