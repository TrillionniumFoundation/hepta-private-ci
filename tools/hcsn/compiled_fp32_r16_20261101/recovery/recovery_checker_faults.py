"""Exercise cheap checker guards without opening any financial reference.

The control reaches a deliberate sentinel before the first MP80 field call.
No artificial fixture is ever a numerical pass and no candidate is invoked.
"""
import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parent


class NumericalPhaseBlocked(RuntimeError):
    pass


def stop_reference(*args, **kwargs):
    raise NumericalPhaseBlocked('Deliberate pre-reference sentinel; no numerical field evaluated')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(protocol_path, expected, oracle_path, output):
    if output.exists():
        raise ValueError('Receipt is create-only')
    protocol = json.loads(protocol_path.read_text())
    spec = importlib.util.spec_from_file_location('checker_under_test', ROOT/'recovery_check.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    oracle = types.ModuleType('frozen_reference')
    oracle.fields = stop_reference
    oracle.jacobian = stop_reference
    old_module = sys.modules.get('frozen_reference')
    sys.modules['frozen_reference'] = oracle
    points = json.loads((ROOT/'RECOVERY_CASES_V1.json').read_text())['rows']
    common = {k: protocol[k] for k in ('binary_sha256', 'source_sha256')}
    common['protocol_sha256'] = expected
    base_rows = [{'case': point['id'], 'slot': slot, 'coordinate': 'log_distance', 'state': 0.,
                  'values': [0.]*5, 'jacobian': [[0.]*10 for _ in range(5)]} for point in points for slot in range(6)]
    base = {'reference': {**common, 'cases': [{**point, 'independently_valid': True} for point in points],
                          'rows': [{**row, 'jacobian_first': copy.deepcopy(row['jacobian'])} for row in base_rows]}}
    for mode in ('float64', 'float32', 'compensated32'):
        base[mode] = {**common, 'mode': mode, 'rows': [{**row, 'status': 0} for row in base_rows]}

    def emit(directory, payload):
        artifacts = {}
        for mode in ('reference', 'float64', 'float32', 'compensated32'):
            name = 'REFERENCE.json.gz' if mode == 'reference' else mode+'.json.gz'
            if mode != 'reference':
                payload[mode]['reference_sha256'] = artifacts['reference']['sha256']
            path = directory/name
            path.write_bytes(gzip.compress(json.dumps(payload[mode], separators=(',', ':')).encode(), mtime=0))
            artifacts[mode] = {'file': name, 'sha256': sha(path)}
        (directory/'INDEX.json').write_text(json.dumps({**common, 'artifacts': artifacts}))

    trials = []
    mutations = [
        ('complete_synthetic_preflight', None, True),
        ('native_fp32_recorded_rejection', lambda p: p['float32']['rows'][0].update(status=1, error='Injected diagnostic failure'), True),
        ('missing_required_row', lambda p: p['compensated32']['rows'].pop(), False),
        ('duplicate_reference_id', lambda p: p['reference']['rows'][1].update(slot=0), False),
        ('nine_jacobian_columns', lambda p: p['compensated32']['rows'][0]['jacobian'][0].pop(), False),
        ('nan_json_token', lambda p: p['compensated32']['rows'][0]['values'].__setitem__(0, float('nan')), False),
        ('required_mode_rejection', lambda p: p['compensated32']['rows'][0].update(status=1, error='Injected diagnostic failure'), False),
        ('parameter_substitution', lambda p: p['reference']['cases'][0]['theta'].__setitem__(0, .125), False),
        ('mode_source_substitution', lambda p: p['compensated32'].update(source_sha256={}), False),
        ('mode_state_substitution', lambda p: p['compensated32']['rows'][0].update(state=1.), False),
        ('mode_reference_substitution', None, False),
        ('artifact_bytes_substitution', None, False),
    ]
    try:
        with tempfile.TemporaryDirectory(prefix='hcsn-checker-preflight-') as temporary:
            for name, mutate, expected_reach in mutations:
                directory = Path(temporary)/name
                directory.mkdir()
                payload = copy.deepcopy(base)
                if mutate:
                    mutate(payload)
                emit(directory, payload)
                if name == 'mode_reference_substitution':
                    path = directory/'compensated32.json.gz'
                    value = json.loads(gzip.decompress(path.read_bytes()))
                    value['reference_sha256'] = '0'*64
                    path.write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))
                    index = json.loads((directory/'INDEX.json').read_text())
                    index['artifacts']['compensated32']['sha256'] = sha(path)
                    (directory/'INDEX.json').write_text(json.dumps(index))
                if name == 'artifact_bytes_substitution':
                    with (directory/'compensated32.json.gz').open('ab') as f:
                        f.write(b'changed')
                try:
                    checker.check(protocol_path, expected, directory, oracle_path)
                    raise AssertionError('Synthetic fixture reached an actual gate result')
                except NumericalPhaseBlocked as error:
                    reached, detail = True, str(error)
                except checker.Invalid as error:
                    reached, detail = False, str(error)
                trials.append({'trial': name, 'expected_reach_pre_reference_sentinel': expected_reach,
                               'reached_pre_reference_sentinel': reached, 'passed': reached == expected_reach, 'detail': detail})
    finally:
        if old_module is None:
            sys.modules.pop('frozen_reference', None)
        else:
            sys.modules['frozen_reference'] = old_module
    result = {'schema': 'hcsn.recovery-checker-preflight-faults.v1', 'all_checks_passed': all(r['passed'] for r in trials),
              'numerical_evaluations': 0, 'scope': 'Only cheap rejection and recorded ordinary-FP32 failure handling. No numerical admission from synthetic controls.',
              'checker_sha256': sha(ROOT/'recovery_check.py'), 'script_sha256': sha(Path(__file__)), 'protocol_sha256': expected,
              'trials': trials}
    with output.open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write('\n')
    print(json.dumps(result, indent=2))
    return result['all_checks_passed']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--protocol', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True)
    p.add_argument('--oracle-pythonpath', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(0 if run(a.protocol, a.protocol_sha256, a.oracle_pythonpath, a.output) else 1)
