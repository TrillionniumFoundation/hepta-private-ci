"""Separated train-only -> label-blind warm starts -> independent E12 scoring.

All source families are synthetic x0 variants of one finite E12 law. Real
pretrained encoders, independently observed tasks and FinalUse are absent.
"""

import argparse
from dataclasses import asdict, fields
from fractions import Fraction as Q
from hashlib import sha256
import json
from pathlib import Path
from time import process_time_ns

from e12_nonlinear_cert import Law, solve
from e12_independent_audit import audit, reference, round_even
from e12_local_cell_solver import _paths
from e12_continuation_field import (
    EPOCHS, RATE, WIDTH, FrozenHead, features, fit_head, initial_y,
    solve_warm, training_rows,
)
from e12_study import PROFILES, read_strict, write_once

SCHEMA = 'hepta.e12.learned-continuation-field.v1'
TRAIN_X0 = tuple(Q(k, 10) for k in range(-18, 19, 2))
CAL_X0 = tuple(Q(k, 20) for k in (-33, -25, -17, -9, 9, 17, 25, 33))
# New unexamined source IDs, frozen independently of the preceding exploratory
# interpolation panel (-37...37)/20. No claims of future calendar windows.
HELD_X0 = tuple(Q(k, 64) for k in (-119, -103, -87, -71, -55, 55, 71, 87, 103, 119))
ARMS = ('zero', 'constant', 'linear', 'neural')


def _check_splits() -> None:
    if (set(TRAIN_X0) & set(CAL_X0) or set(TRAIN_X0) & set(HELD_X0) or
        set(CAL_X0) & set(HELD_X0) or
        len(TRAIN_X0) != 19 or len(CAL_X0) != 8 or len(HELD_X0) != 10):
        raise ValueError('source identity leakage or altered study split')


def _plan() -> dict:
    _check_splits()
    return {'schema': SCHEMA, 'law_profiles': [list(v) for v in PROFILES],
            'train_x0': list(map(str, TRAIN_X0)),
            'calibration_x0': list(map(str, CAL_X0)),
            'held_x0': list(map(str, HELD_X0)),
            'seed': 1729, 'epochs': EPOCHS, 'learning_rate': RATE,
            'hidden_width': WIDTH, 'precision': 'FP64-SGD+Q16-initial-guess',
            'model_source_sha256': sha256(
                Path(__file__).with_name('e12_continuation_field.py').read_bytes()
            ).hexdigest()}


