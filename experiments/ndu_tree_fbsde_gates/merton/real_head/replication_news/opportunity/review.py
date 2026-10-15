"""Separate scalar training and exact-rational belief-tree audit; same author, no signer."""
from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from fractions import Fraction as Q
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from material_news import encode, loads, original, packet, sha, write
from audit_news import equal, reference, reference_row, scalar_softmax
from study import PROTOCOL_SHA, config, read_training, source_hashes


@lru_cache(None)
def rational_plan(curves, scenario_items, mode, history=()):
    """Independent exact arithmetic, recomputed posterior, all future counts."""
    s = dict(scenario_items)
    steps, sizes = (0, 8, 32, 128), (8, 8, 16)
    j = len(history)
    rates = [[Q(c+1, 18) for c in row] for row in curves]
    mass = []
    for row in rates:
        p = Q(1)
        for t, k in enumerate(history):
            n, chance = sizes[t], row[t+1]
            p *= math.comb(n, k)*chance**k*(1-chance)**(n-k)
        mass.append(p)
    total = sum(mass)
    mass = [v/total for v in mass]
    alpha = Q(0) if mode == 'neutral' else Q(1, 4)
    if mode == 'ndu':
        for k, n in zip(history, sizes):
            alpha += (1-2*Q(k, n))/8
            alpha = max(Q(0), min(Q(1, 2), alpha))
    vals = [s['horizon']*((1-alpha)*sum(p*row[t] for p, row in zip(mass, rates))+
                          alpha*min(row[t] for row in rates)) for t in range(j+1)]
    best = max(range(j+1), key=lambda t: (vals[t], -t))
    stop = vals[best]
    if j == 3 or steps[j+1] > s['budget']:
        return stop, stop, None, steps[best], None, str(alpha), tuple(mass)
    values, probabilities = [], []
    n = sizes[j]
    for k in range(n+1):
        prob = sum(p*math.comb(n, k)*row[j+1]**k*(1-row[j+1])**(n-k)
                   for p, row in zip(mass, rates))
        probabilities.append(prob)
        values.append(rational_plan(curves, scenario_items, mode, history+(k,))[0])
    cost = Q(s['step_fee'])*(steps[j+1]-steps[j])+Q(s['calibration_fee'])
    cont = (1-alpha)*sum(p*v for p, v in zip(probabilities, values))+alpha*min(values)-cost
    take = cont > stop
    return max(stop, cont), stop, cont, steps[best], steps[j+1] if take else None, str(alpha), tuple(mass)


@lru_cache(maxsize=8)
def scalar_fold(raw_rows, labels, train, valid):
    raw = [raw_rows[i] for i in train]
    n = len(raw)
    mean = [math.fsum(col)/n for col in zip(*raw)]
    scale = [max(1e-6, math.sqrt(math.fsum((x-m)**2 for x in col)/n)) for m, col in zip(mean, zip(*raw))]
    x = [reference_row(r, mean, scale) for r in raw]
    z = [reference_row(raw_rows[i], mean, scale) for i in valid]
    y = [labels[i] for i in train]
    columns = list(zip(*x))
    weights = [[0.]*4 for _ in range(385)]
    checkpoints, losses, counts = {}, [], []
    for t in range(129):
        if t in (0, 8, 32, 128):
            checkpoints[str(t)] = np.array(weights)
            correct = sum(max(range(4), key=lambda k: p[k]) == labels[i]
                          for i, p in zip(valid, (scalar_softmax(r, weights) for r in z)))
            counts.append(correct)
        if t == 128:
            break
        p = [scalar_softmax(r, weights) for r in x]
        losses.append(math.fsum(-math.log(row[label]) for row, label in zip(p, y))/n+
                      .0005*math.fsum(v*v for row in weights[:-1] for v in row))
        error = [[row[k]-int(k == label) for k in range(4)] for row, label in zip(p, y)]
        errors = list(zip(*error))
        weights = [[v-.1*(math.fsum(a*b for a, b in zip(columns[i], errors[k]))/n+
                          (.001*v if i < 384 else 0)) for k, v in enumerate(row)]
                   for i, row in enumerate(weights)]
    return mean, scale, checkpoints, losses, counts


