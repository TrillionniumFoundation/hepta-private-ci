"""Independent refusal and first-order identity review on six fixed fixtures."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

import torch


ROOT = Path('/tmp/hcsn-autograd-adapter-v3')
V2 = Path('/tmp/hcsn-autograd-adapter-v2')
FINANCIAL = Path('/tmp/hcsn-compiled-recovery')
EXPECTED_ADAPTER = '8117df2cae6b17612d7537b96d72ca74a340bb5356e61bbc3f73b9fe478aa870'
EXPECTED_PROTOCOL = '9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72'
EXPECTED_FIXTURES = 'c94ccdbc02f783c99c5de47032ebc883d7de0b6ff9efc02857ac846547c43bee'
EXPECTED_MESSAGE = 'HXOperator supports first-order reverse AD only; create_graph=True is unsupported'
OUTPUT = Path(__file__).with_name('V3_INDEPENDENT_CONTRACT_REVIEW.json')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sha(ROOT/'hx_autograd.py') == EXPECTED_ADAPTER
    assert sha(ROOT/'ADAPTER_PROTOCOL.json') == EXPECTED_PROTOCOL
    assert sha(ROOT/'ADAPTER_FIXTURES.json') == EXPECTED_FIXTURES
    assert sha(V2/'GRADIENT_AUDIT_V2.json.gz') == 'ac15ecd17abecb7cc4e18058f464689ff07cd7478bf5a33f735290af7c9cf022'
    assert sha(V2/'READOUT_VJP_EVIDENCE.json') == '8f6ebd643691ac71635d94fca0e7a4a48a4e2fb72d8e31d7f486963b52426edb'
    sys.path.insert(0, str(ROOT))
    from hx_autograd import FrozenBackend, HXOperator

    protocol = json.loads((ROOT/'ADAPTER_PROTOCOL.json').read_text())
    for name, digest in protocol['source_sha256'].items():
        assert sha(ROOT/name) == digest
    cases = json.loads((ROOT/'ADAPTER_FIXTURES.json').read_text())['cases']
    raw_records = json.loads(gzip.decompress((V2/'GRADIENT_AUDIT_V2.json.gz').read_bytes()))['base_matrices']
    readout_records = json.loads((V2/'READOUT_VJP_EVIDENCE.json').read_text())['channel_rows']
    backend = FrozenBackend(FINANCIAL)
    rows = []
    for case, previous_raw, previous_readout in zip(cases, raw_records, readout_records, strict=True):
        assert case['id'] == previous_raw['case'] == previous_readout['case']
        for method, width in [('raw', 5), ('readout', 3)]:
            for column in range(width):
                packed = torch.tensor(case['packed'], dtype=torch.float32, requires_grad=True)
                operator = HXOperator(FINANCIAL, case['coordinate'], backend)
                fields = operator(packed) if method == 'raw' else operator.readout(packed)
                first = torch.autograd.grad(fields[column], packed, retain_graph=True)[0]
                old_values = previous_raw['features'][:5] if method == 'raw' else previous_readout['values']
                old_gradient = previous_raw['autograd_jacobian'][column] if method == 'raw' else previous_readout['actual_basis_vjp'][column]
                row = {
                    'case': case['id'], 'coordinate': case['coordinate'], 'method': method, 'column': column,
                    'value_float64_equal_to_v2': fields[column].detach().item() == old_values[column],
                    'first_vjp_float32_bit_equal_to_v2': torch.equal(first, torch.tensor(old_gradient, dtype=torch.float32)),
                    'output_dtype': str(fields.dtype), 'first_gradient_dtype': str(first.dtype),
                }
                try:
                    unsupported = torch.autograd.grad(fields[column], packed, create_graph=True)[0]
                    row.update(first_create_graph_call_rejected=False, unsupported_return=unsupported.detach().tolist())
                except Exception as error:
                    row.update(first_create_graph_call_rejected=type(error) is RuntimeError and str(error) == EXPECTED_MESSAGE,
                               error_type=type(error).__name__, message=str(error))
                row['passed'] = row['value_float64_equal_to_v2'] and row['first_vjp_float32_bit_equal_to_v2'] and row['first_create_graph_call_rejected']
                rows.append(row)
    backend.verify()
    assert sha(ROOT/'hx_autograd.py') == EXPECTED_ADAPTER
    assert sha(ROOT/'ADAPTER_PROTOCOL.json') == EXPECTED_PROTOCOL
    for name, digest in protocol['source_sha256'].items():
        assert sha(ROOT/name) == digest
    result = {
        'schema': 'hcsn.independent-autograd-v3-contract-review.v1',
        'passed': len(rows) == 48 and all(row['passed'] for row in rows),
        'scope': 'Independent first-order identity and explicit higher-order refusal on the original six opened functional fixtures. No new financial oracle, second-order financial implementation, training efficacy or generalization claim.',
        'adapter_sha256': EXPECTED_ADAPTER, 'protocol_sha256': EXPECTED_PROTOCOL,
        'fixture_sha256': EXPECTED_FIXTURES, 'probe_script_sha256': sha(Path(__file__)),
        'financial_binary_sha256': backend.protocol['binary_sha256'],
        'torch_version': torch.__version__, 'financial_calls': backend.calls,
        'financial_states': backend.states, 'financial_oracle_calls': 0,
        'first_order_bit_identity_passed': sum(row['first_vjp_float32_bit_equal_to_v2'] for row in rows),
        'first_create_graph_refusals': sum(row['first_create_graph_call_rejected'] for row in rows),
        'rows': rows,
        'identity_x_note': 'The log-distance readout x is an identity in its independent state and has no financial Hessian claim. This combined readout conservatively rejects create_graph on all channels because it retains the raw financial graph.',
        'financial_and_adapter_frozen_sources_unchanged': True,
    }
    with OUTPUT.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'output': str(OUTPUT), 'sha256': sha(OUTPUT), 'passed': result['passed'],
                      'rows': len(rows), 'first_order_bit_identity_passed': result['first_order_bit_identity_passed'],
                      'first_create_graph_refusals': result['first_create_graph_refusals'],
                      'financial_calls': backend.calls}, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
