"""Original-data scalar replay plus an independently written prefix-only rule."""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from fractions import Fraction as Q
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from material_news import encode, loads, original, packet, sha, write
from audit_news import reference, reference_row, scalar_softmax, equal


def ref_alpha(history, profile):
    if profile == 'neutral':
        return Q(0)
    if profile == 'fixed':
        return Q(1, 4)
    if profile != 'ndu':
        raise ValueError('unknown reference profile')
    a = Q(1, 4)
    for row in history:
        a = min(Q(1, 2), max(Q(0), a + Q(16-sum(row['counts']), 128)))
    return a


def ref_values(history, profile):
    a = ref_alpha(history, profile)
    return [(Q(sum(r['counts']), 32)*(1-a) + Q(min(r['counts']), 8)*a) for r in history]


def reference_decision(history, s, profile):
    if (not history or len(history) > 4 or
        [h['step'] for h in history] != [0, 8, 32, 128][:len(history)]):
        raise ValueError('invalid observed prefix')
    values = ref_values(history, profile)
    current = history[-1]['step']
    later = {0: 8, 8: 32, 32: 128}.get(current)
    ceiling = s['horizon']*(1-max(values))
    price = Q(0) if later is None else Q(s['step_fee'])*(later-current)+Q(s['calibration_fee'])
    projected = None
    reason = 'checkpoint_limit'
    if later is not None:
        if later > s['budget']:
            reason = 'hard_budget'
        elif price >= ceiling:
            reason = 'perfect_payoff_cannot_repay'
        elif current == 0:
            reason = 'bounded_first_pilot'
        else:
            growth = max(Q(0), values[-1]-values[-2])
            rate = growth / (current-history[-2]['step'])
            projected = s['horizon']*min(1-max(values), rate*(later-current))
            reason = 'projected_gain_pays' if projected > price else 'empirical_slope_stop'
    go = reason in ('bounded_first_pilot', 'projected_gain_pays')
    return {'action': 'continue' if go else 'stop', 'from_step': current,
            'to_step': later if go else None, 'reason': reason,
            'alpha': str(ref_alpha(history, profile)), 'next_quote': str(price),
            'perfect_gain_ceiling': str(ceiling),
            'projected_gain': None if projected is None else str(projected)}


def expected_trace(arm, scenario, cal):
    events = [{'kind': 'start'}]
    history, trained = [], []
    current = 0
    if arm in ('no_update', 'fixed8', 'fixed32'):
        selected = 0 if arm == 'no_update' else int(arm[5:])
        if selected > scenario['budget']:
            selected = 0
        events.append({'kind': 'fixed_admission', 'target': selected})
        if selected:
            trained.append((0, selected)); current = selected
            events += [{'kind': 'train_start', 'from_step': 0, 'to_step': selected},
                       {'kind': 'train_done', 'from_step': 0, 'to_step': selected}]
        available = [selected]
    else:
        p = 'neutral' if arm == 'sequential_neutral' else 'fixed' if arm == 'sequential_fixed' else 'ndu'
        while True:
            history.append({'step': current, 'counts': cal[current]})
            events.append({'kind': 'observation', **history[-1]})
            if arm == 'full_search':
                nxt = {0: 8, 8: 32, 32: 128}.get(current)
                go = nxt is not None and nxt <= scenario['budget']
                command = {'action': 'continue' if go else 'stop', 'from_step': current,
                           'to_step': nxt if go else None, 'reason': 'fixed_search_schedule'}
            else:
                command = reference_decision(history, scenario, p)
            events.append({'kind': 'decision', 'observed_steps': [h['step'] for h in history], **command})
            if command['action'] == 'stop':
                break
            nxt = command['to_step']
            trained.append((current, nxt))
            events += [{'kind': 'train_start', 'from_step': current, 'to_step': nxt},
                       {'kind': 'train_done', 'from_step': current, 'to_step': nxt}]
            current = nxt
        values = ref_values(history, p)
        selected = history[values.index(max(values))]['step']
        available = [h['step'] for h in history]
    events.append({'kind': 'success', 'actual_steps': current, 'selected_steps': selected})
    return events, history, trained, current, selected, available


