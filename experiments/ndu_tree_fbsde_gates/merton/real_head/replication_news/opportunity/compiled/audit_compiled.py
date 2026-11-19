"""Independent rational policy and scalar training replay; no external signer."""
from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from fractions import Fraction as Q
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))
from audit_news import equal, reference, reference_row, scalar_softmax
from material_news import encode, loads, original, packet, sha, write
from review import rational_plan, scalar_fold
from study import config as parent_config, read_training
from compile_policy import MODES, SharedPolicy, incremental_break_even, key, sources
from benchmark import config


def verify_table(data):
    """Prove every reachable stored decision against the separate exact solver."""
    curves = tuple(tuple(c) for c in data['curves'])
    checks = 0
    for s in data['scenarios']:
        for mode in MODES:
            for k, d in data['tables'][s['name']+'/'+mode].items():
                h = tuple(int(v) for v in k.split(',')) if k else ()
                value, stop, cont, selected, target, alpha, mass = rational_plan(curves, tuple(s.items()), mode, h)
                equal(d['value'], float(value)); equal(d['stop_value'], float(stop))
                equal(d['posterior'], [float(v) for v in mass])
                if (d['selected_steps'], d['to_step'], d['alpha'], d['action']) != (selected, target, alpha, 'stop' if target is None else 'continue'):
                    raise ValueError('compiled choice differs from exact independent policy')
                if d['pruned']:
                    t = (0, 8, 32, 128)[len(h)]; nxt = (8, 32, 128)[len(h)]
                    bound = s['horizon']*max(Q(v+1, 18) for c in curves for v in c)-Q(s['step_fee'])*(nxt-t)-Q(s['calibration_fee'])
                    equal(d['continue_value_upper_bound'], float(bound))
                    if cont is None or cont > bound or bound > stop or d['continue_value'] is not None:
                        raise ValueError('invalid compiled pruning bound')
                elif cont is not None:
                    equal(d['continue_value'], float(cont))
                elif d['continue_value'] is not None:
                    raise ValueError('fabricated continuation')
                checks += 1
    return checks


def verify_prior(raw, labels, ids, prior):
    order = sorted(range(64), key=lambda i: sha(str(ids[i]).encode()))
    x = tuple(tuple(float(v) for v in row) for row in raw)
    y = tuple(int(v) for v in labels)
    if len(prior['rows']) != 4 or prior['actual_updates'] != 512 or prior['validation_calls'] != 16:
        raise ValueError('missing or unpaid empirical prior')
    for f, row in enumerate(prior['rows']):
        valid = tuple(order[f::4]); train = tuple(i for i in range(64) if i not in valid)
        if row['train_ids'] != ids[list(train)].tolist() or row['valid_ids'] != ids[list(valid)].tolist():
            raise ValueError('prior data leakage or identity drift')
        mean, scale, weights, loss, counts = scalar_fold(x, y, train, valid)
        equal(mean, row['mean']); equal(scale, row['scale']); equal(loss, row['losses'])
        for t in weights:
            equal(weights[t], row['checkpoints'][t])
        if row['counts'] != counts or prior['curves'][f] != counts:
            raise ValueError('incorrect empirical prior')
    return 16


