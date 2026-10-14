"""Independent arithmetic for saved scalar Riccati experiments, no solver imports.

Does not authenticate execution, memory safety, source independence or promotion.
All bounds here concern the same finite binary system in ordinary double floats.
"""
import math
import random
import statistics
from pathlib import Path

from four_gate_common import digest, require, strict_loads


def original_metrics(cfg, x0, y):
    steps = cfg['steps']
    require(type(steps) is int and 1 <= steps <= 10 and
            type(y) is list and len(y) == 2**steps-1, 'complete tree values')
    require(all(type(v) in (float, int) and math.isfinite(v) for v in y), 'finite solution')
    h, n = cfg['horizon']/steps, len(y)
    # Rebuild each state by its ancestors, not by importing the forward routine.
    x = []
    for node in range(2*n+1):
        cursor, ancestors, sign = node, [], 0
        while cursor:
            sign += -1 if cursor % 2 else 1
            cursor = (cursor-1)//2
            ancestors.append(cursor)
        x.append(x0+cfg['a']*h*sum(y[j] for j in ancestors)+cfg['sigma']*math.sqrt(h)*sign)
    mapped = [0.]*n+[math.tanh(v) for v in x[n:]]
    for i in reversed(range(n)):
        mapped[i] = (.5*(mapped[2*i+1]+mapped[2*i+2])+cfg['beta']*h*math.tanh(x[i]))/(1+cfg['lam']*h)
    r = max(abs(a-b) for a, b in zip(y, mapped[:n]))
    q = cfg['a']*cfg['horizon']*(1+cfg['beta']*cfg['horizon'])
    require(0 <= q < .98, 'unsupported original contraction profile')
    return {'fixed_point_residual': r, 'error_bound': r/(1-q), 'x': x}


