"""Checkpoint-reusing real SGD pilot with separately metered inference and scoring.

Same frozen five-parameter residual architecture. No new source or model claim.
The shared inference quote is a versioned same-architecture modeling assumption,
not a claim that individual coefficient vectors have identical hardware latency.
"""
from __future__ import annotations

import argparse
import copy
import math
import sys
import time
from fractions import Fraction as Q
from pathlib import Path

PARENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PARENT))
from material import canonical, sha, strict_loads, write_new
from learning import (STEPS, RATE, CPU_PRICE, alpha_from, aggregate, feature, fit,
                      full_questions, predict, sigmoid, validate_fold)

ARMS = ('no_update', 'fixed_8', 'fixed_32', 'fixed_128',
        'corrected_independent', 'prefix_ndu', 'prefix_neutral')
REPEATS = 9
HORIZON = 8


def spec():
    return {'schema': 'hepta.merton.prefix.spec.v1',
            'parent_sha': 'acd2a0fd8b25568188f7f554f14644c636bbdee2',
            'arms': list(ARMS), 'checkpoints': list(STEPS), 'repeats': REPEATS,
            'hypothetical_reuse_horizon': HORIZON, 'rate': RATE,
            'cpu_price_per_ms': str(CPU_PRICE),
            'selection': 'exact registered recursive value less cumulative refit quote and shared inference quote',
            'shared_inference_quote': 'mean measured prediction-only ns per complete calibration question across SAME-5P candidates',
            'score_cost': 'measured separately; charged as pilot overhead; never repeated as deployment inference',
            'checkpoint_safety': 'only deterministic same-input same-init same-optimizer prefix trajectories',
            'clock_repeats_are_independent_sources': False,
            'new_sources': 0, 'new_encoder_calls': 0, 'fresh_reader_calls': 0,
            'neural_preference_learning': False, 'continuous_fbsde': False,
            'authority': 'DENY_ALL'}


def source_hashes():
    local = [Path(__file__), Path(__file__).with_name('audit_prefix.py'),
             Path(__file__).with_name('test_prefix.py'), Path(__file__).with_name('README.md')]
    ancestors = [PARENT/n for n in ('material.py', 'learning.py', 'audit_real.py')]
    return {str(p.relative_to(PARENT)): sha(p.read_bytes()) for p in local+ancestors}


def public_rows(rows):
    return [{k: r[k] for k in ('id', 'group', 'question', 'base', 'x')} for r in rows]


def timed_prediction_and_score(head, rows):
    # Materialization is paid by the lifecycle, but no labels enter predict().
    public = public_rows(rows)
    c = time.process_time_ns()
    probabilities = predict(head, public)
    prediction_ns = time.process_time_ns()-c
    c = time.process_time_ns()
    outcomes = full_questions(rows, probabilities)
    scoring_ns = time.process_time_ns()-c
    return probabilities, outcomes, prediction_ns, scoring_ns


