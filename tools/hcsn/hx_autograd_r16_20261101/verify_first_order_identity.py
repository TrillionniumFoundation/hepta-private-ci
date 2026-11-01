"""Exact normalized-record comparison against preserved V2 first-order runs."""
import argparse
import gzip
import json
from pathlib import Path

from adapter_common import ROOT, sha, verify, write


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def run(previous_root, expected, output):
    protocol = verify(expected)
    history = protocol['first_order_regression_identity']
    pairs = [('gradients', previous_root/'GRADIENT_AUDIT_V2.json.gz', ROOT/'GRADIENT_AUDIT_V3.json.gz',
              ('base_matrices', 'directional_checks')),
             ('training', previous_root/'TRAINING_SMOKE_V2.json.gz', ROOT/'TRAINING_SMOKE_V3.json.gz',
              ('inputs', 'targets', 'initial_predictions', 'final_predictions', 'initial_loss', 'final_loss',
               'parameter_update_norms', 'parameters', 'history'))]
    results = []
    for name, old, new, keys in pairs:
        if sha(old) != history[name+'_sha256']:
            raise ValueError('Wrong preserved V2 '+name+' evidence')
        before, after = read(old), read(new)
        if after['protocol_sha256'] != expected:
            raise ValueError('New evidence protocol mismatch')
        fields = {key: encoded(before[key]) == encoded(after[key]) for key in keys}
        results.append({'dataset': name, 'previous_sha256': sha(old), 'current_sha256': sha(new),
                        'exact_field_identity': fields, 'passed': all(fields.values())})
    verify(expected)
    result = {'schema': 'hcsn.hx-autograd-first-order-identity.v1', 'passed': all(r['passed'] for r in results),
              'protocol_sha256': expected, 'script_sha256': sha(Path(__file__)),
              'scope': 'Exact canonical JSON byte identity of every first-order matrix/directional record and all 80 training steps, predictions and parameter tensors. Timing/protocol metadata and newly extended rejection checks are intentionally separate.',
              'results': results}
    artifact = write(output, result)
    print(json.dumps({'artifact': artifact, 'passed': result['passed'], 'results': results}, indent=2))
    return result['passed']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--previous-root', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(0 if run(a.previous_root, a.protocol_sha256, a.output) else 1)
