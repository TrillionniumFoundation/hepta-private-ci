"""Rerun opened 432/512 fixtures; these are regression, never fresh validation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from compiled import Kernel
from recovery_eval import dump, seal

ROOT = Path(__file__).resolve().parent
MODES = ('float64', 'float32', 'compensated32')
INPUTS = {
    'development432': ('FROZEN_REFERENCE.json.gz', '6da00f9f67368a413d2d0f6a2c45efd3055231f4bc3786e3162fa764388d77f8', 432),
    'opened_python512': ('R16_HOLDOUT_V1.json.gz', '44f6340bbe2f783e10f36aeddda6f96ed67df1efe5f6d6cf2a0732241f798310', 512),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(protocol_path, expected, output):
    if output.exists():
        raise ValueError('Output directory is create-only')
    protocol = json.loads(protocol_path.read_text())
    seal(protocol, protocol_path, expected)
    before = sha(Path(__file__))
    kernel = Kernel(ROOT/'recovered.so')
    output.mkdir()
    results = {}
    for dataset, (name, digest, count) in INPUTS.items():
        path = ROOT/'regression_input'/name
        if sha(path) != digest:
            raise ValueError('Regression input hash mismatch')
        reference = json.loads(gzip.decompress(path.read_bytes()))
        rows = reference['rows']
        if len(rows) != count:
            raise ValueError('Wrong regression count')
        theta_map = {p['id']: p['theta'] for p in reference.get('cases', [])}
        theta = [r['quantized_theta'] if 'quantized_theta' in r else theta_map[r['case']] for r in rows]
        state = [r['state'] for r in rows]
        coordinate = [r['coordinate'] for r in rows]
        gold = np.asarray([r['reference'] for r in rows])
        gold_j = np.asarray([r['reference_jacobian'] for r in rows])
        if gold.shape != (count, 5) or gold_j.shape != (count, 5, 10) or not np.all(np.isfinite(gold)) or not np.all(np.isfinite(gold_j)):
            raise ValueError('Invalid archived reference shape/finiteness')
        info = {}
        for mode in MODES:
            values, jacobian, status = kernel.batch(theta, state, coordinate, mode)
            actual, good_cases = [], {r['case']: True for r in rows}
            passed_count = failures = 0
            max_value = max_jacobian = 0.
            for i, row in enumerate(rows):
                record = {'row_index': i, 'case': row['case'], 'theta': theta[i],
                          'coordinate': coordinate[i], 'state': state[i], 'status': int(status[i])}
                valid = status[i] == 0 and np.all(np.isfinite(values[i])) and np.all(np.isfinite(jacobian[i]))
                if valid:
                    value_error = float(np.max(abs(values[i]-gold[i])/np.maximum(1., abs(gold[i]))))
                    jacobian_error = float(np.max(abs(jacobian[i]-gold_j[i])/np.maximum(1., abs(gold_j[i]))))
                    passed = value_error <= protocol['gates'][mode]['value_scaled'] and jacobian_error <= protocol['gates'][mode]['jacobian_scaled']
                    record.update(values=values[i].tolist(), jacobian=jacobian[i].tolist(),
                                  value_error=value_error, jacobian_error=jacobian_error, passed=bool(passed))
                    max_value = max(max_value, value_error)
                    max_jacobian = max(max_jacobian, jacobian_error)
                else:
                    passed = False
                    failures += 1
                    record.update(passed=False, error='Rejected or nonfinite full financial evaluation')
                passed_count += int(passed)
                good_cases[row['case']] &= bool(passed)
                actual.append(record)
            artifact = dump(output/(dataset+'_'+mode+'.json.gz'), {
                'schema': 'hcsn.recovery-regression-rows.v1', 'dataset': dataset, 'mode': mode,
                'protocol_sha256': expected, 'source_sha256': protocol['source_sha256'],
                'binary_sha256': protocol['binary_sha256'], 'reference_sha256': digest,
                'rows': actual,
            })
            info[mode] = {'rows': count, 'passed_rows': passed_count, 'case_count': len(good_cases),
                          'passed_cases': sum(good_cases.values()), 'rejected_or_nonfinite': failures,
                          'max_value_error': max_value, 'max_jacobian_error': max_jacobian,
                          'artifact': artifact}
        if sha(path) != digest:
            raise ValueError('Regression input changed during evaluation')
        results[dataset] = info
        print(json.dumps({'dataset': dataset, 'results': info}), flush=True)
    seal(protocol, protocol_path, expected)
    if sha(Path(__file__)) != before:
        raise ValueError('Regression runner changed')
    passed = all(info[mode]['passed_rows'] == info[mode]['rows'] for info in results.values() for mode in ('float64', 'compensated32'))
    receipt = {'schema': 'hcsn.recovery-regression.v1', 'regression_gate_passed': passed,
               'scope': 'Opened archived inputs only; no new independent admission. Every ordinary-FP32 failure retained.',
               'ordinary_fp32_admitted': False, 'protocol_sha256': expected,
               'binary_sha256': protocol['binary_sha256'], 'script_sha256': before, 'results': results}
    dump(output/'INDEX.json', receipt)
    return passed


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--protocol', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(0 if run(a.protocol, a.protocol_sha256, a.output) else 1)
