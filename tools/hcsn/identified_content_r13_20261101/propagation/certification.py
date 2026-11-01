"""Claim gate: finite numerical comparisons cannot certify continuum policies.

The caller must supply evidence, not just a small error-looking number. For a
continuous target every listed proof obligation is required. A full-policy
claim additionally needs a bound uniform over all policies/reachable histories;
a local Q-vector comparison never supplies that bound automatically.
"""

from fractions import Fraction
import math

import numpy as np


CONTINUOUS_OBLIGATIONS = (
    'uniform_over_admissible_actions',
    'common_space_or_projection_lifting_justified',
    'spatial_error_included',
    'upper_domain_error_included',
    'observation_conditioning_error_included',
    'financial_or_declared_payoff_error_included',
    'inference_and_parameter_error_included',
    'arithmetic_error_included',
)


def _nonnegative_fraction(value, name):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be finite and nonnegative')
    return Fraction.from_float(value)


def _outward(value, up):
    if value == math.inf:
        return math.inf
    converted = float(value)
    exact = Fraction.from_float(converted)
    if (up and exact < value) or (not up and exact > value):
        converted = float(np.nextafter(converted, math.inf if up else -math.inf))
    return converted


def certify(qvalues, *, target='continuous_financial_task', horizon=3,
            tie_tolerance=1e-12, reference_qvalues=None,
            continuous_uniform_q_error=None, continuous_obligations=None,
            continuous_evidence_description=None,
            all_policy_value_error=None, all_policy_bound_justified=False):
    """Return local and whole-policy conclusions with different proof scopes.

    target='computed_finite_reference': compare the supplied binary64 Q vectors
    as exact rational numbers. This supports a numerical-vector result only.

    target='continuous_financial_task' or 'continuous_declared_observable':
    a supplied uniform Q error plus every continuous proof obligation is needed.
    The latter target must identify its restricted observable in the description.

    If D bounds per-policy value discrepancies uniformly and the approximate
    policy uses tolerance tau at each of H Bellman levels, policy regret is
    <=2D+H*tau. Neither D nor its uniform coverage is inferred from a local gap.
    """
    if target not in ('computed_finite_reference', 'continuous_financial_task',
                      'continuous_declared_observable'):
        raise ValueError('Unknown claim target')
    if not isinstance(horizon, int) or horizon < 1:
        raise ValueError('horizon must be a positive integer')
    values = np.asarray(qvalues, dtype=float)
    if values.ndim != 1 or np.isnan(values).any() or np.isposinf(values).any():
        raise ValueError('One Q vector with finite values or inadmissible -inf required')
    admissible = np.flatnonzero(np.isfinite(values))
    if not len(admissible):
        raise ValueError('At least one admissible action required')
    rational = {int(i): Fraction.from_float(float(values[i])) for i in admissible}
    tau = _nonnegative_fraction(tie_tolerance, 'tie tolerance')
    best_value = max(rational.values())
    best = min(i for i, v in rational.items() if v == best_value)
    action = min(i for i, v in rational.items() if best_value-v <= tau)
    competitors = [v for i, v in rational.items() if i != best]
    gap = best_value-max(competitors) if competitors else math.inf
    missing = []
    epsilon = None
    if target == 'computed_finite_reference':
        if reference_qvalues is None:
            missing.append('computed_finite_reference_qvalues')
        else:
            ref = np.asarray(reference_qvalues, dtype=float)
            if ref.shape != values.shape or np.isnan(ref).any() or np.isposinf(ref).any():
                raise ValueError('Reference must have matching shape and finite/-inf entries')
            if not np.array_equal(np.isfinite(ref), np.isfinite(values)):
                missing.append('same_admissible_action_set')
            else:
                epsilon = max(abs(v-Fraction.from_float(float(ref[i]))) for i, v in rational.items())
    else:
        if continuous_uniform_q_error is None:
            missing.append('continuous_uniform_action_value_error')
        else:
            epsilon = _nonnegative_fraction(continuous_uniform_q_error, 'continuous Q error')
        obligations = continuous_obligations or {}
        missing.extend(key for key in CONTINUOUS_OBLIGATIONS if obligations.get(key) is not True)
        if not continuous_evidence_description:
            missing.append('continuous_evidence_description')
    complete = not missing and epsilon is not None
    threshold = 2*epsilon+horizon*tau if complete else None
    gap_pass = bool(complete and gap > threshold)
    local_bound = 2*epsilon+tau if complete else None
    policy_missing = []
    policy_bound = None
    if not complete:
        policy_missing.append('complete_target_error_evidence')
    if all_policy_value_error is None:
        policy_missing.append('uniform_all_policy_value_error_D')
    if not all_policy_bound_justified:
        policy_missing.append('all_policy_bound_coverage_justified')
    if not policy_missing:
        d = _nonnegative_fraction(all_policy_value_error, 'all-policy value error')
        policy_bound = 2*d+horizon*tau
    if not complete:
        status = 'uncertified'
    elif gap_pass and target == 'computed_finite_reference':
        status = 'certified_for_supplied_finite_Q_vectors'
    elif gap_pass:
        status = 'conditional_continuous_action_certificate'
    else:
        status = 'uncertified_action_gap'
    return {
        'target': target, 'status': status, 'action': action,
        'best_gap_lower_bound': _outward(gap, False),
        'uniform_Q_error_upper_bound': None if epsilon is None else _outward(epsilon, True),
        'required_gap_with_accumulated_ties': None if threshold is None else _outward(threshold, True),
        'missing_evidence': missing, 'complete_target_error_evidence': complete,
        'action_gap_certified': gap_pass,
        'single_decision_regret_bound_for_supplied_target_Q': None if local_bound is None else _outward(local_bound, True),
        'one_action_reference_optimal_bound_conditional_on_Bellman_tie_contract':
            None if threshold is None else _outward(threshold, True),
        'whole_policy_regret_bound': None if policy_bound is None else _outward(policy_bound, True),
        'whole_policy_missing_evidence': policy_missing,
        'horizon': horizon, 'tie_tolerance': float(tau),
        'tie_loss_budget': _outward(horizon*tau, True),
        'continuous_optimality_claim_allowed': bool(gap_pass and target != 'computed_finite_reference'),
        'continuous_evidence_description': continuous_evidence_description,
        'instruction': ('accept_only_the_stated_target_and_coverage' if gap_pass
                        else 'refine_or_supply_missing_evidence; do_not_claim_continuous_optimality'),
    }
