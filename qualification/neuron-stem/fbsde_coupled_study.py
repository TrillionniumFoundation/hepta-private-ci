"""Execute registered nonlinear coupled-field/corrector and monolithic comparisons.

Numerical observations only. Continuous FBSDE and real Encoder/task efficacy are
not consequences of the finite discrete theorem or these floating experiments.
"""
from dataclasses import asdict, replace
import hashlib
from pathlib import Path
import time

from four_gate_common import require, write_once
from fbsde_coupled import (CoupledProfile, continuation_fields, trace_fields,
                           solve_global, residual_report)
from fbsde_coupled_reference import monolithic_reference

SPACINGS = (.5, .25, .125, .0625, .03125)
INITIALS = (-.7, 0., .45, .85)


def _measure(function, *args, **kwargs):
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    value = function(*args, **kwargs)
    return value, {'cpu_ns': time.process_time_ns()-cpu, 'wall_ns': time.perf_counter_ns()-wall}


def experiment():
    start = time.process_time_ns()
    profiles = [CoupledProfile(), CoupledProfile(horizon=1., a=.4, beta=.6, lam=.4, sigma=.5)]
    rows = []
    for p in profiles:
        cfg = asdict(p)
        # Pay each preparation once, then reuse the identical fields across x0's.
        prepared = []
        for spacing in SPACINGS:
            fields, cost = _measure(continuation_fields, p, spacing)
            prepared.append((spacing, fields, cost))
        wrong_fields, wrong_cost = _measure(continuation_fields, p, SPACINGS[-1], reset_at=(2, 4))
        cases = []
        for x0 in INITIALS:
            reference, reference_cost = _measure(monolithic_reference, cfg, x0)
            global_solution, global_cost = _measure(solve_global, p, x0)
            gap = max(abs(a-b) for a, b in zip(reference['y'], global_solution['y']))
            require(gap <= global_solution['report']['y_error_bound_exact_arithmetic']+1e-12,
                    'global reference disagreement exceeds computed exact-arithmetic bound')
            grid_rows = []
            for spacing, fields, _ in prepared:
                trace, trace_cost = _measure(trace_fields, p, x0, fields)
                corrected, correct_cost = _measure(solve_global, p, x0, initial=trace['y'])
                err = max(abs(a-b) for a, b in zip(trace['y'], reference['y']))
                require(err <= trace['report']['y_error_bound_exact_arithmetic']+1e-11,
                        'field approximation exceeds computed exact-arithmetic bound')
                err_after = max(abs(a-b) for a, b in zip(corrected['y'], reference['y']))
                require(err_after < 1e-9, 'global correction did not recover original discrete problem')
                grid_rows.append({'spacing': spacing, 'y_sup_error_vs_reference': err,
                                  'approximate_y': trace['y'], 'report': trace['report'],
                                  'trace_cost': trace_cost, 'corrector_cost': correct_cost,
                                  'corrector_map_calls': corrected['map_calls'],
                                  'corrected_y_sup_error': err_after})
            wrong = trace_fields(p, x0, wrong_fields)
            require(grid_rows[-1]['y_sup_error_vs_reference'] < grid_rows[0]['y_sup_error_vs_reference']/10,
                    'registered grid refinement experiment failed')
            require(wrong['max_reset_interface_jump'] > .01, 'reset control failed to expose interface gap')
            cases.append({'x0': x0, 'reference': reference, 'reference_cost': reference_cost,
                          'cold_global': global_solution, 'cold_global_cost': global_cost,
                          'grid': grid_rows, 'wrong_reset': wrong})
        rows.append({'profile': cfg, 'q': p.q, 'cases': cases,
                     'field_preparation_once': [dict(spacing=s, **c) for s, _, c in prepared],
                     'wrong_field_preparation_once': wrong_cost,
                     'local_field_solves': prepared[-1][1]['local_solves']})
    rejected = []
    for n in (2, 5, 10):
        p = CoupledProfile(horizon=1., a=.8, beta=.5, steps=n)
        try:
            solve_global(p, .3)
        except ValueError as exc:
            require('global contraction' in str(exc), 'wrong rejection reason')
            rejected.append({'steps': n, 'q': p.q, 'reason': str(exc)})
        else:
            raise AssertionError('unsupported global bound accepted')
    return {'schema': 'hepta.fbsde.nonlinear-coupled-study.v1', 'rows': rows,
            'rejected_outside_profile': rejected,
            'study_cpu_envelope_ns': time.process_time_ns()-start,
            'nonlinear_coupling_executed': True, 'drift_depends_on_backward_y': True,
            'diffusion_depends_on_y_or_z': False, 'generator_depends_on_z': False,
            'model_kind': 'scalar_Y_coupled_binary_Euler_with_nonzero_nonlinear_generator',
            'numerical_bound_is_interval_verified': False,
            'new_discrete_proof_in_runbook': True, 'general_continuous_theorem_claimed': False,
            'policy_optimality_or_language_reasoning_claimed': False,
            'real_encoder_executed': False, 'production_promotion_permitted': False}


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    names = ('fbsde_coupled.py', 'fbsde_coupled_reference.py', 'fbsde_coupled_study.py')
    write_once(output/'design.json', {'schema': 'hepta.fbsde.nonlinear-coupled-design.v1',
        'profiles': [asdict(CoupledProfile()), asdict(CoupledProfile(horizon=1., a=.4, beta=.6, lam=.4, sigma=.5))],
        'initial_states': INITIALS, 'spacings': SPACINGS, 'reset_at': [2, 4],
        'global_q_cap': .98, 'global_tolerance': 1e-10, 'local_tolerance': 1e-12,
        'source_sha256': {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names},
        'in_process_design_is_not_independent_preregistration': True})
    result = experiment()
    write_once(output/'coupled.json', result)
    write_once(output/'summary.json', {'schema': 'hepta.fbsde.nonlinear-coupled-summary.v1',
        'result_sha256': hashlib.sha256((output/'coupled.json').read_bytes()).hexdigest(),
        'mechanism_execution_completed': True, 'profiles': len(result['rows']),
        'fully_observed_binary_nodes_per_case': 2**(CoupledProfile().steps+1)-1,
        'continuous_or_real_world_acceptance': False, 'production_promotion_permitted': False})
