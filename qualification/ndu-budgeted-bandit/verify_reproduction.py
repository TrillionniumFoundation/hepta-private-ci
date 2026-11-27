"""Compare a fresh synthetic execution with frozen local diagnostic evidence."""
import json
import math
import sys
from pathlib import Path


IGNORED_ROOT_FIELD = 'harness_wall_seconds_not_model_cost'


def compare(actual, expected, path='root'):
    if type(actual) is not type(expected):
        raise ValueError(f'{path}: value type differs')
    if isinstance(expected, dict):
        keys = set(expected)
        if set(actual) != keys:
            raise ValueError(f'{path}: field set differs')
        for key in sorted(keys):
            if path == 'root' and key == IGNORED_ROOT_FIELD:
                if not isinstance(actual[key], (int, float)) or not math.isfinite(actual[key]) or actual[key] < 0:
                    raise ValueError('invalid harness duration')
                continue
            compare(actual[key], expected[key], f'{path}.{key}')
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError(f'{path}: length differs')
        for i, (a, e) in enumerate(zip(actual, expected)):
            compare(a, e, f'{path}[{i}]')
    elif isinstance(expected, float):
        if not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f'{path}: numeric result differs')
    elif actual != expected:
        raise ValueError(f'{path}: result differs')


def verify(actual):
    expected = json.loads((Path(__file__).parent / 'evidence' / 'expected-results.json').read_text())
    compare(actual, expected)
    print('Reproduced all 32 seeds / 128 scenario rows / 384 policy trajectories.')
    print('SYNTHETIC_ONLY; original negative results retained; all six scientific blockers OPEN.')
    print(json.dumps({'checks': actual['checks'], 'summary': actual['summary']}, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 verify_reproduction.py FRESH_RESULTS_JSON')
    verify(json.loads(Path(sys.argv[1]).read_text()))