def prefix_fit(rows):
    """Execute 128 updates ONCE; copy the exact 0/8/32/128 snapshots.

    Initialization and train normalization are paid once. Step-zero prediction
    retains the original ones scale. Intermediate arrays are independent copies.
    Cumulative times are quotes; the bank total is charged only once.
    """
    if not rows or any(type(r.get('label')) is not int or r['label'] not in (0,1) for r in rows):
        raise ValueError('genuine binary train labels required')
    c, w = time.process_time_ns(), time.perf_counter_ns()
    heads = {'0': {'weights': [0.0]*5, 'scales': [1.0]*4}}
    cumulative = {'0': 0}
    scales = [max(1e-6, math.sqrt(sum(r['x'][j]**2 for r in rows)/len(rows))) for j in range(4)]
    X = [feature(r, scales) for r in rows]
    questions = {(r['group'], r['question']) for r in rows}
    counts = {q: sum((r['group'], r['question']) == q for r in rows) for q in questions}
    mass = [1/(len(questions)*counts[r['group'], r['question']]) for r in rows]
    weights = [0.0]*5
    trace = []
    for step in range(1, max(STEPS)+1):
        gradient = [0.0]*5
        loss = 0.0
        for r, x, m in zip(rows, X, mass):
            probability = sigmoid(r['base']+sum(a*b for a,b in zip(weights,x)))
            d = probability-r['label']
            loss += m*2*d*d
            g = m*4*d*probability*(1-probability)
            for j in range(5):
                gradient[j] += g*x[j]
        weights = [a-RATE*b for a,b in zip(weights, gradient)]
        trace.append(loss)
        if step in STEPS:
            heads[str(step)] = {'weights': weights.copy(), 'scales': scales.copy()}
            cumulative[str(step)] = time.process_time_ns()-c
    return {'schema': 'hepta.merton.prefix.bank.v1', 'heads': heads,
            'loss_trace': trace, 'cumulative_cpu_ns': cumulative,
            'cpu_ns': time.process_time_ns()-c, 'wall_ns': time.perf_counter_ns()-w,
            'train_ids': [r['id'] for r in rows],
            'label_sha256': sha(canonical([[r['id'],r['label']] for r in rows])),
            'optimizer_steps': max(STEPS), 'train_row_updates': max(STEPS)*len(rows)}


def choose(quotes, alpha):
    if type(alpha) is not Q or not 0 <= alpha <= Q(1,2):
        raise ValueError('bounded exact preference required')
    if set(quotes) != set(map(str, STEPS)):
        raise ValueError('candidate census')
    common = {r['inference_ns_per_question'] for r in quotes.values()}
    if len(common) != 1 or Q(next(iter(common))) < 0:
        raise ValueError('shared-architecture inference quote required')
    values = {}
    for n in STEPS:
        row = quotes[str(n)]
        qs = tuple(Q(x) for x in row['passage_success'])
        if len(qs) != 3 or any(not 0 <= x <= 1 for x in qs) or Q(row['refit_ns']) < 0:
            raise ValueError('invalid cost or outcome')
        quality = aggregate(tuple((Q(1,3), v) for v in qs), alpha)
        cost = Q(row['refit_ns']) + HORIZON*Q(row['inference_ns_per_question'])
        values[n] = HORIZON*quality - CPU_PRICE*cost/1_000_000
    return max(STEPS, key=lambda n: (values[n], -n)), {str(k): str(v) for k,v in values.items()}


