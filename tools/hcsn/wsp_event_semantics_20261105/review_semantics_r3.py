#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Independent, read-only review of the frozen CTMC semantic experiment.

The numerical checker does not call the diagnostic's transition, event, reward,
or aggregation functions. It uses transient submatrices and integrated boundary
flux, plus DOP853 for five predetermined first-world reward-count controls.
Original policy/state definitions are reexecuted for the separate REPAIR check.
"""
import sys
sys.dont_write_bytecode = True
import ast
import copy
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import expm, solve

ROOT = Path(__file__).resolve().parent
FITS = (11, 23, 37, 53, 71)
HORIZONS = (1, 2, 6)
THRESHOLDS = (-.5, 0., .5)
TOLERANCE = 5e-10
READS = {}


def raw(path):
    content = path.read_bytes()
    READS[str(path)] = hashlib.sha256(content).hexdigest()
    return content


def read(path):
    b = raw(path)
    return json.loads(gzip.decompress(b) if path.suffix == '.gz' else b)


def require(condition, why):
    if not condition:
        raise ValueError(why)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False)


def independent_prior(coordinates, distance):
    m = np.zeros(len(coordinates))
    for sign in (-1, 1):
        m[int(np.argmin(np.abs(coordinates[:-2] - sign * distance)))] += .5
    return m


def source_definitions():
    ns = {'np': np, 'copy': copy, 'Path': Path}
    vendor = ROOT / 'vendor/frozen_joint'
    def load(name, selected, constants=(), target=None):
        destination = ns if target is None else target
        tree = ast.parse(raw(vendor / name).decode(), filename=name)
        body = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in selected:
                body.append(node)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets):
                body.append(node)
        exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), name, 'exec'), destination)
    load('legacy_task.py', {'public_features'})
    ns['legacy_public_features'] = ns.pop('public_features')
    load('joint_task.py', {'validate_public', 'initial', 'legal', 'due_request', 'successor', 'public_features'}, {'SCHEMA'})
    deployment = dict(ns)
    load('joint_deploy.py', {'prior_mass', 'NumpyPolicy'}, {'SCHEMA', 'THRESHOLDS'}, target=deployment)
    ns['NumpyPolicy'] = deployment['NumpyPolicy']
    return ns


def main():
    start, cpu = time.monotonic(), time.process_time()
    report = {'schema': 'hepta-ctmc-independent-semantic-review-v1', 'status': 'FAIL',
              'producer_frozen_files_modified': False, 'new_training_or_weight_edit': False,
              'new_generalization_or_task_value_evidence': False}
    try:
        protocol = read(ROOT / 'PROTOCOL_FROZEN.json')
        result = read(ROOT / 'execution_r1/run/RESULTS.json')
        started = read(ROOT / 'execution_r1/run/STARTED.json')
        require(protocol['fits'] == list(FITS) and protocol['horizons'] == list(HORIZONS)
                and protocol['thresholds'] == list(THRESHOLDS), 'frozen diagnostic design changed')
        require(protocol['frozen_utc'] < started['utc'], 'diagnostic not frozen before recorded start')
        require(result['protocol']['sha256'] == READS[str(ROOT / 'PROTOCOL_FROZEN.json')],
                'producer result/protocol digest mismatch')
        for group in ('source_files', 'input_files'):
            for name, item in protocol[group].items():
                b = raw(ROOT / name)
                require(len(b) == item['bytes'] and hashlib.sha256(b).hexdigest() == item['sha256'],
                        'frozen file changed: ' + name)
        artifacts = {a['path']: a for a in result['artifacts']}
        ctx = source_definitions()
        maxima = dict(endpoint=0., first_hit=0., lower_first=0., upper_first=0., outer_survival=0.,
                      ode_counts=0., ode_boundary_mass=0., raw_partitions=0., stored_transition=0.)
        cases = 0
        unique_initial_atoms = {str(v): 0 for v in (0., .5, 1.)}
        repairs = dict(cases=0, equal_mass=0, equal_bank=0, read_reopened=0,
                       any_predicted_q_difference=0, any_predicted_belief_difference=0)
        fit_reports = []
        for fit in FITS:
            model = read(ROOT / f'inputs/fit_{fit}_C.json.gz')
            publics = read(ROOT / f'inputs/fit_{fit}_TRAIN_PUBLICS.json.gz')
            path = ROOT / f'execution_r1/run/fit_{fit}_RECORDS.json.gz'
            payload = read(path)
            require(READS[str(path)] == artifacts[path.name]['sha256'], 'raw result digest mismatch')
            require(len(publics) == 64 and len(payload['records']) == 64, 'missing TRAIN worlds')
            coordinates = np.asarray(model['coordinates'])
            n = model['n_grid']
            require(n == 31 and len(coordinates) == n + 2, 'unexpected state layout')
            generators = {int(k): np.asarray(v) for k, v in model['core']['generators'].items()}
            reset_rates = []
            for q in generators.values():
                for boundary in (n, n+1):
                    reset_rates.append(float(q[boundary, :n].sum()))
                    require(q[boundary, :n].min() >= 0 and q[boundary, :n].sum() > 0,
                            'boundary has no endogenous recovery jump')
                    require(abs(q[boundary, :n].sum() - model['core']['physical']['recovery_rate']) < TOLERANCE,
                            'stored recovery rate differs from generator')
            ordinary, transient, outer = {}, {}, {}
            for table in model['core']['tables']:
                key = (float(table['dt']), int(table['drive']))
                dt, drive = key
                q = generators[drive]
                ordinary[key] = expm(dt*q)
                maxima['stored_transition'] = max(maxima['stored_transition'], float(np.max(np.abs(
                    ordinary[key] - np.asarray(table['matrix'])))))
                for k in THRESHOLDS:
                    surviving = np.flatnonzero(coordinates <= k)
                    transient[key, k] = expm(dt*q[np.ix_(surviving, surviving)])
                a = q[:n, :n]
                p = expm(dt*a)
                # Integral exp(s A)B ds = A^{-1}(exp(t A)-I)B for transient A.
                flux = solve(a, (p-np.eye(n)) @ q[:n, n:], assume_a='gen')
                outer[key] = p, flux
            policy = ctx['NumpyPolicy'](model)
            ode_evaluations = 0
            for world_index, (public, recorded) in enumerate(zip(publics, payload['records'])):
                require(public['id'] == recorded['world_id'], 'world identity mismatch')
                require(hashlib.sha256(canonical(public).encode()).hexdigest() == recorded['public_sha256'],
                        'world content mismatch')
                prior = independent_prior(coordinates, public['prior_distance'])
                mass = prior.copy()
                survivors = {k: prior[coordinates <= k].copy() for k in THRESHOLDS}
                for k in THRESHOLDS:
                    atom = float(prior[coordinates > k].sum())
                    unique_initial_atoms[str(atom)] += 1
                interior, causes = prior[:n].copy(), np.zeros(2)
                ode = np.r_[prior, 0., 0.]
                for tick, (dt, drive) in enumerate(zip(public['duration'], public['drive']), 1):
                    key = (float(dt), int(drive))
                    mass = mass @ ordinary[key]
                    for k in THRESHOLDS:
                        survivors[k] = survivors[k] @ transient[key, k]
                    p, flux = outer[key]
                    causes += interior @ flux
                    interior = interior @ p
                    if world_index == 0:
                        q = generators[int(drive)]
                        entries = np.r_[q[:n, n:].sum(axis=1), 0., 0.]
                        resets = np.r_[np.zeros(n), q[n:, :n].sum(axis=1)]
                        def rhs(_time, y):
                            return np.r_[q.T @ y[:n+2], y[:n+2] @ entries, y[:n+2] @ resets]
                        solution = solve_ivp(rhs, (0., dt), ode, method='DOP853', rtol=1e-12, atol=1e-14)
                        require(solution.success, 'independent count ODE failed')
                        ode = solution.y[:, -1]
                        ode_evaluations += solution.nfev
                    if tick not in HORIZONS:
                        continue
                    h = recorded['horizons'][HORIZONS.index(tick)]
                    require(h['tick'] == tick, 'missing frozen horizon')
                    for k, row in zip(THRESHOLDS, h['thresholds']):
                        endpoint = float(mass[coordinates > k].sum())
                        hit = float(1. - survivors[k].sum())
                        maxima['endpoint'] = max(maxima['endpoint'], abs(endpoint-row['endpoint_strict_greater']))
                        maxima['first_hit'] = max(maxima['first_hit'], abs(hit-row['first_hit_strict_greater']))
                        require(row['initial_event_atom'] == float(prior[coordinates > k].sum()), 'initial event atom mismatch')
                        errors = [row['endpoint_strict_greater']+row['endpoint_strict_less']+row['equality_mass']-1.,
                                  row['endpoint_strict_greater']+row['endpoint_complement_less_equal']-1.,
                                  row['first_hit_strict_greater']+row['survival_never_strict_greater']-1.]
                        maxima['raw_partitions'] = max(maxima['raw_partitions'], max(map(abs, errors)))
                        cases += 1
                    boundary = h['outer']
                    maxima['lower_first'] = max(maxima['lower_first'], abs(causes[0]-boundary['first_lower']))
                    maxima['upper_first'] = max(maxima['upper_first'], abs(causes[1]-boundary['first_upper']))
                    maxima['outer_survival'] = max(maxima['outer_survival'], abs(interior.sum()-boundary['survival_no_outer_hit']))
                    maxima['raw_partitions'] = max(maxima['raw_partitions'], abs(causes.sum()+interior.sum()-1.),
                        abs(boundary['expected_boundary_entries']-boundary['expected_reset_departures']-boundary['boundary_occupancy']))
                    if world_index == 0:
                        maxima['ode_counts'] = max(maxima['ode_counts'],
                            abs(ode[-2]-boundary['expected_boundary_entries']), abs(ode[-1]-boundary['expected_reset_departures']))
                        maxima['ode_boundary_mass'] = max(maxima['ode_boundary_mass'],
                            abs(ode[n:n+2].sum()-boundary['boundary_occupancy']))

                require(0. < public['failure_probability'] <= 1., 'forced failure has zero probability')
                state = ctx['initial'](public)
                due = ctx['due_request'](public, state, 2)
                completion = {'failure': True, 'observation_tick': due} if due is not None else None
                state = ctx['successor'](public, state, 2, completion)
                if due is None:
                    due = ctx['due_request'](public, state, 1)
                    require(due is not None, 'failure not reachable by second tick')
                    state = ctx['successor'](public, state, 1, {'failure': True, 'observation_tick': due})
                wait = ctx['successor'](public, state, 1)
                repair = ctx['successor'](public, state, 3)
                mw, bw, pw = policy.represent(public, wait)
                mr, br, pr = policy.represent(public, repair)
                repairs['cases'] += 1
                repairs['equal_mass'] += bool(np.array_equal(mw, mr))
                repairs['equal_bank'] += bool(np.array_equal(bw, br))
                repairs['read_reopened'] += bool(not ctx['legal'](public, wait)[2] and ctx['legal'](public, repair)[2])
                w, r = policy.predict(public, wait), policy.predict(public, repair)
                repairs['any_predicted_q_difference'] += bool(w['q'] != r['q'])
                repairs['any_predicted_belief_difference'] += bool(w['belief'] != r['belief'])
                changed = {key for key in wait if wait[key] != repair[key]}
                require(changed == {'broken', 'charges'}, 'REPAIR changed unexpected fields')
                require(set(np.flatnonzero(pw != pr)).issubset({3, 4}), 'REPAIR feature changes exceed contract')
                require(abs(repair['charges'] - wait['charges'] - public['repair_price']) < 5e-15,
                        'REPAIR fee mismatch')
            fit_reports.append({'fit': fit, 'train_worlds': len(publics),
                'boundary_to_interior_rate_min': min(reset_rates), 'boundary_to_interior_rate_max': max(reset_rates),
                'independent_ode_first_world_id': publics[0]['id'], 'independent_ode_function_evaluations': ode_evaluations})
        require(cases == 2880 and repairs['cases'] == 320, 'full data count changed')
        require(repairs['equal_mass'] == repairs['equal_bank'] == repairs['read_reopened'] == 320,
                'equal-tick representation or future-action counterfactual failed')
        require(max(maxima.values()) <= TOLERANCE, 'independent numeric recomputation outside frozen tolerance')
        for name, expected in READS.items():
            require(hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, 'reviewed input changed during read')
        report.update(status='PASS_WITH_SCOPE_LIMITS', protocol_sha256=result['protocol']['sha256'],
            producer_results_sha256=READS[str(ROOT/'execution_r1/run/RESULTS.json')],
            fits=fit_reports, endpoint_first_hit_cases=cases,
            initial_event_atom_counts_per_world_threshold=unique_initial_atoms,
            numerical_maximum_absolute_differences=maxima, numerical_tolerance=TOLERANCE,
            repair_counterfactual=repairs,
            methods=['transient-submatrix survival complement on all 320 TRAIN schedules',
                     'transient interior matrix solve for competing first-boundary cause flux',
                     'DOP853 full CTMC/count ODE on first listed TRAIN world of each fit',
                     'source-selected original state/policy definitions on all 320 repair counterfactuals'],
            conclusions={'stored_generator_has_endogenous_reset': True,
                'bank_is_endpoint_forecast': True, 'first_hit_includes_time_zero_atom': True,
                'strict_upper_endpoint_complement_includes_equality': True,
                'two_sided_first_exit_requires_surviving_mass': True,
                'repair_is_sensor_and_fee_not_a_commanded_latent_reset': True,
                'equal_tick_mass_does_not_imply_equal_downstream_or_future_behavior': True},
            limitations=['finite-state known-law numerical diagnostic, not continuum first-passage proof',
                'original TRAIN schedules and five reused research checkpoints, not independent efficacy evidence',
                'large endpoint/first-hit differences can include initial-hit probability, not only reset effects',
                'ODE and transient-matrix agreement are numerical checks, not outward-rounded certificates',
                'no actual Pocket4 production checkpoint, weight mutation, policy improvement or trading claim'],
            read_file_sha256={str(Path(k).relative_to(ROOT)):v for k,v in sorted(READS.items())})
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        report.update(review_body_cpu_seconds=time.process_time()-cpu,
            review_body_wall_seconds=time.monotonic()-start,
            review_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            reviewer_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        with (ROOT / 'independent_semantic_review_r3' / 'REVIEW.json').open('x') as f:
            json.dump(report, f, indent=2, sort_keys=True, allow_nan=False)
            f.write('\n')
        print(json.dumps({k:v for k,v in report.items() if k!='read_file_sha256'}, sort_keys=True))


if __name__ == '__main__':
    main()