def audit(archive, material, training, prior_path, run, output):
    c0, w0 = time.process_time_ns(), time.perf_counter_ns()
    cfg = config()
    a, receipt = packet(material/'worker.npz')
    raw_rows, original_x, parts = original(archive)
    for split, dest in (('train', 'train'), ('calibration', 'cal'), ('holdout', 'holdout')):
        idx = parts[split]
        if not np.array_equal(original_x[idx], a['x_'+dest]):
            raise ValueError('worker changed original features')
        if [raw_rows[i]['case_id'] for i in idx] != a[dest+'_ids'].tolist():
            raise ValueError('worker changed source identity')
        if split != 'holdout' and [raw_rows[i]['label'] for i in idx] != a['y_'+dest].tolist():
            raise ValueError('changed permitted source labels')
    x, y, ids = read_training(training)
    if not (np.array_equal(x, a['x_train']) and np.array_equal(y, a['y_train']) and np.array_equal(ids, a['train_ids'])):
        raise ValueError('prior-training packet mismatch')
    prior, seal = (loads(p.read_bytes()) for p in (prior_path, run/'sealed.json'))
    if (prior['training_sha256'] != sha(training.read_bytes()) or prior['calibration_or_holdout_used'] is not False
            or prior['actual_updates'] != 512 or prior['validation_calls'] != 16):
        raise ValueError('invalid or unpaid prior')
    for obj in (prior, seal):
        if obj['posture'] != 'RESEARCH_ONLY_DENY_ALL' or obj['source_sha256'] != source_hashes() or obj['protocol_sha256'] != PROTOCOL_SHA:
            raise ValueError('source, protocol or authority drift')
    if (seal['prior_sha256'] != sha(prior_path.read_bytes()) or seal['worker_sha256'] != receipt['worker_sha256']
            or seal['fresh_encoder_calls'] != 0 or seal['heldout_labels_loaded'] is not False):
        raise ValueError('invalid source/material claim')
    raw, yy = tuple(tuple(float(v) for v in row) for row in x), tuple(int(v) for v in y)
    order = sorted(range(64), key=lambda i: sha(str(ids[i]).encode()))
    if len(prior['rows']) != 4:
        raise ValueError('missing empirical curve')
    curves = []
    for f, row in enumerate(prior['rows']):
        valid = tuple(order[f::4]); train = tuple(i for i in range(64) if i not in valid)
        if (row['fold'] != f or row['train_ids'] != ids[list(train)].tolist() or row['valid_ids'] != ids[list(valid)].tolist()
                or row['actual_updates'] != 128 or row['validation_calls'] != 4):
            raise ValueError('fold identity, leakage or count mismatch')
        mean, scale, weights, losses, counts = scalar_fold(raw, yy, train, valid)
        for k in weights:
            equal(weights[k], row['checkpoints'][k])
        equal(mean, row['mean']); equal(scale, row['scale']); equal(losses, row['losses'])
        if counts != row['counts']:
            raise ValueError('empirical prior curve mismatch')
        curves.append(tuple(counts))
    curves = tuple(curves)
    if tuple(tuple(c) for c in prior['curves']) != curves:
        raise ValueError('prior rates not learned from recorded folds')
    mean, scale, ref_weights, ref_losses = reference(raw, yy)
    equal(mean, seal['mean']); equal(scale, seal['scale'])
    cal_x = [reference_row(r, mean, scale) for r in a['x_cal']]
    test_x = [reference_row(r, mean, scale) for r in a['x_holdout']]
    labels = [raw_rows[i]['label'] for i in parts['holdout']]
    expected_rows = {(repeat, s['name'], arm) for repeat in range(cfg['repeats']) for s in cfg['scenarios'] for arm in cfg['arms']}
    records = seal['rows']
    keys = [(r['repeat'], r['scenario'], r['arm']) for r in records]
    if len(keys) != len(set(keys)) or set(keys) != expected_rows:
        raise ValueError('incomplete or duplicate lifecycle panel')
    journal = (run/'journal.jsonl').read_bytes()
    if sha(journal) != seal['journal_sha256']:
        raise ValueError('journal tamper')
    expected_journal, results, decision_checks, numeric_checks = [], [], 0, 0
    cal_order = np.argsort(a['cal_hashes'], kind='stable').tolist()
    for row in records:
        s = next(s for s in cfg['scenarios'] if s['name'] == row['scenario'])
        if any(type(row[k]) is not int or row[k] < 0 for k in ('actual_steps', 'calibration_calls', 'cpu_ns', 'wall_ns')):
            raise ValueError('invalid lifecycle counters')
        if row['actual_steps'] > s['budget'] or row['holdout_ids'] != a['holdout_ids'].tolist():
            raise ValueError('budget or holdout identity mismatch')
        t, history, used, selected, waiting, authorized = 0, [], [], None, False, None
        training_active = False
        if not row['events'] or row['events'][0] != {'kind': 'start'}:
            raise ValueError('missing start')
        for i, e in enumerate(row['events']):
            expected_journal.append(encode({'repeat': row['repeat'], 'scenario': row['scenario'], 'arm': row['arm'], **e}))
            kind = e['kind']
            if kind == 'start':
                if i != 0: raise ValueError('duplicate start')
            elif kind == 'decision':
                if waiting or authorized is not None or selected is not None or e['history'] != history:
                    raise ValueError('decision before required observation or history drift')
                if row['arm'].startswith('belief_'):
                    mode = row['arm'][7:]
                    value, stop, cont, best, target, alpha, mass = rational_plan(curves, tuple(s.items()), mode, tuple(history))
                    equal(e['value'], float(value)); equal(e['stop_value'], float(stop)); equal(e['posterior'], [float(v) for v in mass])
                    if e['pruned']:
                        bound = s['horizon']*max(Q(c+1,18) for curve in curves for c in curve)
                        next_step = (8,32,128)[len(history)]
                        bound -= Q(s['step_fee'])*(next_step-t)+Q(s['calibration_fee'])
                        if cont is None or cont > bound or bound > stop or target is not None or e['continue_value'] is not None:
                            raise ValueError('inadmissible optimistic pruning')
                        equal(e['continue_value_upper_bound'],float(bound))
                    else:
                        if (cont is None) != (e['continue_value'] is None): raise ValueError('continuation support changed')
                        if cont is not None: equal(e['continue_value'], float(cont))
                    if e['alpha'] != alpha or e['selected_steps'] != best or e['to_step'] != target:
                        raise ValueError('nonoptimal model-relative decision')
                    if e['action'] != ('continue' if target is not None else 'stop'):
                        raise ValueError('action/target mismatch')
                    decision_checks += 1
                elif row['arm'] == 'slope_matched':
                    steps, sizes = (0, 8, 32, 128), (8, 8, 16)
                    j = len(history)
                    rates = [Q(1, 4)]+[Q(k,n) for k,n in zip(history,sizes)]
                    best = max(range(j+1), key=lambda z:(rates[z],-z))
                    target = None
                    if not history:
                        target = 8 if s['budget'] >= 8 else None
                    elif j < 3 and steps[j+1] <= s['budget']:
                        gain = max(Q(0), rates[-1]-rates[-2])*(steps[j+1]-steps[j])/(steps[j]-steps[j-1])
                        cost = Q(s['step_fee'])*(steps[j+1]-steps[j])+Q(s['calibration_fee'])
                        if s['horizon']*min(1-rates[best],gain) > cost: target = steps[j+1]
                    if e['selected_steps'] != steps[best] or e['to_step'] != target or e['action'] != ('continue' if target else 'stop'):
                        raise ValueError('same-observation slope decision drift')
                else:
                    wanted = 0 if row['arm'] == 'no_update' else int(row['arm'][5:])
                    target = wanted if t < wanted <= s['budget'] else None
                    if e['selected_steps'] != t or e['to_step'] != target or e['action'] != ('continue' if target else 'stop'):
                        raise ValueError('fixed comparator changed')
                if e['action'] == 'continue':
                    authorized = e['to_step']
                    if authorized is None or not t < authorized <= s['budget']: raise ValueError('bad training admission')
                elif e['action'] == 'stop':
                    selected = e['selected_steps']
                else: raise ValueError('unknown action')
            elif kind == 'train_start':
                if authorized != e['to_step'] or e['from_step'] != t or waiting or training_active: raise ValueError('unauthorized training')
                training_active = True
            elif kind == 'train_done':
                if e['actual_steps'] != authorized or not training_active: raise ValueError('unmatched completed update')
                training_active = False
                t = authorized; authorized = None
                if e['weights_sha256'] != sha(encode(row['checkpoints'][str(t)])): raise ValueError('weight journal mismatch')
                waiting = not row['arm'].startswith('fixed')
            elif kind == 'observation':
                if not waiting or e['step'] != t or len(history) >= 3: raise ValueError('unexpected calibration')
                size = (8, 8, 16)[len(history)]; offset = sum((8, 8, 16)[:len(history)])
                idx = cal_order[offset:offset+size]
                probs = [scalar_softmax(cal_x[z], ref_weights[t].tolist()) for z in idx]
                count = sum(max(range(4), key=lambda k: p[k]) == int(a['y_cal'][z]) for z, p in zip(idx, probs))
                if e['size'] != size or e['count'] != count or e['ids'] != a['cal_ids'][idx].tolist(): raise ValueError('calibration leak or wrong count')
                history.append(count); used += e['ids']; waiting = False
            elif kind == 'success':
                if i != len(row['events'])-1 or authorized is not None or waiting or selected is None: raise ValueError('premature success')
                if e['actual_steps'] != t or e['selected_steps'] != selected: raise ValueError('success count drift')
            else: raise ValueError('unknown event')
        if (row['actual_steps'] != t or row['history'] != history or row['selected_steps'] != selected
                or row['calibration_calls'] != len(history) or row['calibration_ids'] != used or len(set(used)) != len(used)):
            raise ValueError('physical lifecycle mismatch')
        if row['events'][-1]['kind'] != 'success' or str(selected) not in row['checkpoints']:
            raise ValueError('incomplete trace or unexecuted selection')
        for k, weights in row['checkpoints'].items():
            if int(k) > t: raise ValueError('future checkpoint stored')
            equal(weights, ref_weights[int(k)]); numeric_checks += 1
        equal(row['weights'], ref_weights[selected]); equal(row['losses'], ref_losses[:t])
        p = [scalar_softmax(r, ref_weights[selected].tolist()) for r in test_x]
        equal(row['probabilities'], p)
        pred = [max(range(4), key=lambda k: r[k]) for r in p]
        correct = sum(v == y for v, y in zip(pred, labels))
        fee = Q(s['step_fee'])*t + Q(s['calibration_fee'])*len(history)
        cold = Q(s['step_fee'])*512 + Q(s['calibration_fee'])*16 if row['arm'].startswith('belief_') else Q(0)
        net = s['horizon']*Q(correct, 32)-fee
        results.append({'repeat': row['repeat'], 'scenario': s['name'], 'arm': row['arm'], 'correct': correct,
                        'selected_steps': selected, 'actual_steps': t, 'calibration_calls': len(history),
                        'online_net': str(net), 'cold_start_net': str(net-cold),
                        'cpu_ms': row['cpu_ns']/1e6, 'cold_start_cpu_ms': (row['cpu_ns']+(prior['cpu_ns'] if cold else 0))/1e6})
    if journal.splitlines() != expected_journal:
        raise ValueError('journal order or per-row correspondence changed')
    # Train-only leave-one-curve-out diagnosis, not independent task validation.
    errors = [abs(sum((curves[g][t]+1)/18 for g in range(4) if g != f)/3-curves[f][t]/16)
              for f in range(4) for t in range(4)]
    summaries = []
    for s in cfg['scenarios']:
        for arm in cfg['arms']:
            rr = [r for r in results if r['scenario'] == s['name'] and r['arm'] == arm]
            if any({k:v for k,v in r.items() if k not in ('repeat','cpu_ms','cold_start_cpu_ms')} !=
                   {k:v for k,v in rr[0].items() if k not in ('repeat','cpu_ms','cold_start_cpu_ms')} for r in rr):
                raise ValueError('deterministic policy changed across timing repetitions')
            summaries.append({**{k:v for k,v in rr[0].items() if k not in ('repeat','cpu_ms','cold_start_cpu_ms')},
                              'median_cpu_ms': statistics.median(r['cpu_ms'] for r in rr),
                              'median_cold_start_cpu_ms': statistics.median(r['cold_start_cpu_ms'] for r in rr)})
    report = {'schema': 'hepta.merton.opportunity-audit.v1', 'posture': 'RESEARCH_ONLY_DENY_ALL',
              'seal_sha256': sha((run/'sealed.json').read_bytes()), 'source_sha256': source_hashes(),
              'prior_curves': curves, 'prior_updates': 512, 'prior_validation_calls': 16,
              'train_only_curve_loo_mae': statistics.mean(errors), 'train_only_curve_loo_max_error': max(errors),
              'verified_lifecycles': len(results), 'model_decision_checks': decision_checks,
              'checkpoint_checks': numeric_checks, 'online_updates': sum(r['actual_steps'] for r in results),
              'cold_start_cost_not_amortized_by_hypothetical_horizon': True,
              'new_sources': 0, 'independent_story_families': None, 'fresh_encoder_calls': 0,
              'production_accepted': False, 'ndu_superiority_established': False,
              'optimal_only_in_fitted_model': True, 'reliable_future_roi_established': False,
              'summaries': summaries, 'rows': results, 'audit_cpu_ns': time.process_time_ns()-c0,
              'audit_wall_ns': time.perf_counter_ns()-w0}
    write(output, report)
    print(encode({'verified_lifecycles': len(results), 'model_decisions': decision_checks,
                  'checkpoints': numeric_checks, 'online_updates': report['online_updates']}).decode())
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'material', 'training', 'prior', 'run', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    audit(a.archive, a.material, a.training, a.prior, a.run, a.output)
