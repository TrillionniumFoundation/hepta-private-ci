"""Paired same-problem Riccati-Newton costs via the existing study entrypoint.

CPU times include each solver call, seed construction and original final residual
check. Shared preparation is separate, attributed only to these actual calls.
No fixed speed threshold, new evaluator, trained model or production admission.
"""
from dataclasses import asdict
import hashlib
from pathlib import Path
import platform
import random
import statistics
import sys
import time

from four_gate_common import digest, require, write_once
from fbsde_coupled import (CoupledProfile, continuation_fields, trace_fields,
                           residual_report, solve_global)
from fbsde_coupled_reference import monolithic_reference
from fbsde_riccati import linear_field, linear_trace, solve_newton
from fbsde_acquisition import JointKernel, Objective, solve, exhaustive_reference

METHODS = ('cold_picard', 'cold_riccati_newton', 'linear_seed_newton', 'table_seed_picard')


def complementary_control():
    """Positive and negative finite planning controls; no semantic observations."""
    rows = [(a ^ b, 0, a, b) for a in (0, 1) for b in (0, 1) for _ in range(250)]
    kernel = JointKernel.fit(rows, 2, {'role': 'complementary_evidence_control'}, alpha=.01)
    outcomes = []
    for fee in (.1, .6):
        objective = Objective(costs=(fee, fee))
        one = solve(kernel, ((0, 0),), objective, one_step=True)
        multi = solve(kernel, ((0, 0),), objective)
        oracle = exhaustive_reference(kernel, ((0, 0),), objective)
        require(abs(multi['value']-oracle['value']) < 1e-12 and multi['action'] == oracle['action'],
                'whole-policy control mismatch')
        require(one['action'] == 'abstain', 'single observation must have no value here')
        require(multi['action'] == ('read:1' if fee == .1 else 'abstain'),
                'cost-aware multi-step control mismatch')
        outcomes.append({'fee_each': fee, 'one_step_action': one['action'],
                         'one_step_value': one['value'], 'multi_step_action': multi['action'],
                         'multi_step_value': multi['value'], 'oracle': oracle})
    return {'cases': outcomes, 'generated_mechanism_not_semantic_evidence': True}


