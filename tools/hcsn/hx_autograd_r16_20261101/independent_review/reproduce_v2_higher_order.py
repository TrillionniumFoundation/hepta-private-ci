"""Retain the observed V2 higher-order refusal defect without changing it.

These six calls use one existing functional fixture and the frozen FP64
backend. They neither evaluate a financial oracle nor test task quality.
"""
import hashlib
import json
from pathlib import Path
import sys

import torch


ADAPTER = Path('/tmp/hcsn-autograd-adapter-v2')
FINANCIAL = Path('/tmp/hcsn-compiled-recovery')
EXPECTED_ADAPTER = '51eebb33a39340d680afbb7a560f17fb2dbe9f17ec74e16dcf9dab6d7a7eefdf'
EXPECTED_PROTOCOL = 'd3ada27411e77ebc4be99dd96e7f6895fbd844e0fd985e7506d682088ee3f4ce'
EXPECTED_FIXTURES = 'c94ccdbc02f783c99c5de47032ebc883d7de0b6ff9efc02857ac846547c43bee'
OUTPUT = Path(__file__).with_name('V2_HIGHER_ORDER_DEFECT.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert digest(ADAPTER/'hx_autograd.py') == EXPECTED_ADAPTER
    assert digest(ADAPTER/'ADAPTER_PROTOCOL.json') == EXPECTED_PROTOCOL
    assert digest(ADAPTER/'ADAPTER_FIXTURES.json') == EXPECTED_FIXTURES
    sys.path.insert(0, str(ADAPTER))
    from hx_autograd import FrozenBackend, HXOperator

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    fixtures = json.loads((ADAPTER/'ADAPTER_FIXTURES.json').read_text())
    fixture = fixtures['cases'][0]
    assert fixture['id'] == 'baseline_continuation_asset'
    backend = FrozenBackend(FINANCIAL)
    rows = []
    for kind in ['rawE', 'rawE2', 'readoutE', 'readoutR', 'readoutX', 'readoutAll2']:
        packed = torch.tensor(fixture['packed'], dtype=torch.float32, requires_grad=True)
        operator = HXOperator(FINANCIAL, 'asset', backend)
        values = operator(packed) if kind.startswith('raw') else operator.readout(packed)
        loss = {
            'rawE': lambda: values[1],
            'rawE2': lambda: values[1].square(),
            'readoutE': lambda: values[0],
            'readoutR': lambda: values[1],
            'readoutX': lambda: values[2],
            'readoutAll2': lambda: values.square().sum(),
        }[kind]()
        row = {'case': kind, 'scalar': float(loss.detach()),
               'first_call': 'torch.autograd.grad(loss, packed, create_graph=True)[0]',
               'second_call': 'torch.autograd.grad(first.sum(), packed)[0]'}
        try:
            first = torch.autograd.grad(loss, packed, create_graph=True)[0]
            row.update(first_call_returned=True, first_vjp=first.detach().tolist(),
                       first_vjp_requires_grad=first.requires_grad)
        except Exception as error:
            row.update(first_call_returned=False, first_rejection_type=type(error).__name__,
                       first_rejection=str(error))
            rows.append(row)
            continue
        try:
            second = torch.autograd.grad(first.sum(), packed)[0]
            row.update(second_call_returned=True, returned_second=second.detach().tolist())
        except Exception as error:
            row.update(second_call_returned=False, second_rejection_type=type(error).__name__,
                       second_rejection=str(error))
        rows.append(row)
    backend.verify()
    assert digest(ADAPTER/'hx_autograd.py') == EXPECTED_ADAPTER
    result = {
        'schema': 'hcsn.independent-autograd-higher-order-defect.v1',
        'scope': 'A refusal-contract counterexample on an already opened functional fixture; no financial oracle and no change to first-order gates.',
        'adapter_sha256': EXPECTED_ADAPTER,
        'protocol_sha256': EXPECTED_PROTOCOL,
        'fixtures_sha256': EXPECTED_FIXTURES,
        'financial_binary_sha256': backend.protocol['binary_sha256'],
        'probe_script_sha256': digest(Path(__file__)),
        'fixed_fixture': fixture,
        'torch_version': torch.__version__,
        'financial_calls': backend.calls,
        'financial_states': backend.states,
        'financial_oracle_calls': 0,
        'rows': rows,
        'higher_order_refusal_contract_passed': all(not row['first_call_returned'] for row in rows),
        'returned_readout_second_derivatives': sum(row['case'].startswith('readout') and row.get('second_call_returned', False) for row in rows),
        'limitation': 'Returned second-order numbers are unsupported and must not be interpreted as financial Hessians. The existing first-order results are retained.',
    }
    with OUTPUT.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'output': str(OUTPUT), 'sha256': digest(OUTPUT),
                      'higher_order_refusal_contract_passed': result['higher_order_refusal_contract_passed'],
                      'returned_readout_second_derivatives': result['returned_readout_second_derivatives'],
                      'financial_calls': backend.calls}, indent=2))
    return 0 if result['higher_order_refusal_contract_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