def audit(archive, material, run, output):
    c0, w0 = time.process_time_ns(), time.perf_counter_ns()
    a, receipt = packet(material/'worker.npz')
    source_rows, original_x, parts = original(archive)
    for src, dest in (('train', 'train'), ('calibration', 'cal'), ('holdout', 'holdout')):
        ix = parts[src]
        if not np.array_equal(a['x_'+dest], original_x[ix]) or a[dest+'_ids'].tolist() != [source_rows[i]['case_id'] for i in ix]:
            raise ValueError('original source mismatch')
        if src != 'holdout' and a['y_'+dest].tolist() != [source_rows[i]['label'] for i in ix]:
            raise ValueError('original permitted labels changed')
    seal = loads((run/'sealed.json').read_bytes())
    prior = loads((run/'prior.json').read_bytes())
    data = loads((run/'policy.json').read_bytes())
    if seal['schema'] != 'hepta.merton.shared-benchmark.v1' or seal['posture'] != 'RESEARCH_ONLY_DENY_ALL':
        raise ValueError('bad run schema or authority')
    if seal['source_sha256'] != sources() or seal['protocol_sha256'] != sha((HERE/'protocol.json').read_bytes()):
        raise ValueError('code or protocol drift')
    if (seal['worker_sha256'] != receipt['worker_sha256'] or seal['prior_sha256'] != sha((run/'prior.json').read_bytes())
            or seal['prior_fits_physically_executed'] != 1 or seal['prior_updates'] != 512
            or seal['shared_table_owners'] != 1 or seal['heldout_labels_loaded'] is not False
            or seal['fresh_encoder_calls'] != 0 or seal['new_sources'] != 0):
        raise ValueError('source binding, physical census or claim changed')
    asset = SharedPolicy(run/'policy.json', seal['compilation']['asset_sha256'], receipt['worker_sha256'], seal['prior_sha256'])
    if data['curves'] != prior['curves']:
        raise ValueError('compiled model not original prior')
    table_checks = verify_table(data)
    if table_checks != seal['compilation']['stored_decisions'] or asset.serialized_bytes != seal['compilation']['serialized_bytes']:
        raise ValueError('compiled work census mismatch')
    tx, ty, tids = read_training(run/'train.npz')
    if not (np.array_equal(tx, a['x_train']) and np.array_equal(ty, a['y_train']) and np.array_equal(tids, a['train_ids'])):
        raise ValueError('wrong prior training packet')
    if prior['training_sha256'] != sha((run/'train.npz').read_bytes()):
        raise ValueError('training binding mismatch')
    prior_checks = verify_prior(tx, ty, tids, prior)
    raw = tuple(tuple(float(v) for v in row) for row in tx); labels = tuple(int(v) for v in ty)
    mean, scale, weights, losses = reference(raw, labels)
    weights = {str(k): v for k, v in weights.items()}
    equal(mean, seal['mean']); equal(scale, seal['scale'])
    cal = {t: [scalar_softmax(reference_row(row, mean, scale), weights[str(t)]) for row in a['x_cal']]
           for t in (0, 8, 32, 128)}
    hold = {t: [scalar_softmax(reference_row(row, mean, scale), weights[str(t)]) for row in a['x_holdout']]
            for t in (0, 8, 32, 128)}
    truth = [source_rows[i]['label'] for i in parts['holdout']]
    if a['cal_hashes'].tolist() != [sha(source_rows[i]['text'].encode()) for i in parts['calibration']]:
        raise ValueError('calibration ordering changed')
    cal_order = np.argsort(a['cal_hashes'], kind='stable').tolist()
    expected_keys = {(r, s['name'], arm) for r in range(config()['repeats']) for s in parent_config()['scenarios'] for arm in config()['arms']}
    keys = [(r['repeat'], r['scenario'], r['arm']) for r in seal['rows']]
    if len(keys) != len(set(keys)) or set(keys) != expected_keys:
        raise ValueError('missing or duplicate lifecycle')
    expected_journal, records, numeric_checks = [], [], 0
    for row in seal['rows']:
        s = next(s for s in parent_config()['scenarios'] if s['name'] == row['scenario'])
        arm = row['arm']; fixed = arm in ('no_update', 'fixed8', 'fixed32')
        for counter in ('cpu_ns', 'wall_ns', 'actual_steps', 'calibration_calls', 'solver_constructions', 'online_model_nodes'):
            if type(row[counter]) is not int or row[counter] < 0:
                raise ValueError('invalid physical counters')
        if row['solver_constructions'] != int(arm.startswith('solve_')) or (not arm.startswith('solve_') and row['online_model_nodes'] != 0):
            raise ValueError('hidden online solver or false counting')
        events = [{'kind': 'start'}]; history = []; t = 0; consumed = []; seen = {0}
        while True:
            if fixed:
                dest = 0 if arm == 'no_update' else int(arm[5:])
                take = t < dest <= s['budget']
                d = {'action': 'continue' if take else 'stop', 'to_step': dest if take else None,
                     'selected_steps': t, 'reason': 'fixed_schedule'}
            else:
                mode = arm.split('_', 1)[1]
                d = data['tables'][s['name']+'/'+mode][key(history)]
            events.append({'kind': 'decision', 'history': list(history), 'actual_steps': t, **d})
            if d['action'] == 'stop':
                selected = d['selected_steps']; break
            target = d['to_step']; events.append({'kind': 'train_start', 'from_step': t, 'to_step': target})
            if str(target) not in row['checkpoints']:
                raise ValueError('missing executed checkpoint')
            equal(row['checkpoints'][str(target)], weights[str(target)])
            numeric_checks += 1; seen.add(target); t = target
            events.append({'kind': 'train_done', 'actual_steps': t, 'weights_sha256': sha(encode(row['checkpoints'][str(t)]))})
            if not fixed:
                n = (8, 8, 16)[len(history)]; offset = sum((8, 8, 16)[:len(history)])
                ix = cal_order[offset:offset+n]
                count = sum(max(range(4), key=lambda k: cal[t][i][k]) == int(a['y_cal'][i]) for i in ix)
                ids = a['cal_ids'][ix].tolist(); history.append(count); consumed.extend(ids)
                events.append({'kind': 'observation', 'step': t, 'count': count, 'size': n, 'ids': ids})
        events.append({'kind': 'success', 'actual_steps': t, 'selected_steps': selected})
        if (events != row['events'] or row['actual_steps'] != t or row['selected_steps'] != selected
                or row['history'] != history or row['calibration_calls'] != len(history) or row['calibration_ids'] != consumed
                or set(row['checkpoints']) != {str(v) for v in seen} or t > s['budget']):
            raise ValueError('unexecuted, unpriced or out-of-order work')
        equal(row['checkpoints']['0'], weights['0']); equal(row['weights'], weights[str(selected)])
        equal(row['losses'], losses[:t]); equal(row['probabilities'], hold[selected])
        if row['holdout_ids'] != a['holdout_ids'].tolist():
            raise ValueError('heldout identity drift')
        predicted = [max(range(4), key=lambda k: p[k]) for p in row['probabilities']]
        correct = [int(pred == gold) for pred, gold in zip(predicted, truth)]
        fee = Q(s['step_fee'])*t+Q(s['calibration_fee'])*len(history)
        for phase in row['phases']:
            if set(phase) != {'kind', 'cpu_ns', 'wall_ns'} or phase['kind'] not in ('decision', 'fit', 'calibration', 'prediction'):
                raise ValueError('unknown measured phase')
            if any(type(phase[k]) is not int or phase[k] < 0 for k in ('cpu_ns', 'wall_ns')):
                raise ValueError('invalid phase clock')
        if sum(p['cpu_ns'] for p in row['phases']) > row['cpu_ns']:
            raise ValueError('omitted phase cost')
        decision_cpu = sum(p['cpu_ns'] for p in row['phases'] if p['kind'] == 'decision')
        records.append({'arm': arm, 'repeat': row['repeat'], 'scenario': s['name'], 'correct': sum(correct),
                        'correct_vector': correct, 'selected_steps': selected, 'actual_steps': t,
                        'calibration_calls': len(history), 'online_cpu_ns': row['cpu_ns'],
                        'decision_cpu_ns': decision_cpu, 'net_declared_tariff': str(s['horizon']*Q(sum(correct), 32)-fee)})
        expected_journal.extend(encode({'repeat': row['repeat'], 'scenario': s['name'], 'arm': arm, **e}) for e in events)
    journal = (run/'journal.jsonl').read_bytes()
    if sha(journal) != seal['journal_sha256'] or journal != b'\n'.join(expected_journal)+b'\n':
        raise ValueError('durable journal differs from validated work')
    paired = 0
    for row in seal['rows']:
        if row['arm'].startswith('shared_'):
            other = next(r for r in seal['rows'] if (r['repeat'], r['scenario'], r['arm']) == (row['repeat'], row['scenario'], 'solve_'+row['arm'][7:]))
            for field in ('events', 'weights', 'checkpoints', 'losses', 'probabilities', 'actual_steps', 'calibration_ids'):
                if row[field] != other[field]:
                    raise ValueError('sharing changed decisions, training or predictions')
            paired += 1
    summaries = []
    for arm in config()['arms']:
        group = [r for r in records if r['arm'] == arm and r['scenario'] == 'unit_low']
        summaries.append({'arm': arm, 'correct': group[0]['correct'], 'actual_steps': group[0]['actual_steps'],
                          'calibration_calls': group[0]['calibration_calls'],
                          'median_online_cpu_ns': statistics.median(r['online_cpu_ns'] for r in group),
                          'median_decision_cpu_ns': statistics.median(r['decision_cpu_ns'] for r in group)})
    lookup = {r['arm']: r for r in summaries}
    setup_cost = seal['compilation']['cpu_ns']+seal['loading']['cpu_ns']
    break_even = {}
    for mode in ('neutral', 'ndu'):
        dense = lookup['solve_'+mode]['median_online_cpu_ns']; shared = lookup['shared_'+mode]['median_online_cpu_ns']
        break_even[mode] = incremental_break_even(setup_cost, dense, shared)
    base_net = next(Q(r['net_declared_tariff']) for r in records if r['scenario'] == 'unit_low' and r['arm'] == 'fixed8')
    shared_net = next(Q(r['net_declared_tariff']) for r in records if r['scenario'] == 'unit_low' and r['arm'] == 'shared_ndu')
    marginal_tariff_delta = shared_net-base_net
    unit_shared = next(r for r in seal['rows'] if r['scenario'] == 'unit_low' and r['arm'] == 'shared_ndu')
    unit_fixed = next(r for r in seal['rows'] if r['scenario'] == 'unit_low' and r['arm'] == 'fixed8')
    same_fixed_predictions = unit_shared['probabilities'] == unit_fixed['probabilities']
    actual_online = sum(r['actual_steps'] for r in records)
    if actual_online != seal['actual_online_updates']:
        raise ValueError('formal update census mismatch')
    result = {'schema': 'hepta.merton.shared-audit.v1', 'posture': 'RESEARCH_ONLY_DENY_ALL',
              'source_sha256': sources(), 'seal_sha256': sha((run/'sealed.json').read_bytes()),
              'verified_lifecycles': len(records), 'paired_shared_vs_solve': paired,
              'rational_policy_nodes': table_checks, 'prior_checkpoints': prior_checks,
              'online_checkpoints': numeric_checks, 'physical_updates': 512+actual_online,
              'compilation': seal['compilation'], 'loading': seal['loading'], 'prior_cpu_ns': prior['cpu_ns'],
              'break_even_calls_extrapolated_not_observed': break_even,
              'same_fixed8_probabilities_unit_low': same_fixed_predictions,
              'unit_low_shared_minus_fixed8_declared_net': str(marginal_tariff_delta),
              'unit_low_fixed8_tariff_payback_possible': not (same_fixed_predictions and marginal_tariff_delta <= 0),
              'summary_unit_low': summaries, 'rows': records, 'new_sources': 0,
              'cross_task_transfer_verified': False, 'ndu_specific_superiority': False,
              'independent_signer': False, 'hosted_ci_verified': False, 'production_accepted': False,
              'audit_cpu_ns': time.process_time_ns()-c0, 'audit_wall_ns': time.perf_counter_ns()-w0}
    write(output, result); return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('archive', 'material', 'run', 'output'):
        p.add_argument('--'+n, type=Path, required=True)
    a = p.parse_args(); r = audit(a.archive, a.material, a.run, a.output)
    print(encode({'lifecycles': r['verified_lifecycles'], 'policy_checks': r['rational_policy_nodes'], 'paired': r['paired_shared_vs_solve']}).decode())
