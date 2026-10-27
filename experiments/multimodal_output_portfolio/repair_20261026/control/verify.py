"""Independent whole-policy leaf enumeration and execution-changing counterexamples."""

import argparse
from dataclasses import asdict, replace
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import tempfile
import time

from . import calibration, execution as ex


def binding():
    return ex.Binding(*(ex.digest(name) for name in ('generator', 'owner', 'evidence',
        'continuation', 'calibration', 'objective', 'cost')), resource_names=('native_ticks',))


def state(name, horizon, remaining, actions, allowed=None, screening_cost=0.):
    owner, ticks = ex.digest(name), []
    for action in actions:
        after = ex.digest([owner, action])
        ticks.append(ex.Tick(action, owner, after, allowed is None or action in allowed))
        owner = after
    return ex.ExecutionState(horizon, ex.digest(name), ex.digest([name, 'history']),
        ex.digest([name, 'evidence']), (remaining,), tuple(actions), tuple(ticks), actions,
        screening_cost, (0,))


def terminal(utility, *, cost=0., probability=1., spent=0, success=1., event='delivered', rejected=False):
    return ex.Outcome(probability, cost, (spent,), event, utility=utility,
                      strict_success=success, resource_rejected=rejected)


def brute(states, root):
    """Enumerate raw execution policies, then sum their terminal trajectories.

This never calls compile_model, bellman.solve or evaluate_policy. Budget and
ordered actual tick admission are read directly from the supplied trace.
"""
    names, choices = list(states), []
    for s in states.values():
        available = [a - b for a, b in zip(s.remaining, s.screening_resources)]
        choices.append([t.action for t in s.ticks if t.admitted and all(
            a <= b for a, b in zip(s.actions[t.action].reserved, available))] or [None])
    count, best = 0, math.inf
    for selected in itertools.product(*choices):
        policy = dict(zip(names, selected))

        def leaves(name, weight, spent):
            s, action = states[name], policy[name]
            spent += s.screening_cost
            if action is None:
                return [weight * math.exp(2 * (spent + 1))]
            values = []
            for branch in s.actions[action].outcomes:
                p, c = weight * branch.probability, spent + branch.cost
                if branch.next_state is None:
                    values.append(p * math.exp(2 * (c - branch.utility)))
                else:
                    values.extend(leaves(branch.next_state, p, c))
            return values

        count += 1
        best = min(best, math.fsum(leaves(root, 1., 0.)))
    return best, count


def rejected(call):
    try:
        call()
    except ValueError:
        return True
    raise AssertionError('Invalid execution contract accepted')


def counterexamples():
    good = ex.Action((0,), (terminal(1.),))
    future = {'clear': state('clear', 1, 1, {'emit': good}),
              'blocked': state('blocked', 1, 1, {'emit': good}, allowed=set(), screening_cost=.01)}
    acquire = ex.Action((1,), tuple(ex.Outcome(.5, .01, (1,), event, next_state=event) for event in future))
    root = state('root', 2, 2, {'emit_now': ex.Action((0,), (terminal(.6),)), 'acquire': acquire})
    actual = ex.backup({'root': root, **future}, binding(), 'root')
    optimistic = ex.backup({'root': root, 'clear': future['clear'],
                           'blocked': state('blocked', 1, 1, {'emit': good})}, binding(), 'root')
    assert actual['actions']['root'] == 'emit_now' and optimistic['actions']['root'] == 'acquire'
    forced = {'root': state('root', 2, 2, {'acquire': acquire}), **future}
    run = ex.execute_finite(ex.backup(forced, binding(), 'root'), forced, binding(), [1])
    assert run['utility'] == -1. and run['strict_success'] == 0. and run['total_cost'] == .02
    ties = {'t': state('t', 1, 1, {'a2': good, 'a10': good})}
    assert ex.backup(ties, binding(), 't')['actions']['t'] == 'a2'
    risk = state('cost', 1, 2, {'safe': ex.Action((0,), (terminal(.4),)), 'risky': ex.Action((0,), (
        terminal(1., probability=.9, event='cheap'), terminal(1., cost=3., probability=.1, event='expensive')))})
    correlated = ex.backup({'cost': risk}, binding(), 'cost')
    mean = replace(risk, actions={**risk.actions, 'risky': ex.Action((0,), (terminal(1., cost=.3),))})
    assert correlated['actions']['cost'] == 'safe' and ex.backup({'cost': mean}, binding(), 'cost')['actions']['cost'] == 'risky'
    small = state('budget', 1, 1, {'fast': ex.Action((1,), (terminal(.4, spent=1),)),
        'large': ex.Action((2,), (terminal(-1., spent=2, success=0., rejected=True),))})
    assert ex.backup({'budget': small}, binding(), 'budget')['actions']['budget'] == 'fast'
    ex.check_execution(actual, {'root': root, **future}, binding(), 'root', owner=root.owner,
        history=root.history, evidence=root.evidence, remaining=root.remaining, ticks=root.ticks, selected='emit_now')
    negatives = {
        'candidate_order': rejected(lambda: ex.backup({'root': replace(root, ticks=root.ticks[::-1]), **future}, binding(), 'root')),
        'owner_drift': rejected(lambda: ex.check_execution(actual, {'root': root, **future}, binding(), 'root',
            owner=ex.digest('different owner'), history=root.history, evidence=root.evidence,
            remaining=root.remaining, ticks=root.ticks, selected='emit_now')),
        'continuation_change': rejected(lambda: ex.check_execution(actual, {'root': root, **future},
            replace(binding(), continuation_sha256=ex.digest('different continuation')), 'root', owner=root.owner,
            history=root.history, evidence=root.evidence, remaining=root.remaining, ticks=root.ticks, selected='emit_now')),
        'unmodelled_future_owner': rejected(lambda: ex.attach_observations([{'event': 1, 'probability': 1.}], {}))}
    return {'feasible_future_refusal_root': actual['actions']['root'], 'optimistic_root': optimistic['actions']['root'],
            'joint_random_cost_root': correlated['actions']['cost'], 'mean_cost_root': 'risky',
            'actual_moment': actual['moment'], 'optimistic_moment': optimistic['moment'], 'rejections': negatives,
            'executed_supplied_environment_refusal': run, 'native_numeric_ties_preserve_candidate_order': True}


