"""Two-stage acquisition of genuine external audio under a finite public model.

The acquired observation is the class pair returned by a frozen CNN on actual
late-arriving source WAVs. Generated output is not evidence about its own hidden
target. The backup exactly evaluates its declared stagewise continuation policy
under the supplied posterior, likelihood, endpoint table, calibration and cost
law. It is not a general solution to policy-dependent global chance constraints.
Those learned objects need validation and do not inherit earlier qualification.
"""

import math

import numpy as np


SCHEMA = 'hepta.advance.external-audio-bellman.v1'
Q = 1 << 24
REJECT, STOP, ACQUIRE = -1, 100, 101
ROLES = ('emit', 'acquire', 'stop')


def law(value, size=100):
    value = np.asarray(value, dtype=np.float64)
    if value.shape != (size,) or not np.isfinite(value).all() or (value < 0).any():
        raise ValueError('A finite public probability vector is required')
    if not math.isclose(float(value.sum()), 1., abs_tol=1e-5):
        raise ValueError('Public probabilities must sum to one')
    return value / value.sum()


def likelihood_matrix(value):
    value = np.asarray(value, dtype=np.float64)
    if (value.shape != (100, 100) or not np.isfinite(value).all() or (value < 0).any()
            or not np.allclose(value.sum(0), 1., atol=1e-12, rtol=0.)):
        raise ValueError('Likelihood[observation,target] must be column stochastic')
    return value


def update_belief(prior, observation, likelihood):
    prior, likelihood = law(prior), likelihood_matrix(likelihood)
    if not isinstance(observation, (int, np.integer)) or not 0 <= observation < 100:
        raise ValueError('Only an actual public source-CNN label pair is accepted')
    joint = prior * likelihood[int(observation)]
    mass = float(joint.sum())
    if mass <= 0:
        raise ValueError('Observed source result has zero probability under frozen likelihood')
    return joint / mass, mass


