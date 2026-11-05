"""Read-only reanalysis of the frozen semantic run; no new scientific panels."""

from decimal import Decimal as D, localcontext
import hashlib
from itertools import product
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parents[1]
ROOT = AUDIT.parents[4]
RUN = AUDIT / 'evidence/run_20261105_001'
COMMIT = '062b6dd7c730c4795ae617f4c85278dd2ac821d7'
THETA = ('0.3', '-0.2', '0.5', '-0.4', '-0.1', '0.2')


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path):
    data = path.read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def ce(rows, eta):
    return sum(p * v for p, v in rows) if eta == 0 else -sum(p * (-eta * v).exp() for p, v in rows).ln() / eta


def probabilities(theta):
    rows = []
    for offset in (0, 2, 4):
        e = [D(theta[offset]).exp(), D(theta[offset + 1]).exp()]
        rows.append([x / sum(e) for x in e])
    return rows


def closed_recursive(theta, eta, rate):
    """Explicit three-node equations, independent of the generic DAG evaluator."""
    with localcontext() as ctx:
        eta, rate = D(str(eta)), D(str(rate))
        ctx.prec = 80 + (max(0, -eta.adjusted()) if eta else 0)
        root, warm, cold = probabilities(theta)
        d1, d2, d3 = ((-rate * k).exp() for k in (1, 2, 3))
        vw = ce([(warm[0], D('.9')), (warm[1] * D('.8'), -D('.05') + d1 * D('1.4')),
                 (warm[1] * D('.2'), -D('.05') - d2 * D('.3'))], eta)
        vc = ce([(cold[0], D('.2')), (cold[1], -D('.2') + d1 * vw)], eta)
        return ce([(root[0], D('.1')), (root[1] / 2, -D('.1') + d1 * vw),
                   (root[1] / 2, -D('.1') + d3 * vc)], eta)


def closed_gradient(theta, eta, rate):
    with localcontext() as ctx:
        ctx.prec = 100
        h = D('1e-10')
        result = []
        for index in range(6):
            plus, minus = list(map(D, theta)), list(map(D, theta))
            plus[index] += h
            minus[index] -= h
            result.append(float((closed_recursive(plus, eta, rate) - closed_recursive(minus, eta, rate)) / (2 * h)))
        return result


def closed_tree_values(eta, rate):
    """The explicit STOP tree plus the two-by-three observation continuations."""
    with localcontext() as ctx:
        ctx.prec = 80
        eta, rate = D(str(eta)), D(str(rate))
        d1, d2, d3 = ((-rate * k).exp() for k in (1, 2, 3))
        warm = [D('.9'), ce([(D('.8'), -D('.05') + d1 * D('1.4')),
                            (D('.2'), -D('.05') - d2 * D('.3'))], eta)]
        cold = [D('.2'), -D('.2') + d1 * warm[0], -D('.2') + d1 * warm[1]]
        return [float(D('.1'))] + [float(ce([(D('.5'), -D('.1') + d1 * w),
                                           (D('.5'), -D('.1') + d3 * c)], eta)) for w, c in product(warm, cold)]


def closed_paths(theta, eta, rate):
    """Eight explicit paths and their scores; all arithmetic starts in Decimal."""
    with localcontext() as ctx:
        eta, rate = D(str(eta)), D(str(rate))
        ctx.prec = 80 + (max(0, -eta.adjusted()) if eta else 0)
        p = probabilities(theta)
        d1, d2, d3 = ((-rate * k).exp() for k in (1, 2, 3))
        rows = [
            (D(1), D('.1'), ((0, 0),)),
            (D('.5'), -D('.1') + d1 * D('.9'), ((0, 1), (1, 0))),
            (D('.4'), -D('.1') + d1 * (-D('.05') + d1 * D('1.4')), ((0, 1), (1, 1))),
            (D('.1'), -D('.1') + d1 * (-D('.05') - d2 * D('.3')), ((0, 1), (1, 1))),
            (D('.5'), -D('.1') + d3 * D('.2'), ((0, 1), (2, 0))),
            (D('.5'), -D('.1') + d3 * (-D('.2') + d1 * D('.9')), ((0, 1), (2, 1), (1, 0))),
            (D('.4'), -D('.1') + d3 * (-D('.2') + d1 * (-D('.05') + d1 * D('1.4'))), ((0, 1), (2, 1), (1, 1))),
            (D('.1'), -D('.1') + d3 * (-D('.2') + d1 * (-D('.05') - d2 * D('.3'))), ((0, 1), (2, 1), (1, 1))),
        ]
        weighted = []
        for mass, value, decisions in rows:
            score = [D(0)] * 6
            for state, action in decisions:
                mass *= p[state][action]
                for a in (0, 1):
                    score[2 * state + a] = D(a == action) - p[state][a]
            weighted.append((mass, value, score))
        if eta == 0:
            gradient = [sum(m * v * g[k] for m, v, g in weighted) for k in range(6)]
        else:
            z = sum(m * (-eta * v).exp() for m, v, _ in weighted)
            gradient = [-sum(m * (-eta * v).exp() * g[k] for m, v, g in weighted) / (eta * z) for k in range(6)]
        return {'value': float(ce([(m, v) for m, v, _ in weighted], eta)),
                'gradient': list(map(float, gradient)), 'path_count': len(weighted)}


