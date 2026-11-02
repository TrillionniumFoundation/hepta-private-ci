"""Small non-numerical negative tests for the independent result gate."""
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


def main(root, expected, audit_path, training_path, work, output):
    work.mkdir(parents=True, exist_ok=False)
    audit, training = read(audit_path), read(training_path)
    trials = []
    def trial(name, side, mutate, message):
        obj = copy.deepcopy(audit if side == 'audit' else training)
        mutate(obj)
        faulty = work/(name+'.json.gz')
        # Nonfinite syntax is deliberate only in the NaN rejection witness.
        faulty.write_bytes(gzip.compress((json.dumps(obj, indent=2, allow_nan=True)+'\n').encode(), mtime=0))
        args = [sys.executable, '-B', str(root/'check_recurrent_results.py'), '--root', str(root),
                '--protocol-sha256', expected, '--audit', str(faulty if side == 'audit' else audit_path),
                '--training', str(faulty if side == 'training' else training_path), '--output', str(work/(name+'_should_not_pass.json'))]
        run = subprocess.run(args, capture_output=True, text=True)
        trials.append({'id': name, 'changed_artifact': side, 'faulty_artifact_sha256': sha(faulty),
                       'returncode': run.returncode, 'expected_error_substring': message,
                       'stdout': run.stdout, 'stderr': run.stderr,
                       'passed': bool(run.returncode != 0 and message in run.stderr and not (work/(name+'_should_not_pass.json')).exists())})
    trial('missing_signed_fixture', 'audit', lambda d: d['signed_readout']['fixtures'].pop(), 'Signed fixture identity/count mismatch')
    trial('missing_training_iteration', 'training', lambda d: d['history'].pop(), 'Training count/input mismatch')
    trial('nonfinite_gradient', 'audit', lambda d: d['temporal']['comparisons']['step_theta']['observed'][0].__setitem__(0, float('nan')), 'Nonfinite JSON NaN')
    trial('corrupt_euler_drift', 'training', lambda d: d['final_trajectory']['drift_dx_da'][0][0].__setitem__(0, .5), 'Recorded Euler drift mismatch')
    trial('corrupt_early_theta_gradient', 'audit', lambda d: d['temporal']['comparisons']['step_theta']['observed'][0].__setitem__(0, .1), 'Recomputed gradient comparison failed')
    trial('erase_parameter_update', 'training', lambda d: d['trainable_parameters']['raw_theta'].__setitem__('final', [0.]*9), 'No final parameter update')
    trial('missing_crossing', 'audit', lambda d: d['temporal']['trajectory']['crossings'].pop(), 'Crossing count/identity mismatch')
    trial('wrong_protocol_binding', 'audit', lambda d: d.__setitem__('protocol_sha256', '0'*64), 'Receipt/protocol mismatch')
    result = {'schema': 'hcsn.hx-recurrent-checker-negative-tests.v1', 'passed': all(row['passed'] for row in trials),
              'protocol_sha256': expected, 'checker_sha256': sha(root/'check_recurrent_results.py'),
              'script_sha256': sha(__file__), 'audit_sha256': sha(audit_path), 'training_sha256': sha(training_path),
              'financial_kernel_calls': 0, 'training_reruns': 0, 'tests': trials,
              'scope': 'Deliberate receipt mutations, not new model evaluations or changes to frozen scientific gates.'}
    with output.open('x') as f:
        f.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': result['passed'], 'tests': len(trials), 'output': str(output), 'sha256': sha(output)}, indent=2))
    return result['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--protocol-sha256', required=True)
    parser.add_argument('--audit', type=Path, required=True); parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    raise SystemExit(0 if main(a.root, a.protocol_sha256, a.audit, a.training, a.work, a.output) else 1)