def execute(fold, arm):
    if arm not in ARMS:
        raise ValueError('unregistered arm')
    validate_fold(fold)
    c,w = time.process_time_ns(),time.perf_counter_ns()
    train, held = fold['train'], fold['held_inputs']
    banks, calibration, quotes, values = [], [], {}, {}
    pilot_cpu, select_cpu = 0, 0
    alpha = Q(0)
    if arm == 'no_update':
        selected = 0
    elif arm.startswith('fixed_'):
        selected = int(arm[6:])
    else:
        pc = time.process_time_ns()
        groups = sorted({r['group'] for r in train})
        for group in groups:
            a = [r for r in train if r['group'] != group]
            b = [r for r in train if r['group'] == group]
            if arm == 'corrected_independent':
                cc,ww = time.process_time_ns(),time.perf_counter_ns()
                heads, timings, receipts = {}, {}, []
                for n in STEPS:
                    head, receipt = fit(a, n)
                    heads[str(n)] = head
                    timings[str(n)] = receipt['cpu_ns'] if n else 0
                    receipts.append(receipt)
                bank = {'schema': 'hepta.merton.independent.bank.v1',
                        'heads': heads, 'cumulative_cpu_ns': timings,
                        'cpu_ns': time.process_time_ns()-cc, 'wall_ns': time.perf_counter_ns()-ww,
                        'train_ids': [r['id'] for r in a],
                        'label_sha256': sha(canonical([[r['id'],r['label']] for r in a])),
                        'optimizer_steps': sum(STEPS), 'train_row_updates': sum(STEPS)*len(a),
                        'receipts': receipts}
            else:
                bank = prefix_fit(a)
            bank['validation_group'] = group
            banks.append(bank)
            for n in STEPS:
                pp, qq, inference_ns, score_ns = timed_prediction_and_score(bank['heads'][str(n)], b)
                calibration.append({'group': group, 'steps': n, 'ids': [r['id'] for r in b],
                                    'p': pp, 'questions': qq,
                                    'prediction_cpu_ns': inference_ns, 'score_cpu_ns': score_ns})
        # Every candidate has exactly the same deployed parameter shape. A common
        # quote avoids giving 128 steps a lucky-clock inference advantage over 8.
        inference_quote = sum((Q(r['prediction_cpu_ns'], len(r['questions'])) for r in calibration), Q(0))/len(calibration)
        for n in STEPS:
            refit = sum((Q(b['cumulative_cpu_ns'][str(n)]*len(train), len(b['train_ids'])) for b in banks), Q(0))/3
            cr = [r for r in calibration if r['steps'] == n]
            quotes[str(n)] = {'passage_success': [str(Q(sum(r['questions']),len(r['questions']))) for r in cr],
                              'refit_ns': str(refit), 'inference_ns_per_question': str(inference_quote)}
        observed = [v for r in calibration if r['steps'] == 0 for v in r['questions']]
        alpha = Q(0) if arm == 'prefix_neutral' else alpha_from(observed)
        pilot_cpu = time.process_time_ns()-pc
        sc = time.process_time_ns()
        selected,values = choose(quotes,alpha)
        select_cpu = time.process_time_ns()-sc
    head,receipt = fit(train,selected)
    public = public_rows(held)
    tc = time.process_time_ns()
    pp = predict(head,public)
    inference_cpu = time.process_time_ns()-tc
    return {'fold': fold['fold'], 'arm': arm, 'source_fold_sha256': sha(canonical(fold)),
            'selected_steps': selected, 'head': head, 'final_fit': receipt,
            'banks': banks, 'calibration': calibration, 'quotes': quotes,
            'alpha': str(alpha), 'values': values,
            'held_predictions': [{'id':r['id'],'p':p} for r,p in zip(held,pp)],
            'stages': {'pilot_cpu_ns':pilot_cpu,'selection_cpu_ns':select_cpu,
                       'final_fit_cpu_ns':receipt['cpu_ns'],'inference_cpu_ns':inference_cpu},
            'lifecycle_cpu_ns':time.process_time_ns()-c,
            'lifecycle_wall_ns':time.perf_counter_ns()-w,
            'actual_optimizer_steps':sum(b['optimizer_steps'] for b in banks)+selected,
            'actual_train_row_updates':sum(b['train_row_updates'] for b in banks)+selected*len(train),
            'held_labels_loaded':False,'fresh_encoder_calls':0,'fresh_reader_calls':0}


def run(material_dir, output):
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    write_new(output/'spec.json',spec())
    folds = [strict_loads((Path(material_dir)/f'fold-{i}.json').read_bytes()) for i in range(4)]
    rows = []
    c,w=time.process_time_ns(),time.perf_counter_ns()
    for repeat in range(REPEATS):
        for i,f in enumerate(folds):
            # Rotate order without inspecting any measured results or test labels.
            offset = (repeat+i) % len(ARMS)
            for arm in ARMS[offset:]+ARMS[:offset]:
                r=execute(f,arm);r['repeat']=repeat;rows.append(r)
    sealed={'schema':'hepta.merton.prefix.seal.v1','spec_sha256':sha(canonical(spec())),
            'source_sha256':source_hashes(),'rows':rows,'authority':'DENY_ALL',
            'optimizer_steps':sum(r['actual_optimizer_steps'] for r in rows),
            'worker_cpu_ns':time.process_time_ns()-c,'worker_wall_ns':time.perf_counter_ns()-w,
            'new_sources':0,'new_encoder_calls':0,'new_reader_calls':0,'python':sys.version}
    write_new(output/'sealed.json',sealed)
    print({'rows':len(rows),'optimizer_steps':sealed['optimizer_steps']})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--material',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();run(args.material,args.output)
