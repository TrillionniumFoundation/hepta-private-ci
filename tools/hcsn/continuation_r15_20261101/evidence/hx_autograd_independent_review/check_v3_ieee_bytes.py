"""Resolve signed-zero precision in the earlier exact numerical comparison."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

import torch

ROOT = Path('/tmp/hcsn-autograd-adapter-v3')
V2 = Path('/tmp/hcsn-autograd-adapter-v2')
OUT = Path(__file__).with_name('V3_IEEE_BYTE_IDENTITY_ADDENDUM.json')
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(ROOT/'hx_autograd.py') == '8117df2cae6b17612d7537b96d72ca74a340bb5356e61bbc3f73b9fe478aa870'
assert sha(ROOT/'ADAPTER_FIXTURES.json') == 'c94ccdbc02f783c99c5de47032ebc883d7de0b6ff9efc02857ac846547c43bee'
sys.path.insert(0, str(ROOT))
from hx_autograd import FrozenBackend, HXOperator

cases = json.loads((ROOT/'ADAPTER_FIXTURES.json').read_text())['cases']
raw = json.loads(gzip.decompress((V2/'GRADIENT_AUDIT_V2.json.gz').read_bytes()))['base_matrices']
readout = json.loads((V2/'READOUT_VJP_EVIDENCE.json').read_text())['channel_rows']
backend = FrozenBackend('/tmp/hcsn-compiled-recovery')
rows = []
for case, old_raw, old_readout in zip(cases, raw, readout, strict=True):
    assert case['id'] == old_raw['case'] == old_readout['case']
    for method, width in [('raw', 5), ('readout', 3)]:
        packed = torch.tensor(case['packed'], dtype=torch.float32, requires_grad=True)
        operator = HXOperator('/tmp/hcsn-compiled-recovery', case['coordinate'], backend)
        fields = operator(packed) if method == 'raw' else operator.readout(packed)
        previous = old_raw['features'][:5] if method == 'raw' else old_readout['values']
        for i in range(width):
            derivative = torch.autograd.grad(fields[i], packed, retain_graph=True)[0]
            expected = old_raw['autograd_jacobian'][i] if method == 'raw' else old_readout['actual_basis_vjp'][i]
            observed_v = fields[i].detach().numpy().tobytes()
            expected_v = torch.tensor(previous[i], dtype=torch.float64).numpy().tobytes()
            observed_d = derivative.detach().contiguous().numpy().tobytes()
            expected_d = torch.tensor(expected, dtype=torch.float32).numpy().tobytes()
            rows.append({'case': case['id'], 'method': method, 'column': i,
                         'observed_value_hex': observed_v.hex(), 'v2_value_hex': expected_v.hex(),
                         'observed_gradient_hex': observed_d.hex(), 'v2_gradient_hex': expected_d.hex(),
                         'value_bytes_equal': observed_v == expected_v,
                         'gradient_bytes_equal': observed_d == expected_d})
backend.verify()
assert sha(ROOT/'hx_autograd.py') == '8117df2cae6b17612d7537b96d72ca74a340bb5356e61bbc3f73b9fe478aa870'
result = {'schema': 'hcsn.independent-v3-ieee-byte-identity.v1',
          'passed': len(rows) == 48 and all(r['value_bytes_equal'] and r['gradient_bytes_equal'] for r in rows),
          'reason': 'The earlier independent contract probe used torch.equal and scalar equality, which treat signed zeros as equal. This additive check compares actual IEEE storage bytes, including signed zero. Prior evidence is retained unchanged.',
          'script_sha256': sha(Path(__file__)), 'adapter_sha256': sha(ROOT/'hx_autograd.py'),
          'protocol_sha256': sha(ROOT/'ADAPTER_PROTOCOL.json'), 'fixture_sha256': sha(ROOT/'ADAPTER_FIXTURES.json'),
          'v2_raw_evidence_sha256': sha(V2/'GRADIENT_AUDIT_V2.json.gz'),
          'v2_readout_evidence_sha256': sha(V2/'READOUT_VJP_EVIDENCE.json'),
          'financial_calls': backend.calls, 'financial_states': backend.states, 'financial_oracle_calls': 0,
          'rows': rows, 'scope': 'Exact storage identity on the same six functional fixtures, not a new financial validation or performance claim.'}
with OUT.open('x') as stream:
    json.dump(result, stream, indent=2, allow_nan=False)
    stream.write('\n')
print(json.dumps({'passed': result['passed'], 'rows': len(rows), 'financial_calls': backend.calls,
                  'output': str(OUT), 'sha256': sha(OUT)}, indent=2))
raise SystemExit(0 if result['passed'] else 1)