def run(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    begin_cpu, begin_wall = time.process_time_ns(), time.perf_counter_ns()
    names = ('fbsde_riccati.py', 'fbsde_riccati_study.py', 'fbsde_riccati_audit.py',
             'fbsde_coupled.py', 'fbsde_coupled_reference.py', 'fbsde_acquisition.py',
             'fbsde_study.py', 'four_gate_common.py')
    cases = []
    for a in (.55, .75):
        for steps in (5, 8, 10):
            p = CoupledProfile(a=a, steps=steps)
            for x0 in (-.8, -.2, .2, .8):
                cases.append({'id': f'a={a};steps={steps};x0={x0}', 'profile': asdict(p), 'x0': x0})
    plan = {'schema': 'hepta.fbsde.riccati-study.v1', 'cases': cases,
            'sources': {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names},
            'methods': METHODS, 'repeats': 7, 'order_seed': 7919, 'tolerance': 1e-10,
            'table_spacing': .125, 'scope': 'same_finite_nonlinear_system_solver_comparison',
            'benchmark_repetitions_are_not_independent_task_observations': True,
            'continuous_time_or_roundoff_error_bounded': False,
            'process': {'python': sys.version, 'platform': platform.platform()},
            'production_promotion_permitted': False}
    write_once(root/'design.json', plan)
    timings, solutions, preparation, controls = [], [], [], []
    prepared = {}
    for item in cases:
        p, x0 = CoupledProfile(**item['profile']), item['x0']
        key = digest(asdict(p))
        if key not in prepared:
            cpu, wall = time.process_time_ns(), time.perf_counter_ns()
            lf = linear_field(p)
            preparation.append({'profile_sha256': key, 'kind': 'linear_field',
                                'cpu_ns': time.process_time_ns()-cpu,
                                'wall_ns': time.perf_counter_ns()-wall})
            cpu, wall = time.process_time_ns(), time.perf_counter_ns()
            table = continuation_fields(p, plan['table_spacing'])
            preparation.append({'profile_sha256': key, 'kind': 'numerical_table',
                                'cpu_ns': time.process_time_ns()-cpu,
                                'wall_ns': time.perf_counter_ns()-wall})
            prepared[key] = (lf, table)
        lf, table = prepared[key]
        outputs = {}
        for repeat in range(plan['repeats']):
            order = list(METHODS)
            random.Random(f"{plan['order_seed']}:{item['id']}:{repeat}").shuffle(order)
            for position, method in enumerate(order):
                cpu, wall = time.process_time_ns(), time.perf_counter_ns()
                if method == 'cold_picard':
                    result = solve_global(p, x0, tolerance=plan['tolerance'])
                elif method == 'cold_riccati_newton':
                    result = solve_newton(p, x0, tolerance=plan['tolerance'])
                elif method == 'linear_seed_newton':
                    seed = linear_trace(p, x0, lf)['y']
                    result = solve_newton(p, x0, initial=seed, tolerance=plan['tolerance'])
                else:
                    seed = trace_fields(p, x0, table)['y']
                    result = solve_global(p, x0, initial=seed, tolerance=plan['tolerance'])
                cost, elapsed = time.process_time_ns()-cpu, time.perf_counter_ns()-wall
                require(result['report']['y_error_bound_exact_arithmetic'] <= plan['tolerance'],
                        'original equation error budget failed')
                if repeat == 0:
                    outputs[method] = result
                require(digest(result['y']) == digest(outputs[method]['y']), 'deterministic solver drift')
                timings.append({'case_id': item['id'], 'method': method, 'repeat': repeat,
                                'position': position, 'cpu_ns': cost, 'wall_ns': elapsed,
                                'solution_sha256': digest(result['y'])})
        solutions.append({**item, 'solutions': outputs})
        direct = linear_trace(p, x0, lf)
        control = {'case_id': item['id'], 'linear_target_root_y': direct['y'][0],
                   'original_target_root_y': outputs['cold_riccati_newton']['y'][0],
                   'linear_answer_original_error_bound': residual_report(p,x0,direct['y'])['y_error_bound_exact_arithmetic']}
        if p.steps == 5:
            cpu = time.process_time_ns()
            reference = monolithic_reference(asdict(p), x0)
            control.update({'independent_dense_reference_cpu_ns': time.process_time_ns()-cpu,
                            'max_y_error_against_dense_reference': max(abs(a-b) for a,b in
                             zip(reference['y'],outputs['cold_riccati_newton']['y']))})
            require(control['max_y_error_against_dense_reference'] < 2e-10, 'independent reference disagrees')
        controls.append(control)
    write_once(root/'solutions.json', solutions)
    write_once(root/'timings.json', timings)
    write_once(root/'preparation.json', preparation)
    write_once(root/'linear-negative-controls.json', controls)
    write_once(root/'complementary-control.json', complementary_control())
    summaries = []
    for item in cases:
        samples = {m: [t['cpu_ns'] for t in timings if t['case_id'] == item['id'] and t['method'] == m] for m in METHODS}
        median = {m: statistics.median(v) for m,v in samples.items()}
        summaries.append({'case_id': item['id'], 'cpu_ns_samples': samples,
                          'cpu_ns_medians': median,
                          'cold_picard_over_cold_newton_cpu_ratio': median['cold_picard']/median['cold_riccati_newton']})
    per_method = {m: sum(t['cpu_ns'] for t in timings if t['method'] == m) for m in METHODS}
    prep_cost = {'cold_picard': 0, 'cold_riccati_newton': 0,
                 'linear_seed_newton': sum(p['cpu_ns'] for p in preparation if p['kind'] == 'linear_field'),
                 'table_seed_picard': sum(p['cpu_ns'] for p in preparation if p['kind'] == 'numerical_table')}
    summary = {'schema': 'hepta.fbsde.riccati-study-results.v1', 'case_summaries': summaries,
               'solution_sha256': digest(solutions), 'timings_sha256': digest(timings),
               'preparation_sha256': digest(preparation), 'solver_cpu_ns': sum(per_method.values()),
               'solver_wall_ns': sum(t['wall_ns'] for t in timings),
               'component_preparation_cpu_ns': sum(p['cpu_ns'] for p in preparation),
               'per_method_solver_cpu_ns': per_method,
               'per_method_preparation_plus_actual_calls_cpu_ns': {m:per_method[m]+prep_cost[m] for m in METHODS},
               'cpu_envelope_ns': time.process_time_ns()-begin_cpu,
               'wall_envelope_ns': time.perf_counter_ns()-begin_wall,
               'seed_preparation_charged_only_to_actual_uses': True,
               'no_unmeasured_future_volume_amortization': True,
               'preparation_and_solve_are_components_not_native_lifecycle': True,
               'neural_encoder_executed': False, 'semantic_accuracy_improvement_claimed': False,
               'production_promotion_permitted': False}
    write_once(root/'summary.json', summary)
    from fbsde_riccati_audit import audit
    write_once(root/'arithmetic-audit.json', audit(root))
    return summary
