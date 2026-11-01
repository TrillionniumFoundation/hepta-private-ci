"""Reject ten targeted corruptions without retraining the fixed-z model."""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def run(root, expected, audit, training, financial_root, work, output):
    work.mkdir(parents=True, exist_ok=False)
    baseline_audit, baseline_training = read(audit), read(training)
    rows = []
    def trial(name, side, mutate, message, expected_native_calls):
        value = copy.deepcopy(baseline_audit if side == 'audit' else baseline_training)
        mutate(value)
        faulty = work/(name+'.json.gz')
        faulty.write_bytes(gzip.compress((json.dumps(value, indent=2, allow_nan=True)+'\n').encode(), mtime=0))
        target = work/(name+'_should_not_pass.json')
        args = [sys.executable, '-B', str(root/'check_asset_results.py'), '--root', str(root), '--protocol-sha256', expected,
                '--audit', str(faulty if side == 'audit' else audit), '--training', str(faulty if side == 'training' else training),
                '--financial-root', str(financial_root), '--output', str(target)]
        result = subprocess.run(args, capture_output=True, text=True)
        rows.append({'id': name, 'changed_artifact': side, 'faulty_artifact_sha256': sha(faulty),
                     'returncode': result.returncode, 'expected_error_substring': message,
                     'stdout': result.stdout, 'stderr': result.stderr,
                     'expected_same_kernel_branch_calls_along_verified_error_path': expected_native_calls,
                     'passed': bool(result.returncode != 0 and message in result.stderr and not target.exists())})
    trial('missing_physical_fixture', 'audit', lambda d: d['fixed_potential_readout']['fixtures'].pop(), 'Fixed-z fixture identity/count mismatch', 0)
    trial('missing_training_update', 'training', lambda d: d['history'].pop(), 'Training input/count mismatch', 0)
    trial('nan_early_gradient', 'audit', lambda d: d['temporal']['comparisons']['step_theta']['observed'][0].__setitem__(0, float('nan')), 'Nonfinite JSON NaN', 0)
    trial('corrupt_euler_drift', 'training', lambda d: d['final_trajectory']['drift_dz_da'][0][0].__setitem__(0, .5), 'Euler drift mismatch', 1)
    trial('corrupt_early_theta_gradient', 'audit', lambda d: d['temporal']['comparisons']['step_theta']['observed'][0].__setitem__(0, .1), 'Temporal gradient comparison failed', 1)
    trial('move_claimed_fixed_asset', 'training', lambda d: d['fixed_physical_fixture']['represented_assets_final'].__setitem__(0, 51.), 'Physical assets changed with theta', 1)
    trial('wrong_boundary_diagnostic', 'training', lambda d: d.__setitem__('financial_boundary_final', d['financial_boundary_final']+.1), 'Actual fixed-physical boundary movement failed', 1)
    trial('change_physical_target', 'training', lambda d: d['data']['target_z'].__setitem__(0, d['data']['target_z'][0]+.01), 'Training input/count mismatch', 0)
    trial('wrong_protocol', 'audit', lambda d: d.__setitem__('protocol_sha256', '0'*64), 'Receipt/protocol mismatch', 0)
    trial('missing_phase_change', 'audit', lambda d: d['temporal']['trajectory']['crossings'].pop(), 'Phase-change count/identity mismatch', 1)
    result = {'schema': 'hcsn.hx-fixed-potential-checker-negative-tests.v1', 'passed': all(r['passed'] for r in rows),
              'protocol_sha256': expected, 'checker_sha256': sha(root/'check_asset_results.py'), 'script_sha256': sha(__file__),
              'original_audit_sha256': sha(audit), 'original_training_sha256': sha(training),
              'tests': rows, 'training_reruns': 0, 'pytorch_calls': 0,
              'same_kernel_reference_scope': 'Five corruptions reach the existing 18-row branch/local-reference batch before the asserted failure; five reject earlier. These are same-kernel consistency probes, not new financial qualification.',
              'frozen_candidate_source_changed': False}
    with output.open('x') as f: f.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': result['passed'], 'tests': len(rows), 'output': str(output), 'sha256': sha(output)}, indent=2))
    return result['passed']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True); p.add_argument('--protocol-sha256', required=True)
    p.add_argument('--audit', type=Path, required=True); p.add_argument('--training', type=Path, required=True)
    p.add_argument('--financial-root', type=Path, required=True); p.add_argument('--work', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); raise SystemExit(0 if run(a.root, a.protocol_sha256, a.audit, a.training, a.financial_root, a.work, a.output) else 1)
