"""Frozen-candidate, candidate-independent finite numerical validation.

This evaluates the already sealed V1 manifest. It never changes the candidate,
filters by candidate success, changes inherited tolerances, or tunes on results.
The archived literal oracle retains its decimal-roundtrip input convention.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
PROTOCOL = 'R16_VALIDATION_PROTOCOL_V1.json'
PROTOCOL_SHA256 = '18f66bd44e4ea03792c678947ede965af0f83199ccbdc34067f1c5b809af2c31'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output, summary_path, oracle_pythonpath):
    if output.exists() or summary_path.exists() or output == summary_path:
        raise ValueError('Evidence outputs must be distinct, create-only paths')
    if oracle_pythonpath:
        sys.path.insert(0, str(oracle_pythonpath))
    import frozen_reference as oracle
    import compensated_kernel as kernel
    from mpmath import mp

    protocol = json.loads((ROOT / PROTOCOL).read_text())
    expected = {**protocol['candidate_source_sha256'], PROTOCOL: PROTOCOL_SHA256,
                protocol['case_manifest']: protocol['case_manifest_sha256']}
    seal = {name: digest(ROOT / name) for name in expected}
    if seal != expected:
        raise ValueError('Frozen candidate/protocol/manifest seal mismatch')
    manifest = json.loads((ROOT / protocol['case_manifest']).read_text())
    points = manifest['rows'] if isinstance(manifest, dict) else manifest
    ctx = mp.clone()
    ctx.dps = 80
    cv = lambda value: ctx.mpf(str(value))
    eps32 = ctx.mpf(2) ** -23
    cases, rows = [], []
    start = time.perf_counter()
    start_cpu = time.process_time()
    for number, point in enumerate(points):
        theta = np.asarray(point['theta'], dtype=np.float32).astype(float).tolist()
        case = {'id': point['id'], 'theta': theta}
        try:
            r, delta, sigma, alpha, tax, liquidity, maturity, coupon, principal = map(cv, theta)
            boundary = oracle.fields(theta, 0., 'log_distance')[0]
            flow = delta * boundary - (1-tax) * coupon + (alpha * boundary-principal) / maturity
            scale = abs(delta*boundary) + abs((1-tax)*coupon) + (abs(alpha*boundary)+abs(principal)) / maturity
            valid = bool(ctx.isfinite(boundary) and boundary > 0 and
                         ctx.isfinite(flow) and flow < -64*eps32*max(ctx.mpf(1),scale))
            case.update(independent_boundary=str(boundary), independent_flow=str(flow),
                        independent_scale=str(scale), independently_valid=valid)
        except Exception as error:
            case.update(independently_valid=False, independent_validity_error=repr(error))
        if not case['independently_valid']:
            # Retain every independently rejected point; do not count it as a pass.
            try:
                kernel.build(theta)
                case['candidate_boundary_status'] = 'accepted_independently_rejected_point'
            except Exception as error:
                case['candidate_boundary_status'] = 'rejected'
                case['candidate_boundary_error'] = repr(error)
            cases.append(case)
            continue

        a = (r-delta-sigma*sigma/2) / (sigma*sigma)
        zt = ctx.sqrt(a*a+2*(r+liquidity)/(sigma*sigma))
        local = ctx.mpf('.75') * min(ctx.mpf('.002'), ctx.mpf('.02')*sigma*ctx.sqrt(maturity),
                                    ctx.mpf('.05')/(1+abs(a)+zt))
        states = [('log_distance', float(np.float32(float(local)))), ('log_distance', 1.),
                  ('asset', float(np.float32(float(boundary*(1+ctx.mpf('1e-6')))))), ('asset', 100.)]
        try:
            model = kernel.build(theta)
            build_error = None
        except Exception as error:
            model, build_error = None, repr(error)
        case['candidate_boundary_status'] = 'accepted' if build_error is None else 'rejected_valid_point'
        case['passed'] = True
        for coordinate, state in states:
            row = {'case': point['id'], 'coordinate': coordinate, 'state': state, 'passed': False}
            try:
                ref = np.asarray([float(v) for v in oracle.fields(theta, state, coordinate)])
                jac1 = oracle.jacobian(theta, state, coordinate, step='1e-18')
                jac2 = oracle.jacobian(theta, state, coordinate, step='5e-19')
                if not all(np.all(np.isfinite(x)) for x in (ref, jac1, jac2)):
                    raise ArithmeticError('Nonfinite independent oracle value or derivative')
                halving = np.max(abs(jac1-jac2)/np.maximum(1., abs(jac2)))
                row.update(reference=ref.tolist(), reference_jacobian=jac2.tolist(),
                           oracle_halving_error=float(halving), oracle_halving_passed=bool(halving <= 1e-12))
                if build_error is not None:
                    raise ArithmeticError('Candidate rejected independently valid point: '+build_error)
                y, jac = model.state(state, coordinate)
                if not np.all(np.isfinite(y)) or not np.all(np.isfinite(jac)):
                    raise ArithmeticError('Nonfinite candidate output or derivative')
                ve = abs(y-ref)/np.maximum(1., abs(ref))
                je = abs(jac-jac2)/np.maximum(1., abs(jac2))
                worst = tuple(int(i) for i in np.unravel_index(je.argmax(), je.shape))
                row.update(values=y.tolist(), jacobian=jac.tolist(), value_errors=ve.tolist(),
                           value_error=float(ve.max()), jacobian_error=float(je.max()),
                           worst_jacobian_index=worst,
                           passed=bool(halving <= 1e-12 and ve.max() <= 8e-7 and je.max() <= 2e-5))
            except Exception as error:
                row['error'] = repr(error)
            rows.append(row)
            case['passed'] = case['passed'] and row['passed']
        cases.append(case)
        if (number+1) % 8 == 0:
            print(json.dumps({'points_completed': number+1, 'rows': len(rows),
                              'failed_rows': sum(not row['passed'] for row in rows)}), flush=True)

    after = {name: digest(ROOT/name) for name in expected}
    if after != seal:
        raise ValueError('Frozen sources changed during validation; result is unusable')
    valid = [case for case in cases if case['independently_valid']]
    summary = {'generated_points': len(points), 'independently_valid_points': len(valid),
               'independently_rejected_points': len(points)-len(valid), 'evaluated_rows': len(rows),
               'passed_rows': sum(row['passed'] for row in rows),
               'passed_valid_points': sum(case['passed'] for case in valid),
               'oracle_halving_failures': sum(not row.get('oracle_halving_passed', False) for row in rows),
               'max_value_error': max((row.get('value_error',0.) for row in rows), default=None),
               'max_jacobian_error': max((row.get('jacobian_error',0.) for row in rows), default=None),
               'max_oracle_halving_error': max((row.get('oracle_halving_error',0.) for row in rows), default=None),
               'all_valid_rows_passed': bool(rows) and all(row['passed'] for row in rows),
               'diagnostic_wall_seconds': time.perf_counter()-start,
               'diagnostic_cpu_seconds': time.process_time()-start_cpu}
    report = {'schema': 'hcsn.r16.compensated-fp32-independent-validation-result.v1',
              'candidate_precision': kernel.ARITHMETIC, 'source_sha256_before': seal,
              'source_sha256_after': after, 'runner_sha256': digest(Path(__file__)),
              'reference_input_convention': 'Frozen oracle converts round-trip decimal strings of float32 words represented as Python floats to mp80; it does not reconstruct exact binary rationals.',
              'gate_scope': 'Finite independent numerical validation of two-word compensated FP32 only; not ordinary FP32 admission or global-domain/task/GPU qualification.',
              'gates': protocol['gates'], 'summary': summary, 'cases': cases, 'rows': rows}
    encoded = (json.dumps(report, separators=(',', ':'), allow_nan=False)+'\n').encode()
    with output.open('xb') as handle:
        if output.suffix == '.gz':
            handle.write(gzip.compress(encoded, mtime=0))
        else:
            handle.write(encoded)
    small = {key: value for key,value in report.items() if key not in ('rows','cases')}
    small.update(evidence_file=output.name, evidence_sha256=digest(output),
                 rejected_points=[case for case in cases if not case['independently_valid']],
                 failed_rows=[{k:v for k,v in row.items() if k not in ('reference_jacobian','jacobian')}
                              for row in rows if not row['passed']])
    with summary_path.open('x') as handle:
        json.dump(small, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--summary', type=Path, required=True)
    parser.add_argument('--oracle-pythonpath', type=Path)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        run(args.output.resolve(), args.summary.resolve(), args.oracle_pythonpath)
