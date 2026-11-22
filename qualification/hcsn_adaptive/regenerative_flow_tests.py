"""Brownian renewal reference versus the actual finite population process.

Run: python -m unittest qualification.hcsn_adaptive.regenerative_flow_tests -v

These synthetic fixed-coefficient checks call BatchedFlow.step_physical and its
generator; they do not reimplement finite-volume rates. The analytic process
has an exact reset point and deterministic refractory delay. The finite process
has interpolated reset, spatial upwinding, an absorbing upper truncation and
Erlang phases. Agreement is therefore tested under explicit refinement/error
bounds, not asserted to machine precision. No moving-boundary or network claim.
"""

from dataclasses import replace
import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import gammainc
import torch

from .batched_flow import BatchedFlow, FlowConfig
from .finite_control import continuation_value
from .flow_semantics import FlowSemantics
from .regenerative_reference import RegenerativeReference


DRIFT, SIGMA, RESET, DELAY = -0.7, 0.6, 0.5, 0.3
DISCOUNT, RUNNING_REWARD, EVENT_PAYOFF = 0.8, 0.6, -0.2
HORIZON, ACTIVE_WEIGHT = 2.0, 0.6
REFINEMENTS = ((16, 4), (32, 8), (64, 16))
QUANTITIES = (
    "expected_count",
    "first_risk",
    "discounted_first",
    "refractory_mass",
    "active_time",
    "initial_continuation_value",
)


def brownian_targets(active_weight, horizon):
    """Initial locked mass waits a full delay; it has no new event at time zero.

    With N(t)=E[count through t], locked mass is N(t)-N(t-delay).
    Its time integral is integral_{max(0,t-delay)}^t N(s) ds, so the
    complementary occupation below includes all subsequent refractory cycles.
    """
    model = RegenerativeReference(DRIFT, SIGMA, RESET, DELAY)
    value = model.value(RESET, DISCOUNT, RUNNING_REWARD, EVENT_PAYOFF)

    def count(time):
        return model.summary(RESET, max(0.0, time))["expected_events"]

    def active_start(time):
        occupied = (
            time
            - quad(count, max(0.0, time - DELAY), time, epsabs=2e-11, epsrel=2e-11)[0]
        )
        return np.array(
            (
                count(time),
                model.first_hit_cdf(RESET, time),
                model.discounted_hit(RESET, DISCOUNT, horizon=time),
                count(time) - count(time - DELAY),
                occupied,
                value,
            )
        )

    active = active_start(horizon)
    if horizon < DELAY:
        locked = np.array(
            (0.0, 0.0, 0.0, 1.0, 0.0, math.exp(-DISCOUNT * DELAY) * value)
        )
    else:
        locked = active_start(horizon - DELAY)
        locked[2] *= math.exp(-DISCOUNT * DELAY)
        locked[5] *= math.exp(-DISCOUNT * DELAY)
    return active_weight * active + (1.0 - active_weight) * locked


def finite_observation(bins, stages, active_weight, horizon):
    """Exercise production propagation; zero input and no writes isolate physics."""
    flow = BatchedFlow(
        FlowConfig(
            input_size=1,
            content_size=1,
            bins=bins,
            stages=stages,
            extent=3.0,
            sigma=SIGMA,
            base_drift=DRIFT,
            drift_scale=0.0,
            reset_margin=RESET,
            refractory=DELAY,
            discount=DISCOUNT,
            upper_mode="absorbing",
        )
    )
    inputs = torch.zeros(1, 1, dtype=torch.float64)
    state = flow.initial_state(1, like=inputs)
    density = state.density.clone()
    density[:, 0] *= active_weight
    density[:, 0, bins] = 1.0 - active_weight
    state = replace(state, density=density)
    with torch.no_grad():
        _, updated, diagnostics = flow.step_physical(
            inputs,
            state,
            semantics=FlowSemantics("event_mask"),
            write_mask=[0],
            dt=horizon,
            drift_override=DRIFT,
        )
        observed = diagnostics["observables"]
        generator, event, _ = flow._generator(inputs.new_tensor([DRIFT]))
        active = torch.cat((inputs.new_ones(bins), inputs.new_zeros(stages + 1)))
        # An instantaneous payoff belongs at the event time, through its rate.
        reward = RUNNING_REWARD * active + EVENT_PAYOFF * event[0]
        value = continuation_value(generator[0], reward, DISCOUNT)
        probability = updated.density[0, 0]
        result = np.array(
            (
                observed.expected_event_count.item(),
                observed.first_event_probability.item(),
                observed.discounted_first_event.item(),
                probability[bins : bins + stages].sum().item(),
                observed.occupation_integral.item(),
                (state.density[0, 0] * value).sum().item(),
            )
        )
    return result, {
        "active_mass": probability[:bins].sum().item(),
        "escape_mass": probability[-1].item(),
        "mass_error": diagnostics["mass_error"].item(),
        "jump_events": diagnostics["boundary_jump_hits"].item(),
        "refractory_variance": diagnostics["refractory_variance"],
    }


class RegenerativeFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.old_threads)

    def test_mixed_active_and_locked_population_refines_toward_brownian_reference(self):
        expected = brownian_targets(ACTIVE_WEIGHT, HORIZON)
        relative_errors, first_risk_errors, finest = [], [], None
        for bins, stages in REFINEMENTS:
            with self.subTest(bins=bins, stages=stages):
                actual, diagnostic = finite_observation(
                    bins, stages, ACTIVE_WEIGHT, HORIZON
                )
                self.assertTrue(np.isfinite(actual).all())
                self.assertLess(abs(diagnostic["mass_error"]), 1e-10)
                self.assertEqual(diagnostic["jump_events"], 0.0)
                self.assertLess(diagnostic["escape_mass"], 2e-4)
                self.assertGreater(
                    actual[0], 1.5
                )  # repeat count is not first-hit probability
                self.assertTrue(0 < actual[2] < actual[1] < 1)
                relative_errors.append(
                    float(np.sum(np.abs(actual - expected) / np.abs(expected)))
                )
                first_risk_errors.append(abs(actual[1] - expected[1]))
                finest = actual
        # Spatial and Erlang biases can cancel in one observable, so requiring
        # every individual error to decrease would be unjustified. Use the sum
        # of dimensionless relative errors plus the clean first-risk sequence.
        self.assertLess(relative_errors[-1], 0.75 * relative_errors[0])
        self.assertLess(relative_errors[-1], 0.85 * relative_errors[1])
        for coarse, fine in zip(first_risk_errors, first_risk_errors[1:]):
            self.assertLess(fine, 0.65 * coarse)
        bounds = (0.025, 0.005, 0.004, 0.001, 0.004, 0.0045)
        for name, actual, target, bound in zip(QUANTITIES, finest, expected, bounds):
            with self.subTest(quantity=name):
                self.assertAlmostEqual(actual, target, delta=bound)

    def test_initial_refractory_early_release_is_explicit_and_converges(self):
        horizon = DELAY / 2
        deterministic = brownian_targets(0.0, horizon)
        np.testing.assert_array_equal(deterministic[:5], (0.0, 0.0, 0.0, 1.0, 0.0))
        event_counts, active_masses = [], []
        for bins, stages in REFINEMENTS:
            with self.subTest(bins=bins, stages=stages):
                actual, diagnostic = finite_observation(bins, stages, 0.0, horizon)
                # Independent Gamma/Erlang CDF for the original cohort's release.
                released = float(gammainc(stages, stages * horizon / DELAY))
                outside = diagnostic["active_mass"] + diagnostic["escape_mass"]
                returned_locked = released - outside
                self.assertGreater(actual[1], 0.0)  # include phase-origin first events
                self.assertLessEqual(actual[1], actual[0] + 1e-12)
                self.assertTrue(0 < actual[2] < actual[1])
                self.assertGreaterEqual(returned_locked, -1e-11)
                self.assertLessEqual(returned_locked, actual[1] + 1e-11)
                self.assertLess(abs(diagnostic["mass_error"]), 1e-10)
                self.assertAlmostEqual(
                    diagnostic["refractory_variance"], DELAY**2 / stages
                )
                event_counts.append(actual[0])
                active_masses.append(diagnostic["active_mass"])
        for coarse, fine in zip(event_counts, event_counts[1:]):
            self.assertLess(fine, 0.2 * coarse)
        self.assertLess(event_counts[-1], 2e-6)
        self.assertLess(active_masses[-1], 0.01)


if __name__ == "__main__":
    unittest.main()