def confidence(probabilities, role, calibration=None):
    p = np.asarray(probabilities, dtype=np.float64)
    if role not in ROLES or not np.isfinite(p).all() or (p < 0).any() or (p > 1.0000001).any():
        raise ValueError('Valid terminal strict-success probability and operation role required')
    p = np.clip(p, 0., 1.)
    if calibration is not None:
        if calibration.get('schema') != 'hepta.advance.operation-confidence.v1':
            raise ValueError('Wrong operation calibration schema')
        spec = calibration['roles'][role]
        cuts, values = np.asarray(spec['cuts']), np.asarray(spec['probabilities'])
        if (cuts.ndim != 1 or values.ndim != 1 or len(values) != len(cuts) + 1
                or not np.isfinite(cuts).all() or (cuts < 0).any() or (cuts > 1).any()
                or not np.isfinite(values).all()
                or np.any(np.diff(cuts) <= 0) or (values < 0).any() or (values > 1).any()):
            raise ValueError('Invalid frozen calibration curve')
        p = values[np.searchsorted(cuts, p, side='right')]
    # Match the native Q24 -> ppm residual-confidence arithmetic.
    prediction = np.floor(p * Q + .5).astype(np.int64)
    return (1_000_000 - np.minimum(np.abs(Q - prediction) * 1_000_000 // Q, 1_000_000)) / 1e6


def terminal(utility, strict, posterior, *, emit_cost=.002, minimum_confidence=.75,
             calibration=None, actual_mask=None, stop=None, rejection_probability=0., gamma=2.):
    """All 100 code emissions and optional actually observed retained bundle.

stop supplies actual target-indexed utility/strict arrays, never merely the
planned code index. current actual_mask is authoritative after genuine owner
ticks. Predicted future masks use the same frozen operation calibration. A
resource rejection probability is a supplied model, not an inferred certificate.
"""
    posterior = law(posterior)
    utility, strict = np.asarray(utility, dtype=np.float64), np.asarray(strict, dtype=np.float64)
    if (utility.shape != (100, 100) or strict.shape != utility.shape
            or not np.isfinite(utility).all() or not np.isfinite(strict).all()
            or (strict < 0).any() or (strict > 1).any()
            or not math.isfinite(emit_cost) or emit_cost < 0
            or not math.isfinite(gamma) or gamma <= 0
            or not math.isfinite(minimum_confidence) or not 0 <= minimum_confidence <= 1):
        raise ValueError('Frozen endpoint utility/strict tables and nonnegative emit cost required')
    reject = np.broadcast_to(np.asarray(rejection_probability, dtype=np.float64), (100,))
    if not np.isfinite(reject).all() or (reject < 0).any() or (reject > 1).any():
        raise ValueError('Valid supplied future resource-rejection probabilities required')
    terminal_factor = (1 - reject[:, None]) * np.exp(-gamma * utility) + reject[:, None] * math.exp(gamma)
    moment = math.exp(gamma * emit_cost) * (terminal_factor @ posterior)
    success = (1 - reject) * (strict @ posterior)
    admitted = confidence(success, 'emit', calibration) >= minimum_confidence
    if actual_mask is not None:
        actual_mask = np.asarray(actual_mask, dtype=bool)
        if actual_mask.shape != (101,):
            raise ValueError('Actual current mask requires 100 code positions plus stop')
        admitted &= actual_mask[:100]
    candidates = {int(a): (float(moment[a]), float(success[a])) for a in np.flatnonzero(admitted)}
    stop_moment = stop_success = None
    if stop is not None:
        su, sk = np.asarray(stop['utility'], dtype=np.float64), np.asarray(stop['strict'], dtype=np.float64)
        if (su.shape != (100,) or sk.shape != (100,) or not np.isfinite(su).all()
                or not np.isfinite(sk).all() or (sk < 0).any() or (sk > 1).any()):
            raise ValueError('Stop must describe an actual observed complete bundle')
        stop_moment, stop_success = float(np.exp(-gamma * su) @ posterior), float(sk @ posterior)
        permitted = bool(confidence(stop_success, 'stop', calibration) >= minimum_confidence)
        if actual_mask is not None: permitted &= bool(actual_mask[STOP])
        if permitted: candidates[STOP] = (stop_moment, stop_success)
    if candidates:
        action = min(candidates, key=lambda a: (candidates[a][0], a != STOP, a))
        value, p_success = candidates[action]
    else:
        action, value, p_success = REJECT, math.exp(gamma), 0.
    return {'action': action, 'moment': value, 'strict_success_probability': p_success,
            'code_moments': moment, 'code_strict_success': success, 'code_admitted': admitted,
            'stop_moment': stop_moment, 'stop_strict_success': stop_success}


def plan(utility, strict, prior, likelihood, *, emit_cost=.002, acquire_cost=.002,
         minimum_confidence=.75, calibration=None, current_actual_mask=None,
         future_resource_rejection=0., stop=None, remaining_decisions=2, gamma=2.):
    """Compare immediate delivery with acquisition and its admissible continuation.

Acquisition cost is either scalar or 100 registered costs indexed by the public
observation. The factor exp(gamma*cost[o]) remains inside the outcome sum. A
probability-sensitive cost law needs a finer observation/cost branch model (use
bellman.solve); replacing it by a mean cost is not silently done here.
"""
    prior, likelihood = law(prior), likelihood_matrix(likelihood)
    if remaining_decisions not in (1, 2):
        raise ValueError('The explicit decision budget is one or two')
    if current_actual_mask is not None:
        current_actual_mask = np.asarray(current_actual_mask, dtype=bool)
        if current_actual_mask.shape != (102,):
            raise ValueError('Root actual mask must cover codes, stop and acquisition')
    now = terminal(utility, strict, prior, emit_cost=emit_cost, minimum_confidence=minimum_confidence,
                   calibration=calibration, actual_mask=None if current_actual_mask is None else current_actual_mask[:101],
                   stop=stop, gamma=gamma)
    observation_mass = likelihood @ prior
    costs = np.broadcast_to(np.asarray(acquire_cost, dtype=np.float64), (100,))
    if not np.isfinite(costs).all() or (costs < 0).any():
        raise ValueError('Finite nonnegative registered observation-wise acquisition cost required')
    futures = []
    for observation in range(100):
        mass = float(observation_mass[observation])
        if mass == 0:
            futures.append({'observation': observation, 'mass': 0., 'action': REJECT,
                            'moment': math.exp(gamma), 'strict_success_probability': 0.})
            continue
        posterior = prior * likelihood[observation] / mass
        if remaining_decisions == 1:
            future = {'action': REJECT, 'moment': math.exp(gamma), 'strict_success_probability': 0.}
        else:
            future = terminal(utility, strict, posterior, emit_cost=emit_cost,
                minimum_confidence=minimum_confidence, calibration=calibration, stop=stop,
                rejection_probability=future_resource_rejection, gamma=gamma)
        futures.append({'observation': observation, 'mass': mass, 'action': future['action'],
                        'moment': future['moment'], 'strict_success_probability': future['strict_success_probability']})
    acquisition_moment = math.fsum(row['mass'] * math.exp(gamma * costs[row['observation']]) * row['moment'] for row in futures)
    acquisition_success = math.fsum(row['mass'] * row['strict_success_probability'] for row in futures)
    if remaining_decisions == 1:
        # Inactive operation: no acquisition was attempted and no cost is paid.
        acquisition_moment, acquisition_success = math.exp(gamma), 0.
    acquisition_admitted = (remaining_decisions == 2
        and bool(confidence(acquisition_success, 'acquire', calibration) >= minimum_confidence))
    if current_actual_mask is not None: acquisition_admitted &= bool(current_actual_mask[ACQUIRE])
    selected = now['action']
    value, p_success = now['moment'], now['strict_success_probability']
    if acquisition_admitted and (selected == REJECT or acquisition_moment < value):
        selected, value, p_success = ACQUIRE, acquisition_moment, acquisition_success
    return {'schema': SCHEMA, 'action': selected, 'moment': value,
            'strict_success_probability': p_success,
            'immediate': now, 'acquire_moment': acquisition_moment,
            'acquire_strict_success_probability': acquisition_success,
            'acquire_admitted': acquisition_admitted,
            'future_no_admitted_observation_mass': math.fsum(r['mass'] for r in futures if r['action'] == REJECT),
            'future_policy': futures,
            'scope': 'Exact backup of the declared stagewise policy under supplied public belief/likelihood/cost/admission laws. General policy-dependent chance-constrained global optimality, actual future resource tails and source-distribution accuracy are not certified.'}