def main():
    cpu, wall = time.process_time(), time.perf_counter()
    manifest_path = AUDIT / 'SOURCE_MANIFEST.json'
    manifest, protocol = read(manifest_path), read(AUDIT / 'PROTOCOL.json')
    remote = read(HERE / 'GITHUB_READBACK.json')
    remote_files = {r['path']: r for r in remote['entries']}
    registration = read(RUN / 'REGISTRATION.json')
    start, envelope = read(RUN / 'semantics/run/START.json'), read(RUN / 'semantics/run/RESULT.json')
    receipt = read(RUN / 'semantics/PROCESS_RECEIPT.json')
    result = envelope['data']
    observed = {name: identity(ROOT / name) for name in manifest['files']}
    binding = {'manifest_sha256': digest(manifest_path), 'base_commit': manifest['base_commit'], 'files': observed}
    checks = {}
    checks['local_registered_source_bytes'] = observed == manifest['files']
    checks['start_result_registration_same_source'] = all(v['source_binding'] == binding for v in (registration, start, envelope))
    checks['published_commit_and_tree'] = registration['source_commit'] == remote['source_commit'] == remote['commit_sha'] == COMMIT
    checks['all_registered_git_blobs_match_remote'] = all(remote_files[n]['git_blob'] == v['git_blob'] and remote_files[n]['bytes'] == v['bytes'] for n, v in observed.items())
    checks['manifest_itself_matches_remote'] = remote_files[str(manifest_path.relative_to(ROOT))]['git_blob'] == identity(manifest_path)['git_blob']
    checks['phase_and_runner_binding'] = start['phase'] == envelope['phase'] == 'semantics' and Path(start['runner_file']) == AUDIT / 'run.py'
    checks['retained_failure_absent'] = not (RUN / 'semantics/run/FAILURE.json').exists()
    checks['process_exit_and_reaping'] = receipt['exit_code'] == 0 and not receipt['timed_out'] and receipt['child_reaped']
    checks['process_log_hash'] = digest(RUN / 'semantics/process.log') == receipt['process_log_sha256']
    expected = set(product(protocol['semantics']['eta'], protocol['semantics']['discount_rate']))
    checks['six_panel_roster_complete'] = len(result['panels']) == len(expected) and {(p['eta'], p['rate']) for p in result['panels']} == expected
    panels = []
    for row in result['panels']:
        eta, rate = row['eta'], row['rate']
        actor, paths = row['actor'], closed_paths(THETA, eta, rate)
        actor_gradient = closed_gradient(THETA, eta, rate)
        trees = closed_tree_values(eta, rate)
        recorded_bellman_error = abs(row['optimal']['value'] - row['enumeration']['value'])
        recorded_gradient_error = max(abs(a-b) for a,b in zip(actor['gradient'], row['independent_decimal_gradient']))
        panels.append({'eta': eta, 'rate': rate, 'recorded_bellman_error_recomputed': recorded_bellman_error,
            'recorded_gradient_error_recomputed': recorded_gradient_error,
            'reported_error_fields_match': recorded_bellman_error == row['bellman_error'] and recorded_gradient_error == row['gradient_error'],
            'closed_tree_optimal_error': abs(max(trees) - row['optimal']['value']),
            'closed_recursive_value_error': abs(float(closed_recursive(THETA, eta, rate)) - actor['value']),
            'closed_recursive_gradient_error': max(abs(a-b) for a,b in zip(actor_gradient, actor['gradient'])),
            'closed_static_path_value_error': abs(paths['value'] - row['static_path']['value']),
            'closed_static_path_gradient_error': max(abs(a-b) for a,b in zip(paths['gradient'], row['static_path']['gradient'])),
            'risk_scaled_static_path_error': abs(row['risk_scaled_static_value'] - paths['value']),
            'nested_minus_static': actor['value'] - paths['value'],
            'seven_trees_and_eight_paths': len(trees) == row['enumeration']['root_trees'] == 7 and paths['path_count'] == row['static_path']['paths'] == 8,
            'objective_flag_correct': row['path_objective_matches_recursive'] == (eta == 0 or rate == 0)})
    checks['panel_reanalysis'] = all(p['reported_error_fields_match'] and p['seven_trees_and_eight_paths'] and p['objective_flag_correct']
        and all(p[k] < 1e-12 for k in ('closed_tree_optimal_error','closed_recursive_value_error','closed_recursive_gradient_error',
        'closed_static_path_value_error','closed_static_path_gradient_error','risk_scaled_static_path_error')) for p in panels)
    # Reconstruct only the exact four registered risk-limit cases from frozen code.
    sys.path.insert(0, str(ROOT))
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.semantics import evaluate, example_model
    limits = []
    for row in result['independent_path_risk_limit']:
        actor = evaluate(example_model(), tuple(map(float, THETA)), row['eta'])
        paths = closed_paths(THETA, row['eta'], 0)
        recomputed = {'value_error': abs(paths['value']-actor['value']),
                      'gradient_error': max(abs(a-b) for a,b in zip(paths['gradient'],actor['gradient']))}
        limits.append({'eta': row['eta'], **recomputed,
                       'reported_error_fields_match': all(abs(recomputed[k]-row[k]) < 1e-15 for k in recomputed)})
    checks['registered_low_risk_path_limit'] = [v['eta'] for v in limits] == protocol['semantics']['path_limit_eta'] and all(v['reported_error_fields_match'] and v['value_error'] < 1e-12 and v['gradient_error'] < 1e-12 for v in limits)
    c = result['counterexamples']
    g = c['duration_GAE']
    correct, wrong = [.5**3*2, .5*1], [.5*2, .5*1]
    duration_grad = [(correct[0]-correct[1])/4, (correct[1]-correct[0])/4]
    wrong_grad = [(wrong[0]-wrong[1])/4, (wrong[1]-wrong[0])/4]
    with localcontext() as ctx:
        ctx.prec=80
        z = D('.5')*(-D(1)).exp()+D('.25')*D(2).exp()+D('.25')*(-D(6)).exp()
        entropic_value = float(-z.ln()/2)
        safe_gradient = float((D('.5')-D('.5')*(-D(1)).exp()/z)/2)
    counterexample_errors = {
        'duration_correct_gradient': max(abs(a-b) for a,b in zip(duration_grad,g['correct_gradient'])),
        'duration_wrong_gradient': max(abs(a-b) for a,b in zip(wrong_grad,g['fixed_step_gradient'])),
        'duration_correlation': abs(.5*.9**3*2-c['duration_correlation']['correct_expected_discounted_value']),
        'duration_wrong_factorization': abs((.9+.9**3)/2-c['duration_correlation']['incorrect_product_of_expectations']),
        'entropic_value': abs(entropic_value-c['entropic_GAE']['entropic']['value']),
        'entropic_gradient': max(abs(a-b) for a,b in zip([safe_gradient,-safe_gradient],c['entropic_GAE']['entropic']['gradient'])),
        'upfront_cost': abs(-.4+.5**2-c['upfront_cost']['correct_value']),
        'wrong_delayed_cost': abs(.5**2*(1-.4)-c['upfront_cost']['incorrect_discounted_cost_value']),
    }
    checks['counterexamples_reconstructed'] = max(counterexample_errors.values()) < 1e-12
    checks['source_bytes_still_unchanged'] = all(identity(ROOT/n)==v for n,v in observed.items())
    report = {'schema':'ndu.semantic-output-review.v1','source_commit':COMMIT,'source_tree':remote['tree_sha'],
        'scope':'Read-only reanalysis of the registered six panels and four path-limit cases; no additional scientific experiment.',
        'reviewer_disclosure':'The semantic implementation author performed this separate reanalysis. Arithmetic is independently reconstructed; this is not independent institutional review.',
        'source_file_count':len(observed),'manifest_sha256':binding['manifest_sha256'],
        'result_sha256':digest(RUN/'semantics/run/RESULT.json'),'review_source_sha256':digest(Path(__file__)),
        'checks':checks,'all_checks_passed':all(checks.values()),'panel_reanalysis':panels,'low_risk_path_reanalysis':limits,
        'counterexample_absolute_errors':counterexample_errors,
        'maximum_recorded_bellman_error':max(v['recorded_bellman_error_recomputed'] for v in panels),
        'maximum_recorded_gradient_error':max(v['recorded_gradient_error_recomputed'] for v in panels),
        'maximum_closed_form_gradient_error':max(v['closed_recursive_gradient_error'] for v in panels),
        'recorded_risk_neutral_limit':result['risk_neutral_limit'],
        'process_cost':{k:receipt[k] for k in ('child_cpu_seconds','supervisor_cpu_seconds','wall_seconds','child_peak_rss_bytes','abnormal_exit_cost_is_only_measured_lower_bound')},
        'cost_boundary':'Review body timing below is additional one-time review work; it is not included in the original phase receipt and excludes review interpreter startup, imports and GitHub readback.',
        'review_body_cpu_seconds':time.process_time()-cpu,'review_body_wall_seconds':time.perf_counter()-wall,
        'new_algorithm_or_production_qualification':False}
    with (HERE/'REVIEW.json').open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps({'all_checks_passed':report['all_checks_passed'],'source_file_count':len(observed),
        'max_bellman_error':report['maximum_recorded_bellman_error'],'max_recorded_gradient_error':report['maximum_recorded_gradient_error'],
        'max_closed_gradient_error':report['maximum_closed_form_gradient_error'],'low_risk_path_reanalysis':limits},indent=2))
    return 0 if report['all_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