def audit(directory):
    root = Path(directory)
    def read(name):
        path = root/name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 32*1024*1024,
                'bounded regular evidence')
        return strict_loads(path.read_bytes())
    plan, evidence, summary = (read(n) for n in ('design.json', 'solutions.json', 'summary.json'))
    trials = read('timings.json')
    preparation = read('preparation.json')
    require(plan['schema'] == 'hepta.fbsde.riccati-study.v1', 'study profile')
    require(summary['solution_sha256'] == digest(evidence) and
            summary['timings_sha256'] == digest(trials), 'original evidence digest')
    require(plan['repeats'] == 7 and plan['tolerance'] == 1e-10 and plan['order_seed'] == 7919,
            'registered comparison controls changed')
    require(plan['methods'] == ['cold_picard','cold_riccati_newton','linear_seed_newton','table_seed_picard'],
            'strong solver control inventory changed')
    require(len(plan['cases']) == 24, 'registered case count')
    planned = {c['id']: c for c in plan['cases']}
    require(len(planned) == len(plan['cases']) == len(evidence) and
            {c['id'] for c in evidence} == set(planned), 'complete registered case inventory')
    require(summary['preparation_sha256'] == digest(preparation), 'preparation digest drift')
    prep_expected = {(digest(c['profile']), kind) for c in plan['cases']
                     for kind in ('linear_field','numerical_table')}
    prep_seen, prep_cpu = set(), 0
    for row in preparation:
        key = (row['profile_sha256'], row['kind'])
        require(key in prep_expected and key not in prep_seen, 'repeated/missing physical preparation')
        require(type(row['cpu_ns']) is int and row['cpu_ns'] >= 0 and
                type(row['wall_ns']) is int and row['wall_ns'] >= 0, 'invalid preparation cost')
        prep_seen.add(key); prep_cpu += row['cpu_ns']
    require(prep_seen == prep_expected and prep_cpu == summary['component_preparation_cpu_ns'],
            'preparation work mismatch')
    identities, maximum = {}, 0.
    for case in evidence:
        require({k:case[k] for k in ('id','profile','x0')} == planned[case['id']],
                'case coefficient/input mismatch')
        p, x0 = case['profile'], case['x0']
        require(set(case['solutions']) == set(plan['methods']), 'missing solver control')
        for arm, result in case['solutions'].items():
            measured = original_metrics(p, x0, result['y'])
            require(measured['error_bound'] <= plan['tolerance']+2e-13,
                    'solution fails ORIGINAL nonlinear equation')
            reported = result['report']['y_error_bound_exact_arithmetic']
            require(abs(measured['error_bound']-reported) <= 2e-13, 'claimed residual drift')
            require(type(result['x']) is list and len(result['x']) == len(measured['x']) and
                    all(type(v) in (float,int) and math.isfinite(v) for v in result['x']),
                    'complete finite forward-state inventory')
            require(max(abs(a-b) for a, b in zip(measured['x'], result['x'])) < 1e-11,
                    'forward state drift')
            key = (case['id'], arm)
            require(key not in identities, 'duplicate solver case')
            identities[key] = digest(result['y'])
            maximum = max(maximum, measured['error_bound'])
    expected = {(cid, arm, r) for cid, arm in identities for r in range(plan['repeats'])}
    seen, cpu, wall = set(), 0, 0
    for item in trials:
        key = (item['case_id'], item['method'], item['repeat'])
        require(key in expected and key not in seen, 'unpaired/repeated timing trial')
        seen.add(key)
        order = list(plan['methods'])
        random.Random(f"{plan['order_seed']}:{key[0]}:{key[2]}").shuffle(order)
        require(type(item['position']) is int and 0 <= item['position'] < len(order) and
                order[item['position']] == key[1], 'recorded solver order mismatch')
        require(item['solution_sha256'] == identities[key[:2]], 'timed output differs from audited solution')
        require(type(item['cpu_ns']) is int and item['cpu_ns'] >= 0 and
                type(item['wall_ns']) is int and item['wall_ns'] >= 0, 'invalid measured work')
        cpu += item['cpu_ns']; wall += item['wall_ns']
    require(seen == expected and cpu == summary['solver_cpu_ns'] and
            wall == summary['solver_wall_ns'], 'missing work or false cost sum')
    totals = {m: sum(t['cpu_ns'] for t in trials if t['method'] == m) for m in plan['methods']}
    standalone = dict(totals)
    standalone['linear_seed_newton'] += sum(p['cpu_ns'] for p in preparation if p['kind']=='linear_field')
    standalone['table_seed_picard'] += sum(p['cpu_ns'] for p in preparation if p['kind']=='numerical_table')
    require(totals == summary['per_method_solver_cpu_ns'] and
            standalone == summary['per_method_preparation_plus_actual_calls_cpu_ns'], 'per-method cost drift')
    require(len(summary['case_summaries']) == len(planned) and
            {c['case_id'] for c in summary['case_summaries']} == set(planned), 'comparison summary coverage')
    for row in summary['case_summaries']:
        samples = {m: [t['cpu_ns'] for t in trials if t['case_id']==row['case_id'] and t['method']==m]
                   for m in plan['methods']}
        medians = {m:statistics.median(v) for m,v in samples.items()}
        require(row['cpu_ns_samples'] == samples and row['cpu_ns_medians'] == medians and
                row['cold_picard_over_cold_newton_cpu_ratio'] ==
                medians['cold_picard']/medians['cold_riccati_newton'], 'performance summary drift')
    require(summary['component_preparation_cpu_ns'] >= 0 and
            summary['solver_cpu_ns']+summary['component_preparation_cpu_ns'] <= summary['cpu_envelope_ns'],
            'CPU work outside envelope')
    return {'cases': len(evidence), 'timed_solves': len(trials),
            'max_independently_recomputed_error_bound': maximum,
            'solver_cpu_ns': cpu, 'all_controls_same_original_problem': True,
            'float_roundoff_enclosed': False, 'physical_execution_authenticated': False,
            'semantic_superiority_established': False, 'production_promotion_permitted': False}
