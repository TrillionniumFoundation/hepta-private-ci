"""Independent finite-policy enumeration and consequential kernel edge cases."""

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np

from . import bellman, dynamic


def brute(states, root):
    """Enumerate whole deterministic policies, then expand their actual leaves."""
    choices = {}
    for name, state in states.items():
        choices[name] = list(state.actions)
        if state.stop_moment is not None:
            choices[name].append('stop')
        if not choices[name]:
            choices[name].append(None)
    names = list(choices)
    values = []
    for options in itertools.product(*(choices[name] for name in names)):
        policy = dict(zip(names, options))

        def expand(name, probability, spent):
            state, action = states[name], policy[name]
            if action is None:
                return probability * math.exp(2 * (spent - state.rejection_utility))
            if action == 'stop':
                return probability * math.exp(2 * spent) * state.stop_moment
            result = 0.
            for branch in state.actions[action]:
                p, cost = probability * branch.probability, spent + branch.cost
                if branch.next_state is None:
                    result += p * math.exp(2 * (cost - branch.terminal_utility))
                else:
                    result += expand(branch.next_state, p, cost)
            return result

        values.append((expand(root, 1., 0.), policy))
    return min(v[0] for v in values), len(values)


def finite_cases():
    rng = np.random.default_rng(7611)
    maximum_error, policies = 0., 0
    for index in range(64):
        states = {}
        for child in range(3):
            actions = {}
            if not (index % 2 == 0 and child == 2):
                for action in range(2):
                    p = float(rng.uniform(.1, .9))
                    actions[str(action)] = tuple(bellman.Branch(
                        probability, float(rng.uniform(0, .4)),
                        terminal_utility=float(rng.uniform(-1, 1))) for probability in (p, 1 - p))
            stop = float(rng.uniform(.15, 3.)) if child == 1 else None
            states[str(child)] = bellman.State(1, actions, stop)
        branches = {}
        for action in range(2):
            weights = rng.dirichlet(np.ones(3))
            branches[str(action)] = tuple(bellman.Branch(float(weights[c]),
                float(rng.uniform(0, .4)), next_state=str(c)) for c in range(3))
        states['root'] = bellman.State(2, branches, .9 if index % 3 == 0 else None)
        expected, count = brute(states, 'root')
        actual = bellman.solve(states, 'root').root_moment
        maximum_error = max(maximum_error, abs(actual - expected))
        policies += count
    assert maximum_error < 1e-12
    # A realized expensive failure cannot be replaced by average cost.
    state = bellman.State(1, {'attempt': (
        bellman.Branch(.5, 0., terminal_utility=1.),
        bellman.Branch(.5, .7, terminal_utility=-1.))})
    exact = bellman.solve({'root': state}, 'root').root_moment
    invalid_mean = math.exp(.7) * (.5 * math.exp(-2) + .5 * math.exp(2))
    assert abs(exact - invalid_mean) > 1.
    return {'models': 64, 'whole_policies_enumerated': policies,
            'max_absolute_moment_error': maximum_error,
            'correlated_cost_exact_moment': exact,
            'invalid_mean_cost_moment': invalid_mean}


def dense_case():
    """Independent target/outcome expansion for a binary endpoint system."""
    rng = np.random.default_rng(8923)
    prior = rng.dirichlet(np.ones(100))
    likelihood = rng.dirichlet(np.ones(100) * .15, size=100).T
    utility = np.eye(100)
    costs = np.linspace(.001, .03, 100)
    # A lower diagnostic floor exercises many simultaneous admissible codes.
    forecast = dynamic.plan(utility, utility, prior, likelihood,
        acquire_cost=costs, minimum_confidence=.05)
    exact_moment = exact_success = 0.
    for observation, future in enumerate(forecast['future_policy']):
        action = future['action']
        for target in range(100):
            joint = prior[target] * likelihood[observation, target]
            value = -1. if action == dynamic.REJECT else utility[action, target] - .002
            exact_moment += joint * math.exp(2 * (costs[observation] - value))
            exact_success += joint * (0. if action == dynamic.REJECT else utility[action, target])
    assert abs(exact_moment - forecast['acquire_moment']) < 1e-12
    assert abs(exact_success - forecast['acquire_strict_success_probability']) < 1e-12
    return {'expanded_target_observation_leaves': 10000,
        'moment_error': abs(exact_moment - forecast['acquire_moment']),
        'strict_success_error': abs(exact_success - forecast['acquire_strict_success_probability'])}


