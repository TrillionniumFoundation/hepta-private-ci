"""Reachable equal-marginal histories under the existing R15 emissions.

R16 extends the public observation schedule to continuous intervals. It does
not change the emission alphabet or condition on a future scoring label. The
two histories exchange content labels 1 and 2. A deterministic scalar root
equates their current content marginals; phase marginals agree by symmetry.
Their future optimal *answer* can differ. This does not assert different
READ/WAIT/REFRESH timing decisions in the label-symmetric R15 task.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

from ..addressed_decision_r15_20261101.law import Law, default_free_raw
from .compression import project


FAMILIES = ("hx", "free_drift", "phase_inhomogeneous", "reset_mixture")
AGE = 2.0
FORECAST = 2.0
ROOT_INTERVAL = (0.0, 80.0)


def family_law(family):
    """Predeclared alternative laws, with all content labels exchangeable."""
    if family == "hx":
        return Law()
    if family == "free_drift":
        raw = default_free_raw()
        raw[:3] += np.log([1.15, .85, 1.2])
        return Law(mode="free", free_raw=raw)
    law = Law.from_export(Law().export())
    law.Q = law.Q.copy()
    if family == "phase_inhomogeneous":
        rates = np.repeat(1 + .55 * np.cos(np.arange(10)), 4)
        law.Q *= rates[:, None]
    elif family == "reset_mixture":
        weights = np.array([0., .2, 0., .3, 0., 0., .5, 0.])
        for content in range(4):
            row = 36 + content
            law.Q[row] = 0
            for phase, weight in enumerate(weights):
                for target in range(4):
                    keep = law.same_content if target == content else (1 - law.same_content) / 3
                    law.Q[row, 4 * phase + target] = law.recovery_rate * weight * keep
            law.Q[row, row] = -law.recovery_rate
    else:
        raise ValueError("Unknown registered law family")
    law.params["r16_family"] = family
    law._finish()
    return law


def uniformization(q, dt):
    """Independent positive-series reference; reports Poisson truncation only.

    The displayed bound excludes floating-point roundoff. Splitting avoids
    underflow for long intervals; no normalization hides accumulated error.
    """
    rate = float(np.max(-np.diag(q)))
    if dt == 0 or rate == 0:
        return np.eye(len(q)), 0.0
    parts = max(1, int(np.ceil(rate * dt / 6)))
    mu = rate * dt / parts
    step = np.eye(len(q)) + q / rate
    weight = np.exp(-mu)
    power = np.eye(len(q))
    total = weight * power
    from scipy.special import gammainc
    for order in range(1, 256):
        power = power @ step
        weight *= mu / order
        total += weight * power
        tail = float(gammainc(order + 1, mu))
        if tail < 1e-17 / parts:
            break
    else:
        raise RuntimeError("Uniformization budget exhausted")
    return np.linalg.matrix_power(total, parts), parts * tail


def history_posterior(law, gap, first=1, second=2, reference=False):
    transition = (lambda dt: uniformization(law.Q, dt)[0]) if reference else law.transition
    p = law.initial_prior(0) @ transition(AGE)
    p *= law.E_refresh[:, first]
    first_mass = float(p.sum())
    p /= first_mass
    p = p @ transition(gap)
    p *= law.E_read[:, second]
    second_mass = float(p.sum())
    p /= second_mass
    return p, first_mass * second_mass


def witness(law, family):
    def equalize(gap):
        p, _ = history_posterior(law, gap)
        marginal = p.reshape(10, 4).sum(0)
        return float(marginal[1] - marginal[2])

    left, right = map(equalize, ROOT_INTERVAL)
    if not left > 0 > right:
        return dict(family=family, found=False, reason="Registered root bracket has no sign change",
                    root_endpoint_values=[left, right])
    gap, root_result = brentq(equalize, *ROOT_INTERVAL, xtol=1e-13, full_output=True)
    p, mass_p = history_posterior(law, gap)
    q, mass_q = history_posterior(law, gap, 2, 1)
    beliefs = np.array([p, q])
    joint = beliefs.reshape(2, 10, 4)
    predictions = beliefs @ law.transition(FORECAST) @ law.reward
    full_value = float(predictions.max(1).mean())
    marginal_optimum = float(predictions.mean(0).max())
    compressed = {}
    for mode in ("factorized", "block2", "block4", "block5"):
        states = law.project(beliefs, mode) if mode == "factorized" else project(beliefs, mode)
        estimates = states @ law.transition(FORECAST) @ law.reward
        answers = estimates.argmax(1)
        compressed[mode] = dict(answers=answers.tolist(),
                                actual_expected_reward=float(predictions[np.arange(2), answers].mean()),
                                forecast_l1_error=np.abs(estimates - predictions).sum(1).tolist())
    # This ordinary tracker stores which public history occurred, then uses
    # exactly the same conditional matrix. It is a strong sufficiency control.
    hmm = Law.from_export(law.export())
    tracked = np.array([history_posterior(hmm, gap, a, b)[0]
                        for a, b in ((1, 2), (2, 1))])
    hmm_predictions = tracked @ hmm.transition(FORECAST) @ hmm.reward
    refs = np.array([history_posterior(law, gap, a, b, True)[0]
                     for a, b in ((1, 2), (2, 1))])
    ref_transition, truncation = uniformization(law.Q, FORECAST)
    ref_predictions = refs @ ref_transition @ law.reward
    phase_error = float(np.max(np.abs(joint[0].sum(1) - joint[1].sum(1))))
    content_error = float(np.max(np.abs(joint[0].sum(0) - joint[1].sum(0))))
    numerical_error = float(np.max(np.abs(predictions - ref_predictions)))
    gain = full_value - marginal_optimum
    qualifies = (max(phase_error, content_error) < 2e-12 and gain > 1e-6
                 and numerical_error < 1e-10 and mass_p > 0 and mass_q > 0
                 and predictions.argmax(1)[0] != predictions.argmax(1)[1])
    return dict(family=family, found=bool(qualifies), law=law.export(),
                schedule=dict(initial_write=0, first_observation_time=AGE,
                              first_quality="refresh", second_quality="read",
                              gap=gap, forecast_interval=FORECAST,
                              histories=[[1, 2], [2, 1]],
                              scope="R15 law/emissions, extended R16 continuous-time schedule"),
                root_endpoint_values=[left, right], root_iterations=root_result.iterations,
                positive_history_probabilities=[mass_p, mass_q],
                history_probability_difference=abs(mass_p - mass_q),
                equal_mixture_reason="The two histories are label permutations under a label-exchangeable initial law",
                posterior_beliefs=beliefs.tolist(), phase_marginal_error=phase_error,
                content_marginal_error=content_error,
                joint_l1_distance=float(np.abs(p - q).sum()), predictions=predictions.tolist(),
                optimal_answers=predictions.argmax(1).tolist(),
                full_expected_reward=full_value, best_common_answer_reward=marginal_optimum,
                equal_history_mixture_regret=gain,
                compressed=compressed,
                ordinary_public_history_tracker_max_error=float(np.max(np.abs(hmm_predictions - predictions))),
                independent_uniformization_prediction_error=numerical_error,
                uniformization_poisson_truncation_only_bound=truncation,
                value_risk_feature_differences=dict(
                    terminal_stop_value=float(abs(predictions[0].max() - predictions[1].max())),
                    first_passage=float(abs(law.first_hit(p, FORECAST) - law.first_hit(q, FORECAST)))),
                scope="Existence and exact conditional decision value; no population net-gain or HX superiority claim",
                tracker_scope="This implemented ordinary tracker recomputes a full 40-state posterior; a one-bit history index is a sufficiency argument, not a measured optimized implementation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start = time.process_time()
    rows = [witness(family_law(family), family) for family in FAMILIES]
    result = dict(schema="hcsn-r16-reachable-v1", families=rows,
                  cost=dict(cpu_seconds=time.process_time() - start,
                            scope="All four laws, root attempts and independent series; imports excluded"),
                  no_post_outcome_selection=True,
                  failure_policy="Report every registered family including no-witness outcomes",
                  limitations=["Timing extends R15 discrete schedule", "Exact expectation conditional on two histories",
                               "Strict optimal answer, not different timing action", "Ordinary history tracker is equal",
                               "Float64 numerical witness, not interval-certified continuum proof"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"families": [{k: row.get(k) for k in
                                    ("family", "found", "equal_history_mixture_regret",
                                     "independent_uniformization_prediction_error")} for row in rows],
                      "cpu_seconds": result["cost"]["cpu_seconds"]}))


if __name__ == "__main__":
    main()
