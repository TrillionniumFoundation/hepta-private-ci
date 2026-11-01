"""Deterministic, nonselective mechanisms and task-boundary diagnostics.

These are specified finite-model examples, not independent task-performance
evidence. They retain zero effects and empty reset regions. A free boundary is
reported only as a policy region in belief/time/budget space, never as a proved
universal scalar threshold. Q^pi follows an explicit deployed tail policy.
"""
import time

import numpy as np
from scipy.linalg import expm

from .task_value import ExactBeliefDP


def _numpy(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float64)


def run_mechanisms(cell):
    """Return a JSON-safe report for the 8-active/2-recovery R12 model."""
    cpu, wall = time.process_time(), time.perf_counter()
    planner = ExactBeliefDP(cell)
    if planner.states != 20 or planner.E.shape != (20, 7):
        raise ValueError("R12 mechanisms require the 20-state, seven-observation profile")
    centers = _numpy(getattr(cell, "centers", (np.arange(8)+.5)*.1))
    if centers.shape != (8,) or not np.isfinite(centers).all():
        raise ValueError("Expected eight finite log-distance bin centers")
    q, reset, emission = planner.Q, planner.R, planner.E
    schedule = (.15, .45, 1.05)

    def belief(phase_weights, probability_one=.5):
        return np.outer(np.asarray(phase_weights, float), [1-probability_one, probability_one]).reshape(20)

    def point(phase, probability_one=.5):
        weights = np.zeros(10)
        weights[phase] = 1.
        return belief(weights, probability_one)

    def describe(p, times=schedule, budget=2):
        phases = p.reshape(10, 2).sum(1)
        active_mass = float(phases[:8].sum())
        mean = float(phases[:8] @ centers / active_mass) if active_mass else None
        variance = (float(phases[:8] @ ((centers-mean)**2)/active_mass)
                    if active_mass else None)
        return dict(belief=p.tolist(), bit_one=float(p[1::2].sum()),
                    active_margin_mean=mean, active_margin_variance=variance,
                    recovery_mass=float(phases[8:].sum()),
                    schedule=list(times), read_budget=budget,
                    channels=planner.channels(p, times, budget))

    # Same mean, same content posterior, different distributional tails.
    narrow_weights, wide_weights = np.zeros(10), np.zeros(10)
    narrow_weights[[3, 4]], wide_weights[[0, 7]] = .5, .5
    narrow, wide = belief(narrow_weights), belief(wide_weights)
    killed = expm(q[:16, :16]*1.05)
    equal_mean = dict(narrow=describe(narrow), wide=describe(wide), horizon=1.05,
                      first_event_narrow=float(1-(narrow[:16] @ killed).sum()),
                      first_event_wide=float(1-(wide[:16] @ killed).sum()))
    equal_mean["mean_difference"] = abs(equal_mean["narrow"]["active_margin_mean"]
                                         -equal_mean["wide"]["active_margin_mean"])
    equal_mean["first_event_difference"] = equal_mean["first_event_wide"]-equal_mean["first_event_narrow"]

    # Same margin but different known content uncertainty; time and recovery
    # comparisons keep the starting content posterior fixed.
    uncertain, confident = point(3, .5), point(3, .9)
    half_recovering = .5*confident+.5*point(8, .9)
    uncertainty = dict(uncertain=describe(uncertain), confident=describe(confident))
    time_sensitivity = dict(short=describe(confident, (.15, .15, .15)),
                            long=describe(confident, (1.05, 1.05, 1.05)))
    recovery = dict(active=describe(confident), mixed=describe(half_recovering),
                    phase0=describe(point(8, .9)), phase1=describe(point(9, .9)))

    # Identical phase and content marginals can hide opposite associations
    # between a content bit and a state likely to be lost or regenerated.
    correlated_a, correlated_b = np.zeros(20), np.zeros(20)
    correlated_a[[0, 15]], correlated_b[[1, 14]] = .5, .5
    flow = expm(q*1.05)
    next_a, next_b = correlated_a @ flow, correlated_b @ flow
    alive_a, alive_b = correlated_a[:16] @ killed, correlated_b[:16] @ killed
    content_correlation = dict(
        before_a=describe(correlated_a), before_b=describe(correlated_b),
        phase_marginal_max_difference=float(np.max(np.abs(correlated_a.reshape(10, 2).sum(1)
                                                        -correlated_b.reshape(10, 2).sum(1)))),
        bit_marginal_difference=float(abs(correlated_a[1::2].sum()-correlated_b[1::2].sum())),
        after_bit_one_a=float(next_a[1::2].sum()), after_bit_one_b=float(next_b[1::2].sum()),
        surviving_content_a=float(alive_a[1::2].sum()-alive_a[::2].sum()),
        surviving_content_b=float(alive_b[1::2].sum()-alive_b[::2].sum()),
        scope="Different successor content does not by itself prove a utility advantage.")

    # Resetting at the interval end incorrectly discards all within-interval
    # recovery and its content consequences. Record the complete two outcomes.
    asymmetric = point(7, .9)
    after_reset = asymmetric @ reset
    reset_then_time, time_then_reset = after_reset @ flow, asymmetric @ flow @ reset
    reset_remaining_time = dict(
        initial=asymmetric.tolist(), after_reset=after_reset.tolist(),
        exact_reset_then_time=reset_then_time.tolist(), wrong_end_reset=time_then_reset.tolist(),
        duration=1.05,
        initial_bit_one=float(asymmetric[1::2].sum()),
        immediate_reset_bit_one=float(after_reset[1::2].sum()),
        completed_interval_bit_one=float(reset_then_time[1::2].sum()),
        interval_end_reset_bit_one=float(time_then_reset[1::2].sum()),
        recovered_active_mass=float(reset_then_time[:16].sum()),
        order_l1_difference=float(np.abs(reset_then_time-time_then_reset).sum()),
        exact_task_q=planner.action_values(asymmetric, (1.05,), 0))

    def wait_tail(p, times, budget):
        if times:
            return "WAIT"
        return f"STOP{int(np.argmax(p @ planner.reward))}"

    q_star = planner.action_values(uncertain, schedule, 2)
    q_pi = planner.paired_q_pi(uncertain, schedule, 2, wait_tail)
    continuation = dict(policy="WAIT at every remaining step; best observed-belief answer at deadline",
                        first_action_q_star=q_star, first_action_q_pi=q_pi,
                        oracle_tail_gap={action: q_star[action]-q_pi[action] for action in q_pi},
                        policy_value=planner.evaluate_policy(uncertain, schedule, 2, wait_tail))

    # Preserve every slice, including those where STOP dominates both channels
    # or RESET is never chosen. No reward/price tuning is performed here.
    boundary_slices = []
    for phase in (0, 3, 7):
        for confidence in (.5, .9):
            for times in ((.15,), (.15, .45, 1.05)):
                for budget in (0, 2):
                    row = describe(point(phase, confidence), times, budget)
                    row.update(phase=phase, content_confidence=confidence)
                    boundary_slices.append(row)
    price_sensitivity = []
    for multiplier in (.5, 1., 2.):
        priced = ExactBeliefDP(cell, read_multiplier=multiplier)
        price_sensitivity.append(dict(read_multiplier=multiplier,
                                      channels=priced.channels(uncertain, schedule, 2)))

    full = expm(q*.60)
    segmented = expm(q*.15) @ expm(q*.45)
    all_beliefs = (narrow, wide, confident, half_recovering, next_a, next_b,
                   reset_then_time, time_then_reset)
    unavailable_posterior = half_recovering*emission[:, 6]
    unavailable_mass = float(unavailable_posterior.sum())
    unavailable_posterior = unavailable_posterior/unavailable_mass if unavailable_mass else None
    invariants = dict(
        max_mass_error=max(float(abs(p.sum()-1)) for p in all_beliefs),
        minimum_probability=min(float(p.min()) for p in all_beliefs),
        irregular_time_semigroup_max_error=float(np.max(np.abs(full-segmented))),
        reset_preserves_immediate_bit_error=float(abs(asymmetric[1::2].sum()-after_reset[1::2].sum())),
        unavailable_observation_probability=unavailable_mass,
        unavailable_posterior_recovery_mass=(None if unavailable_posterior is None
                                             else float(unavailable_posterior[16:].sum())),
        q_pi_exceeds_optimal=max(0., max(q_pi[a]-q_star[a] for a in q_pi)))
    return dict(
        schema="hcsn.r12.mechanisms.v1", model_identity=planner.model_identity,
        scope="Finite-model diagnostics; no confirmation-set selection or production claim",
        same_mean_different_distribution=equal_mean, content_uncertainty=uncertainty,
        remaining_time=time_sensitivity, recovery_state=recovery,
        content_risk_correlation=content_correlation, reset_remaining_time=reset_remaining_time,
        continuation_marginalization=continuation, boundary_slices=boundary_slices,
        strictly_optimal_reset_slice_count=sum(row["channels"]["reset_strictly_optimal"] for row in boundary_slices),
        slice_count=len(boundary_slices), price_sensitivity=price_sensitivity,
        numerical_invariants=invariants, planner_cache=planner.cache_info(),
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