def consequential_cases():
    utility = np.eye(100)
    prior = np.zeros(100); prior[:2] = [.55, .45]
    likelihood = np.eye(100)
    likelihood[:2, :2] = [[.95, .05], [.05, .95]]
    result = dynamic.plan(utility, utility, prior, likelihood)
    assert result['action'] == dynamic.ACQUIRE
    assert result['immediate']['action'] == dynamic.REJECT
    assert abs(result['acquire_strict_success_probability'] - .95) < 1e-12
    mask = np.ones(102, dtype=bool); mask[dynamic.ACQUIRE] = False
    assert dynamic.plan(utility, utility, prior, likelihood, current_actual_mask=mask)['action'] == dynamic.REJECT
    assert dynamic.plan(utility, utility, prior, likelihood, remaining_decisions=1)['action'] == dynamic.REJECT
    failed = dynamic.plan(utility, utility, prior, likelihood, future_resource_rejection=1.)
    assert failed['action'] == dynamic.REJECT and abs(failed['future_no_admitted_observation_mass'] - 1.) < 1e-12
    # Existing output affects retained delivery, and does not alter target belief.
    sharp = np.zeros(100); sharp[0] = 1.
    good = {'utility': utility[0], 'strict': utility[0]}
    broken = {'utility': np.full(100, -1.), 'strict': np.zeros(100)}
    assert dynamic.terminal(utility, utility, sharp, stop=good)['action'] == dynamic.STOP
    assert dynamic.terminal(utility, utility, sharp, stop=broken)['action'] == 0
    calibrated = {'schema': 'hepta.advance.operation-confidence.v1', 'roles': {
        role: {'cuts': [.9], 'probabilities': [0., .8]} for role in dynamic.ROLES}}
    weak_likelihood = np.eye(100); weak_likelihood[:2, :2] = [[.8, .2], [.2, .8]]
    rejected = dynamic.plan(utility, utility, prior, weak_likelihood, calibration=calibrated)
    assert rejected['action'] == dynamic.REJECT
    assert abs(rejected['future_no_admitted_observation_mass'] - 1.) < 1e-12
    malformed = []
    for name, call in (
        ('invalid_likelihood', lambda: dynamic.likelihood_matrix(likelihood * 1.000001)),
        ('nonfinite_gamma', lambda: dynamic.terminal(utility, utility, sharp, gamma=float('nan'))),
        ('invalid_stop_strict', lambda: dynamic.terminal(utility, utility, sharp,
            stop={'utility': utility[0], 'strict': np.full(100, 1.2)})),
        ('invalid_remaining_budget', lambda: dynamic.plan(utility, utility, prior, likelihood, remaining_decisions=0)),
        ('nondecreasing_horizon', lambda: bellman.solve({'root': bellman.State(1,
            {'cycle': (bellman.Branch(1., 0., next_state='root'),)})}, 'root'))):
        try:
            call()
        except ValueError:
            malformed.append(name)
        else:
            raise AssertionError(name)
    return {'actual_mask_can_reject_acquisition': True,
            'empty_future_set_is_rejection_not_stop': True,
            'acquisition_success_is_terminal_policy_success': .95,
            'stop_requires_actual_retained_utility': True,
            'budget_one_disables_acquisition': True, 'rejected_invalid_inputs': malformed}


def global_scope_counterexample():
    """Show why arbitrary utility/strict tables require more than stagewise DP."""
    prior = np.zeros(100); prior[:2] = .5
    likelihood = np.eye(100)
    utility = np.full((100, 100), -1.)
    strict = np.zeros((100, 100))
    utility[0, 0] = utility[1, 1] = 1.
    utility[2, 0] = utility[3, 1] = .9
    strict[:2] = .8; strict[2:4] = .99
    calibration = {'schema': 'hepta.advance.operation-confidence.v1', 'roles': {
        'emit': {'cuts': [.75], 'probabilities': [0., 1.]},
        'stop': {'cuts': [.75], 'probabilities': [0., 1.]},
        'acquire': {'cuts': [.9], 'probabilities': [0., 1.]}}}
    result = dynamic.plan(utility, strict, prior, likelihood, calibration=calibration)
    alternate_moment = math.exp(-2 * (.9 - .004))
    assert not result['acquire_admitted']
    assert alternate_moment < result['moment']
    return {'stagewise_acquisition_probability': result['acquire_strict_success_probability'],
            'alternative_feasible_acquisition_probability': .99,
            'stagewise_selected_moment': result['moment'],
            'alternative_continuation_moment': alternate_moment,
            'interpretation': 'Counterexample outside the measured mutually exclusive binary endpoint space: a different continuation can satisfy a policy-dependent root chance gate. Generic global constrained optimality is not claimed.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'schema': 'hepta.advance.control-kernel-verification.v1',
        'registered_ns': time.time_ns(), 'finite_policy_enumeration': finite_cases(),
        'independent_target_outcome_expansion': dense_case(),
        'consequential_edges': consequential_cases(),
        'global_constraint_scope_counterexample': global_scope_counterexample(),
        'code_sha256': {str(Path(module.__file__).resolve()): hashlib.sha256(
            Path(module.__file__).read_bytes()).hexdigest() for module in (bellman, dynamic)},
        'verification_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'native_parity': 'Not executed by this Python-only numerical verification',
        'status': 'passed_with_explicit_global_scope_limit'}
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