def enumerated():
    rng, maximum, policies = random.Random(76261), 0., 0
    for i in range(64):
        children = {}
        for name in ('a', 'b'):
            actions = {a: ex.Action((1,), (terminal(rng.uniform(-1, 1), cost=rng.uniform(0, .3),
                                                   success=rng.random()),)) for a in ('emit0', 'emit1')}
            children[name] = state(name, 1, 3, actions, {a for a in actions if rng.random() > .4}, .01)
        actions = {}
        for action in ('first', 'second'):
            p = rng.random()
            actions[action] = ex.Action((1,), tuple(ex.Outcome(prob, rng.random() / 5, (1,), name,
                next_state=name) for name, prob in (('a', p), ('b', 1 - p))))
        states = {'root': state('root', 2, 4, actions, screening_cost=.02), **children}
        expected, count = brute(states, 'root')
        observed = ex.backup(states, binding(), 'root')['moment']
        maximum, policies = max(maximum, abs(expected - observed)), policies + count
    assert maximum < 1e-12
    return {'models': 64, 'whole_policies': policies, 'maximum_absolute_moment_error': maximum}


def calibration_targets():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp)
        descriptor = {'policy': 'dynamic', 'stream_id': 'request', 'source_group_id': 'g', 'pins': {'weights': ex.digest('weights')}}
        files = {'descriptor.json': descriptor, 'OFFLINE_SCORE.json': {
            'policy': 'dynamic', 'source_group': 'g', 'writer': 'w', 'speaker': 's', 'route': 'image',
            'initial_action': 101, 'final_action': None, 'strict_success': False, 'execution_error': None,
            'initial_forecast_evaluated_against_actual_terminal_outcome': True},
            'DECISION_H2.json': {'decision': {'selected_action': 101, 'actual_mask': [True] * 102, 'raw_success': [.95] * 102}},
            'DECISION_H1.json': {'decision': {'selected_action': None, 'parent_outcome_digest': ex.digest('observation')}},
            'COMMITTED_EXTERNAL_AUDIO.json': {'outcome_digest': ex.digest('observation')},
            'EPISODE.json': {'initial_action': 101, 'policy': 'dynamic', 'actual_output_bundle': False}}
        for name, value in files.items():
            (path / name).write_text(json.dumps(value))
        identity = calibration.execution_identity(descriptor)
        labels = calibration.load_native([path], expected_execution_sha256=identity, source_role='old_fit',
                                         source_members={'g': [ex.digest('waveform')]})
        assert labels[0].operation == 'acquire' and labels[0].strict_success is False and labels[0].raw_probability == .95
        candidate = calibration.fit_selected(labels, execution_sha256=identity)
        assert candidate['later_failures_preserved'] == 1 and not candidate['qualified']
        heldout = [replace(labels[0], episode='new source', source_keys=('group:new', 'writer:new', 'speaker:new'),
                           source_role='old_development')]
        result = calibration.evaluate_selected(candidate, heldout)
        assert result['selected_terminal_ECE'] == 0. and result['strict_success_including_refusals'] == 0.
        assert rejected(lambda: calibration.evaluate_selected(candidate, [replace(labels[0], source_role='old_development')]))
        assert rejected(lambda: calibration.evaluate_selected(candidate,
            [replace(heldout[0], execution_sha256=ex.digest('changed admission'))]))
        assert calibration.frozen_pair(descriptor, candidate)['requires_new_actual_policy_replay']
    return {'acquire_then_refusal_target': 0, 'raw_initial_forecast': .95,
            'same_source_and_changed_policy_evaluations_rejected': True,
            'actual_new_native_episodes': 0, 'scope': 'Synthetic receipt fixture exercises real loader; no empirical qualification claimed.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    began = time.perf_counter_ns()
    result = {'schema': 'hepta.repair.execution-verification.v1', 'counterexamples': counterexamples(),
        'independent_policy_enumeration': enumerated(), 'terminal_calibration_targets': calibration_targets(),
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                          (Path(ex.__file__), Path(calibration.__file__), Path(__file__))},
        'elapsed_ns': time.perf_counter_ns() - began, 'passed': True,
        'future_native_owner_law_fitted': False, 'independent_qualification_passed': False}
    with args.output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