def _plan_digest() -> str:
    return sha256(json.dumps(_plan(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _rows_for_groups(groups: tuple[Q, ...]):
    rows = []
    teacher_solves = 0
    teacher_sweeps = 0
    start = process_time_ns()
    for x0 in groups:
        for depth, a in PROFILES:
            law = Law(depth=depth, a=a, x0=str(x0))
            teacher = solve(law)
            if not audit(law, teacher).certified:
                raise ValueError('independent original E12 mathematical teacher invalid')
            n = (1 << depth) - 1
            rows.extend(training_rows(law, tuple(Q(v.y) for v in teacher.trace.states[:n])))
            teacher_solves += 1
            teacher_sweeps += teacher.evaluations
    return tuple(rows), teacher_solves, teacher_sweeps, max(1, process_time_ns() - start)


def _decode_head(data: dict, expected_kind: str) -> FrozenHead:
    if type(data) is not dict or set(data) != {f.name for f in fields(FrozenHead)}:
        raise ValueError('missing/extra head tensors or authority')
    rec = dict(data)
    if (type(rec['hidden']) is not list or
        any(type(w) is not list for w in rec['hidden']) or
        type(rec['hidden_bias']) is not list or type(rec['readout']) is not list):
        raise ValueError('untyped head tensors')
    rec['hidden'] = tuple(tuple(w) for w in rec['hidden'])
    rec['hidden_bias'] = tuple(rec['hidden_bias'])
    rec['readout'] = tuple(rec['readout'])
    head = FrozenHead(**rec)
    head.validate()
    if head.kind != expected_kind:
        raise ValueError('head identity substituted')
    return head


def _read_training(path: str, expected_sha: str) -> tuple[dict, dict]:
    data, digest = read_strict(path)
    if (type(expected_sha) is not str or digest != expected_sha or
        type(data) is not dict or set(data) != {
            'schema', 'plan_digest', 'train_only_teacher_solves', 'teacher_sweeps',
            'teacher_cpu_ns', 'rows', 'heads', 'authority', 'held_labels_opened',
            'source_owner_authenticated', 'production_accepted',
        } or data['schema'] != SCHEMA + '.train' or
        data['plan_digest'] != _plan_digest() or data['authority'] != 'DENY_ALL' or
        data['held_labels_opened'] is not False or
        data['source_owner_authenticated'] is not False or
        data['production_accepted'] is not False or
        type(data['train_only_teacher_solves']) is not int or
        data['train_only_teacher_solves'] != len(TRAIN_X0) * len(PROFILES) or
        type(data['teacher_sweeps']) is not int or data['teacher_sweeps'] < 1 or
        type(data['teacher_cpu_ns']) is not int or data['teacher_cpu_ns'] <= 0 or
        type(data['rows']) is not int or data['rows'] != len(TRAIN_X0) * 22 or
        type(data['heads']) is not dict or set(data['heads']) != set(ARMS) - {'zero'}):
        raise ValueError('invalid train-only immutable evidence')
    heads = {kind: _decode_head(data['heads'][kind], kind) for kind in ARMS[1:]}
    if any(h.train_rows != data['rows'] for h in heads.values()):
        raise ValueError('reduced or fabricated training support')
    return data, heads


def train(output: str) -> str:
    _check_splits()
    rows, solves, sweeps, cpu = _rows_for_groups(TRAIN_X0)
    if len(rows) != len(TRAIN_X0) * 22:
        raise ValueError('incomplete original tree train inventory')
    heads = {kind: asdict(fit_head(rows, kind)) for kind in ARMS[1:]}
    return write_once(output, {
        'schema': SCHEMA + '.train', 'plan_digest': _plan_digest(),
        'train_only_teacher_solves': solves, 'teacher_sweeps': sweeps,
        'teacher_cpu_ns': cpu, 'rows': len(rows), 'heads': heads,
        'authority': 'DENY_ALL', 'held_labels_opened': False,
        'source_owner_authenticated': False, 'production_accepted': False,
    })


def propose(training_file: str, training_sha: str, output: str) -> str:
    _train, heads = _read_training(training_file, training_sha)
    cases = []
    for x0 in HELD_X0:
        for depth, coupling in PROFILES:
            law = Law(depth=depth, a=coupling, x0=str(x0))
            arms = []
            for kind in ARMS:
                start = process_time_ns()
                guess = initial_y(law, heads.get(kind))
                start_math = process_time_ns()
                result = solve_warm(law, guess)
                initialization = max(1, start_math - start)
                total = max(1, process_time_ns() - start)
                arms.append({'name': kind, 'candidate': asdict(result),
                             'initial_head_cpu_ns': initialization,
                             'total_cpu_ns': max(total, initialization + result.cpu_ns),
                             'head_forward_calls': 0 if kind == 'zero' else len(guess)})
            cases.append({'source': str(x0), 'depth': depth, 'coupling': coupling,
                          'arms': arms})
    return write_once(output, {
        'schema': SCHEMA + '.blind', 'plan_digest': _plan_digest(),
        'train_sha256': training_sha, 'held_roster': [str(v) for v in HELD_X0],
        'authority': 'DENY_ALL', 'cases': cases,
        'held_truth_or_reference_accessed': False,
        'global_solution_calls': 0, 'pretrained_model_forwards': 0,
        'natural_task_gain_proven': False, 'production_accepted': False,
    })


def _verify_warm(law: Law, candidate: dict, guess: tuple[Q, ...]) -> tuple[int, Q]:
    """Independent prefix-dictionary replay, never imports producer local sweep."""
    if type(candidate) is not dict or set(candidate) != {
        'law', 'trace', 'initial_y', 'final_y', 'residual',
        'rigorous_error_bound', 'contraction_q', 'iterations',
        'node_updates', 'cpu_ns', 'policy',
    } or candidate['law'] != asdict(law) or candidate['policy'] != 'DENY_ALL':
        raise ValueError('untrusted/wrong warm candidate schema')
    p = law.values()
    n = (1 << law.depth) - 1
    if (candidate['initial_y'] != list(map(str, guess)) or
        type(candidate['iterations']) is not int or not 1 <= candidate['iterations'] <= 24 or
        type(candidate['node_updates']) is not int or
        candidate['node_updates'] != candidate['iterations'] * 2 * n or
        type(candidate['cpu_ns']) is not int or candidate['cpu_ns'] <= 0 or
        candidate['contraction_q'] != str(p['q'])):
        raise ValueError('forged start/contraction or work')
    y = guess
    for step in range(1, candidate['iterations'] + 1):
        xvals, uvals, mapped = reference(law, y)
        residual = max(abs(l - r) for l, r in zip(y, mapped))
        bound = residual / (1 - p['q'])
        if bound <= Q(1, 10000):
            if step != candidate['iterations']:
                raise ValueError('prematurely extended warm run')
            break
        if step == candidate['iterations']:
            raise ValueError('ended without globally qualified residual')
        y = tuple(round_even(v, 16) for v in mapped)
    if (candidate['final_y'] != list(map(str, y)) or
        candidate['residual'] != str(residual) or
        candidate['rigorous_error_bound'] != str(bound)):
        raise ValueError('global certificate differs from independent replay')
    trace = candidate['trace']
    if (type(trace) is not dict or set(trace) != {'states', 'z'} or
        type(trace['states']) is not list or len(trace['states']) != 2 * n + 1 or
        type(trace['z']) is not list or len(trace['z']) != n):
        raise ValueError('missing entire public stochastic tree')
    keys = tuple(tuple(-1 if ((i >> (d-1-b)) & 1) == 0 else 1 for b in range(d))
                 for d in range(law.depth+1) for i in range(1 << d))
    nodes = tuple(trace['states'])
    if any(type(v) is not dict or set(v) != {'x','y'} for v in nodes):
        raise ValueError('untyped trace state')
    for i, key in enumerate(keys):
        want_y = y[i] if i < n else uvals[key]
        if nodes[i] != {'x': str(xvals[key]), 'y': str(want_y)}:
            raise ValueError('forward/backward interface or terminal mismatch')
    for i, key in enumerate(keys[:n]):
        # Verify the conditional martingale Z against the ACTUAL recorded
        # candidate-child values, never against the mapped values alone.
        left = Q(nodes[2*i+1]['y'])
        right = Q(nodes[2*i+2]['y'])
        if trace['z'][i] != str((right-left)/(2*p['s'])):
            raise ValueError('wrong conditional Z or missing martingale')
    return candidate['node_updates'], bound


def score(training_file: str, training_sha: str, blind_file: str,
          blind_sha: str, output: str) -> str:
    train_record, heads = _read_training(training_file, training_sha)
    # Replay complete train-only parameter learning deterministically. This is
    # same-algorithm replay, NOT independent optimizer implementation.
    rows, count, sweeps, _ = _rows_for_groups(TRAIN_X0)
    if count != train_record['train_only_teacher_solves'] or sweeps != train_record['teacher_sweeps']:
        raise ValueError('historical train-source inventory changed')
    for kind, head in heads.items():
        retrained = fit_head(rows, kind)
        if (head.kind, head.hidden, head.hidden_bias, head.readout, head.out_bias,
            head.train_rows, head.updates) != (
            retrained.kind, retrained.hidden, retrained.hidden_bias,
            retrained.readout, retrained.out_bias, retrained.train_rows,
            retrained.updates):
            raise ValueError('non-replayable learned parameters')
    blind, digest = read_strict(blind_file, size_limit=2_000_000)
    if (type(blind_sha) is not str or digest != blind_sha or
        type(blind) is not dict or set(blind) != {
            'schema','plan_digest','train_sha256','held_roster','authority','cases',
            'held_truth_or_reference_accessed','global_solution_calls',
            'pretrained_model_forwards','natural_task_gain_proven','production_accepted',
        } or blind['schema'] != SCHEMA + '.blind' or
        blind['plan_digest'] != _plan_digest() or blind['train_sha256'] != training_sha or
        blind['held_roster'] != list(map(str, HELD_X0)) or blind['authority'] != 'DENY_ALL' or
        blind['held_truth_or_reference_accessed'] is not False or
        type(blind['global_solution_calls']) is not int or blind['global_solution_calls'] != 0 or
        type(blind['pretrained_model_forwards']) is not int or blind['pretrained_model_forwards'] != 0 or
        blind['natural_task_gain_proven'] is not False or
        blind['production_accepted'] is not False or
        type(blind['cases']) is not list or len(blind['cases']) != len(HELD_X0) * len(PROFILES)):
        raise ValueError('forged/missing blind proposal inventory')
    cheap = {'uncoupled_exact_cases': 0, 'direct_cell_updates': 0,
             'coupled_one_map_uncertified': 0, 'reviewer_direct_cpu_ns': 0}
    summary = {kind: {'cases': 0, 'cell_updates': 0, 'solver_cpu_ns': 0,
                      'inclusive_cpu_ns': 0, 'head_calls': 0, 'root_squared_error': 0.0}
               for kind in ARMS}
    for case, (x0, (depth, coupling)) in zip(blind['cases'],
                                            ((x, p) for x in HELD_X0 for p in PROFILES)):
        law = Law(depth=depth, a=coupling, x0=str(x0))
        if (type(case) is not dict or set(case) != {'source','depth','coupling','arms'} or
            case['source'] != str(x0) or type(case['depth']) is not int or
            case['depth'] != depth or case['coupling'] != coupling or
            type(case['arms']) is not list or len(case['arms']) != len(ARMS)):
            raise ValueError('changed evaluation source or policy arms')
        # Held oracle is first opened only AFTER blind source SHA verification.
        teacher = solve(law)
        if not audit(law, teacher).certified:
            raise ValueError('independent original global E12 held oracle rejected')
        # Cheapest exact Bellman/BSDE control for the a=0 special case:
        # one complete backward map is already the unique solution. Coupled
        # one-map results require a SECOND paid map to certify residual and
        # are not claimed correct when outside tolerance.
        count_nodes = (1 << depth) - 1
        base = (Q(0),) * count_nodes
        t0 = process_time_ns()
        _cx, _cy, cheap_one = reference(law, base)
        cheap['reviewer_direct_cpu_ns'] += max(1, process_time_ns() - t0)
        if coupling == '0':
            cheap['uncoupled_exact_cases'] += 1
            cheap['direct_cell_updates'] += 2 * count_nodes
            if reference(law, cheap_one)[2] != cheap_one:
                raise ValueError('uncoupled exact direct map unexpectedly failed')
        else:
            second = reference(law, cheap_one)[2]
            gap = max(abs(l-r) for l, r in zip(cheap_one, second))
            if gap / (1 - law.values()['q']) > Q(1, 10000):
                cheap['coupled_one_map_uncertified'] += 1
        target = Q(teacher.trace.states[0].y)
        for arm, kind in zip(case['arms'], ARMS):
            if (type(arm) is not dict or set(arm) != {
                'name','candidate','initial_head_cpu_ns','total_cpu_ns','head_forward_calls',
            } or arm['name'] != kind or
                type(arm['initial_head_cpu_ns']) is not int or arm['initial_head_cpu_ns'] <= 0 or
                type(arm['total_cpu_ns']) is not int or
                arm['total_cpu_ns'] < arm['initial_head_cpu_ns'] or
                type(arm['head_forward_calls']) is not int or
                arm['head_forward_calls'] != (0 if kind == 'zero' else (1 << depth) - 1)):
                raise ValueError('forged paid model or work record')
            checked_updates, bound = _verify_warm(law, arm['candidate'],
                                                   initial_y(law, heads.get(kind)))
            if arm['total_cpu_ns'] < (arm['initial_head_cpu_ns'] + arm['candidate']['cpu_ns']):
                raise ValueError('missing paid FBSDE and prediction work')
            s = summary[kind]
            s['cases'] += 1
            s['cell_updates'] += checked_updates
            s['solver_cpu_ns'] += arm['candidate']['cpu_ns']
            s['inclusive_cpu_ns'] += arm['total_cpu_ns']
            s['head_calls'] += arm['head_forward_calls']
            root_y = Q(arm['candidate']['final_y'][0])
            s['root_squared_error'] += float((root_y-target)**2)
    for name, stat in summary.items():
        stat['fit_cpu_ns'] = 0 if name == 'zero' else heads[name].fit_cpu_ns
        stat['teacher_cpu_ns_attributed'] = 0 if name == 'zero' else train_record['teacher_cpu_ns']
        stat['one_panel_training_plus_inference_cpu_ns'] = (stat['fit_cpu_ns'] +
            stat['teacher_cpu_ns_attributed'] + stat['inclusive_cpu_ns'])
        stat['params_fp64'] = (0 if name == 'zero' else
             1 if name == 'constant' else 11 if name == 'linear' else 145)
    return write_once(output, {
        'schema': SCHEMA + '.independent-score', 'train_sha256': training_sha,
        'blind_sha256': digest, 'source_groups_held': len(HELD_X0),
        'cases_per_arm': len(HELD_X0) * len(PROFILES),
        'all_e12_discrete_global_certificates_replayed': True,
        'learning_replayed_using_same_algorithm': True,
        'summary': summary, 'cheap_direct_special_case': cheap,
        'cheap_direct_cost_scope': 'reviewer-process-only-not-matched-proposer',
        'authority': 'DENY_ALL',
        'pretrained_model_forwards': 0, 'independent_natural_task_outcomes': False,
        'cost_adjusted_online_reasoning_gain_qualified': False,
        'model_selected': False, 'production_accepted': False,
    })


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='mode', required=True)
    t = sub.add_parser('train');t.add_argument('--output', required=True)
    p = sub.add_parser('blind');p.add_argument('--train', required=True)
    p.add_argument('--train-sha256', required=True);p.add_argument('--output', required=True)
    s = sub.add_parser('score');s.add_argument('--train', required=True)
    s.add_argument('--train-sha256', required=True)
    s.add_argument('--blind', required=True);s.add_argument('--blind-sha256', required=True)
    s.add_argument('--output', required=True)
    args = ap.parse_args()
    digest = (train(args.output) if args.mode == 'train' else
              propose(args.train, args.train_sha256, args.output) if args.mode == 'blind' else
              score(args.train, args.train_sha256, args.blind, args.blind_sha256, args.output))
    print(json.dumps({'mode': args.mode, 'sha256': digest, 'authority': 'DENY_ALL'}, sort_keys=True))


if __name__ == '__main__':
    main()