def audit(archive, material, directory, output):
    from online import config, source_hashes, PROTOCOL_SHA
    c0, w0 = time.process_time_ns(), time.perf_counter_ns()
    cfg = config()
    seal = loads((directory/'sealed.json').read_bytes())
    a, receipt = packet(material/'worker.npz')
    expected_fields = {'schema','posture','protocol_sha256','worker_sha256','source_sha256','journal_sha256',
                       'mean','scale','preparation','runtime','fresh_encoder_calls','heldout_labels_loaded','rows'}
    if set(seal) != expected_fields or seal['schema'] != 'hepta.merton.sequential-seal.v1':
        raise ValueError('invalid seal schema')
    if (seal['posture'] != 'RESEARCH_ONLY_DENY_ALL' or seal['source_sha256'] != source_hashes() or
        seal['protocol_sha256'] != PROTOCOL_SHA or seal['worker_sha256'] != receipt['worker_sha256'] or
        type(seal['fresh_encoder_calls']) is not int or seal['fresh_encoder_calls'] != 0 or
        seal['heldout_labels_loaded'] is not False):
        raise ValueError('seal identity or capability changed')
    if loads((directory/'protocol.json').read_bytes()) != cfg:
        raise ValueError('protocol replacement')
    rows, x, parts = original(archive)
    for src, dst in [('train','train'), ('calibration','cal'), ('holdout','holdout')]:
        equal(a['x_'+dst], x[parts[src]])
        if a[dst+'_ids'].tolist() != [rows[i]['case_id'] for i in parts[src]]:
            raise ValueError('source ID substitution')
        if dst != 'holdout':
            equal(a['y_'+dst], [rows[i]['label'] for i in parts[src]])
    hashes = [sha(rows[i]['text'].encode()) for i in parts['calibration']]
    if a['cal_hashes'].tolist() != hashes:
        raise ValueError('calibration partition changed')
    mean, scale, weights, losses = reference(tuple(map(tuple,a['x_train'].astype(float).tolist())), tuple(a['y_train'].tolist()))
    equal(seal['mean'], mean); equal(seal['scale'], scale)
    order = sorted(range(32), key=lambda i: hashes[i])
    cal, hold = {}, {}
    for step, weight in weights.items():
        p = [scalar_softmax(reference_row(r,mean,scale), weight.tolist()) for r in a['x_cal']]
        pred = [max(range(4), key=row.__getitem__) for row in p]
        cal[step] = [sum(int(pred[i] == a['y_cal'][i]) for i in order[j:j+8]) for j in range(0,32,8)]
        hold[step] = [scalar_softmax(reference_row(r,mean,scale), weight.tolist()) for r in a['x_holdout']]
    labels = [rows[i]['label'] for i in parts['holdout']]
    scenarios = {s['name']: s for s in cfg['scenarios']}
    keys = [(r['repeat'], r['scenario'], r['arm']) for r in seal['rows']]
    wanted = {(r,s,arm) for r in range(cfg['repeats']) for s in scenarios for arm in cfg['arms']}
    if len(set(keys)) != len(keys) or set(keys) != wanted:
        raise ValueError('missing or duplicate lifecycle')
    raw = (directory/'attempts.jsonl').read_bytes()
    if sha(raw) != seal['journal_sha256']:
        raise ValueError('changed journal')
    recorded = [loads(line) for line in raw.splitlines()]
    reconstructed, scored = [], []
    strict_fields = {'arm','scenario','actual_steps','selected_steps','calibration_calls','history','checkpoints',
                     'weights','losses','holdout_ids','probabilities','events','phases','cpu_ns','wall_ns','repeat'}
    verified = 0
    for row in seal['rows']:
        if set(row) != strict_fields:
            raise ValueError('unknown lifecycle field')
        if any(type(row[k]) is not int for k in ('repeat','actual_steps','selected_steps','calibration_calls')):
            raise ValueError('noninteger work or identity')
        if loads((directory/f"{row['repeat']}-{row['scenario']}-{row['arm']}.json").read_bytes()) != row:
            raise ValueError('standalone row differs from seal')
        for h in row['history']:
            if (set(h) != {'step','counts'} or type(h['step']) is not int or len(h['counts']) != 4 or
                any(type(n) is not int or not 0 <= n <= 8 for n in h['counts'])):
                raise ValueError('invalid exact observed counts')
        s = scenarios[row['scenario']]
        events, history, trained, actual, selected, available = expected_trace(row['arm'], s, cal)
        if (row['history'] != history or row['actual_steps'] != actual or row['selected_steps'] != selected or
            row['calibration_calls'] != len(history) or set(row['checkpoints']) != set(map(str,available))):
            raise ValueError('observed prefix, work or selection mismatch')
        for step in available:
            equal(row['checkpoints'][str(step)], weights[step]); verified += 1
        # Check exact producer bytes against its original journal AND scalar values above.
        for ev in events:
            if ev['kind'] == 'train_done':
                value = row['checkpoints'][str(ev['to_step'])]
                ev['weights_sha256'] = sha(encode(value))
        if row['events'] != events:
            raise ValueError('lookahead, missing execution, or post-stop training in journal')
        reconstructed.extend({'repeat':row['repeat'],'scenario':row['scenario'],'arm':row['arm'],**e} for e in events)
        equal(row['losses'], losses[:actual]); equal(row['weights'], weights[selected])
        equal(row['probabilities'], hold[selected])
        if row['holdout_ids'] != a['holdout_ids'].tolist():
            raise ValueError('heldout order changed')
        expected_kinds = (['fit'] if actual else [])+['prediction'] if not history else None
        if history:
            expected_kinds = []
            for i in range(len(history)):
                expected_kinds.append('calibration')
                if row['arm'] != 'full_search': expected_kinds.append('decision')
                if i < len(history)-1: expected_kinds.append('fit')
            expected_kinds += ['selection', 'prediction']
        if [p['kind'] for p in row['phases']] != expected_kinds:
            raise ValueError('missing or extra paid phase')
        for clock in ('cpu_ns','wall_ns'):
            if type(row[clock]) is not int or row[clock] < 0:
                raise ValueError('invalid clock')
            if any(set(p) != {'kind','cpu_ns','wall_ns'} or type(p[clock]) is not int or p[clock] < 0 for p in row['phases']):
                raise ValueError('invalid phase')
            if sum(p[clock] for p in row['phases']) > row[clock]:
                raise ValueError('phase clock exceeds lifecycle')
        if actual and sum(p['cpu_ns'] for p in row['phases'] if p['kind']=='fit') <= 0:
            raise ValueError('unmetered training')
        pred = [max(range(4),key=p.__getitem__) for p in hold[selected]]
        correct = [int(p==y) for p,y in zip(pred,labels)]
        charge = Q(s['step_fee'])*actual + Q(s['calibration_fee'])*len(history)
        net = s['horizon']*Q(sum(correct),32)-charge
        stops = [e['reason'] for e in events if e['kind']=='decision' and e['action']=='stop']
        scored.append({'repeat':row['repeat'],'scenario':row['scenario'],'arm':row['arm'],
                       'correct':sum(correct),'correct_vector':correct,'selected_steps':selected,'actual_steps':actual,
                       'calibration_calls':len(history),'charged_utility_units':str(charge),'scenario_net':str(net),
                       'cpu_ms':row['cpu_ns']/1e6,'stop_reason':stops[-1] if stops else 'fixed_schedule'})
    if reconstructed != recorded:
        raise ValueError('full journal not equal to all sealed attempts')
    summaries = []
    for s in scenarios:
        for arm in cfg['arms']:
            r = [r for r in scored if r['scenario']==s and r['arm']==arm]
            if len({(v['correct'],v['selected_steps'],v['actual_steps'],v['scenario_net']) for v in r}) != 1:
                raise ValueError('repeat semantic drift')
            summaries.append({k:v for k,v in r[0].items() if k not in ('repeat','correct_vector','cpu_ms')} |
                             {'median_cpu_ms':statistics.median(v['cpu_ms'] for v in r)})
    result = {'schema':'hepta.merton.sequential-audit.v1','posture':'RESEARCH_ONLY_DENY_ALL',
              'protocol_sha256':PROTOCOL_SHA,'source_sha256':source_hashes(),'seal_sha256':sha((directory/'sealed.json').read_bytes()),
              'verified_lifecycles':len(scored),'verified_checkpoints':verified,
              'actual_optimizer_updates':sum(r['actual_steps'] for r in scored),'unique_holdout_records':32,
              'fresh_encoder_calls':0,'new_sources':0,'prospective_efficacy':False,'ndu_superiority':False,
              'independent_hardware_witness':False,'prepilot_positive_roi_proved':False,
              'scope':'historical classification; empirical ceiling; heuristic sequential stopping',
              'summaries':summaries,'rows':scored,'audit_cpu_ns':time.process_time_ns()-c0,'audit_wall_ns':time.perf_counter_ns()-w0}
    write(output,result)
    print(encode({'lifecycles':len(scored),'checkpoints':verified,'actual_updates':result['actual_optimizer_updates']}).decode())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive','material','run','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    audit(args.archive,args.material,args.run,args.output)
