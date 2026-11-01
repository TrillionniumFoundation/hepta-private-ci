"""First-order VJP/feature checks using represented-endpoint finite differences.

No financial MP80 oracle is imported. These are fixed integration fixtures,
not a new financial-model holdout or a replacement for the R16 kernel gate.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from adapter_common import ROOT, verify, write
from hx_autograd import FrozenBackend, HXOperator


def independent_features(backend, packed, coordinate):
    raw, jacobian = backend.evaluate_numpy(np.asarray(packed, dtype=np.float32).reshape(1, 10), coordinate)
    raw, jacobian = raw[0], jacobian[0]
    value = np.r_[raw, 1.-(1.-raw[2])**2,
                  np.log(float(packed[9])/raw[0]) if coordinate == 'asset' else float(packed[9])]
    jx = -jacobian[0]/raw[0] if coordinate == 'asset' else np.zeros(10)
    jx[9] += 1./float(packed[9]) if coordinate == 'asset' else 1.
    derivative = np.vstack((jacobian, 2*(1-raw[2])*jacobian[2], jx))
    return value, derivative


def side(packed, features, coordinate):
    if coordinate == 'asset':
        return 'default' if float(packed[9]) <= features[0] else 'continuation'
    return 'right_boundary' if packed[9] == 0 else 'continuation'


def run(frozen_root, expected, output):
    protocol = verify(expected)
    fixtures = json.loads((ROOT/'ADAPTER_FIXTURES.json').read_text())
    backend = FrozenBackend(frozen_root)
    matrices, differences, errors = [], [], []
    start, cpu = time.perf_counter(), time.process_time()
    for case in fixtures['cases']:
        packed = np.asarray(case['packed'], dtype=np.float32)
        coordinate = case['coordinate']
        layer = HXOperator(frozen_root, coordinate, backend)
        x = torch.tensor(packed, dtype=torch.float32, requires_grad=True)
        observed = layer.features(x)
        autograd = np.stack([torch.autograd.grad(observed[i], x, retain_graph=True)[0].detach().numpy() for i in range(7)]).astype(np.float64)
        values, chain = independent_features(backend, packed, coordinate)
        value_error = float(np.max(abs(observed.detach().numpy()-values)/np.maximum(1., abs(values))))
        chain_error = float(np.max(abs(autograd-chain)/np.maximum(1., abs(chain))))
        matrices.append({'case': case['id'], 'coordinate': coordinate, 'packed': packed.tolist(),
                         'features': values.tolist(), 'autograd_jacobian': autograd.tolist(),
                         'independent_chain_jacobian': chain.tolist(), 'value_error': value_error,
                         'chain_error': chain_error, 'output_dtype': str(observed.dtype),
                         'passed': value_error <= protocol['gates']['feature_value_scaled'] and chain_error <= protocol['gates']['chain_jacobian_scaled']})
        scale = np.maximum(.01, abs(packed.astype(np.float64)))
        base_side = side(packed, values, coordinate)
        for direction_index, direction in enumerate(case['directions']):
            direction = np.asarray(direction, dtype=np.float64)
            delta = scale*direction
            for h in protocol['finite_difference_steps']:
                record = {'case': case['id'], 'direction_index': direction_index, 'step': h,
                          'nominal_direction': delta.tolist(), 'base_side': base_side}
                try:
                    if base_side == 'right_boundary' and direction[9] != 0:
                        if np.any(direction[:9] != 0) or direction[9] <= 0:
                            raise ValueError('Boundary right stencil must be a positive state-only direction')
                        one = (packed.astype(np.float64)+h*delta).astype(np.float32)
                        two = (packed.astype(np.float64)+2*h*delta).astype(np.float32)
                        v1, _ = independent_features(backend, one, coordinate)
                        v2, _ = independent_features(backend, two, coordinate)
                        a, b = float(one[9])-float(packed[9]), float(two[9])-float(packed[9])
                        if not 0 < a < b:
                            raise ValueError('Unresolved represented one-sided stencil')
                        weights = np.array([-(a+b)/(a*b), b/(a*(b-a)), -a/(b*(b-a))])
                        finite_difference = (weights[0]*values+weights[1]*v1+weights[2]*v2)*delta[9]
                        effective = delta
                        endpoint_sides = [side(one, v1, coordinate), side(two, v2, coordinate)]
                        if endpoint_sides != ['continuation', 'continuation']:
                            raise ValueError('Right stencil left the continuation branch')
                        record.update(stencil='represented three-point right derivative',
                                      endpoints=[one.tolist(), two.tolist()], endpoint_values=[v1.tolist(), v2.tolist()],
                                      actual_node_distances=[a, b], physical_derivative_weights=weights.tolist(), endpoint_sides=endpoint_sides)
                    else:
                        plus = (packed.astype(np.float64)+h*delta).astype(np.float32)
                        minus = (packed.astype(np.float64)-h*delta).astype(np.float32)
                        vp, _ = independent_features(backend, plus, coordinate)
                        vm, _ = independent_features(backend, minus, coordinate)
                        effective = (plus.astype(np.float64)-minus.astype(np.float64))/(2*h)
                        midpoint = (plus.astype(np.float64)+minus.astype(np.float64))/2-packed.astype(np.float64)
                        if not np.any(effective):
                            raise ValueError('Direction disappeared under input quantization')
                        endpoint_sides = [side(plus, vp, coordinate), side(minus, vm, coordinate)]
                        if endpoint_sides != [base_side, base_side]:
                            raise ValueError('Central finite difference crossed a branch')
                        finite_difference = (vp-vm)/(2*h)
                        record.update(stencil='represented central endpoints',
                                      endpoints=[plus.tolist(), minus.tolist()], endpoint_values=[vp.tolist(), vm.tolist()],
                                      midpoint_offset=midpoint.tolist(), endpoint_sides=endpoint_sides)
                    predicted = autograd@effective
                    scaled = abs(finite_difference-predicted)/np.maximum(1., abs(predicted))
                    passed = bool(np.all(np.isfinite(scaled)) and np.max(scaled) <= protocol['gates']['directional_difference_scaled'])
                    record.update(effective_direction=effective.tolist(), autograd_directional=predicted.tolist(),
                                  finite_difference=finite_difference.tolist(), scaled_error=scaled.tolist(),
                                  max_scaled_error=float(np.max(scaled)), passed=passed)
                except Exception as error:
                    record.update(passed=False, error=repr(error))
                differences.append(record)

    contract = []
    base = torch.tensor(fixtures['cases'][0]['packed'], dtype=torch.float32, requires_grad=True)
    layer = HXOperator(frozen_root, 'asset', backend)

    def rejected(label, operation, expected_message=None):
        try:
            operation()
            contract.append({'check': label, 'passed': False, 'error': 'Invalid operation unexpectedly accepted'})
        except (TypeError, ValueError, ArithmeticError, RuntimeError) as error:
            contract.append({'check': label, 'passed': expected_message is None or expected_message in str(error), 'rejection': str(error)})

    rejected('float64 input is not silently downcast', lambda: layer(base.detach().to(torch.float64)))
    rejected('non-CPU input', lambda: layer(torch.empty(10, dtype=torch.float32, device='meta')))
    rejected('wrong feature count', lambda: layer(base[:9]))
    rejected('empty batch', lambda: layer(torch.empty(0, 10, dtype=torch.float32)))
    rejected('nonfinite input', lambda: layer(torch.full((10,), float('nan'), dtype=torch.float32)))
    bad_asset = base.detach().clone(); bad_asset[9] = 0
    rejected('nonpositive asset state', lambda: layer(bad_asset))
    bad_margin = base.detach().clone(); bad_margin[9] = -.1
    rejected('negative independent log-margin', lambda: HXOperator(frozen_root, 'log_distance', backend)(bad_margin))
    rejected('unknown coordinate', lambda: HXOperator(frozen_root, 'unknown', backend))

    def upstream(weight):
        x = base.detach().clone().requires_grad_()
        return torch.autograd.grad(layer(x).sum()*weight, x)

    rejected('nonfinite upstream gradient', lambda: upstream(float('inf')))
    rejected('float32 gradient overflow', lambda: upstream(1e300))

    def second_derivative():
        x = base.detach().clone().requires_grad_()
        first = torch.autograd.grad(layer(x)[1].square(), x, create_graph=True)[0]
        return torch.autograd.grad(first.sum(), x)

    rejected('double backward explicitly unsupported', second_derivative)
    for coordinate, fixture_index in (('asset', 0), ('log_distance', 2)):
        for method, count in (('raw', 5), ('readout', 3)):
            for column in range(count):
                def higher_order_vjp(coordinate=coordinate, fixture_index=fixture_index, method=method, column=column):
                    x = torch.tensor(fixtures['cases'][fixture_index]['packed'], dtype=torch.float32, requires_grad=True)
                    operator = HXOperator(frozen_root, coordinate, backend)
                    fields = operator(x) if method == 'raw' else operator.readout(x)
                    return torch.autograd.grad(fields[column], x, create_graph=True)
                rejected(f'first higher-order VJP rejects {coordinate}/{method}/{column}', higher_order_vjp,
                         'HXOperator supports first-order reverse AD only; create_graph=True is unsupported')
    batch = torch.tensor([fixtures['cases'][0]['packed'], fixtures['cases'][1]['packed']], dtype=torch.float32).T.contiguous().T.requires_grad_()
    batch_values = layer.features(batch)
    batch_gradient = torch.autograd.grad(batch_values.sum(), batch)[0]
    expected_batch = np.stack([np.asarray(m['independent_chain_jacobian']).sum(axis=0) for m in matrices[:2]])
    batch_error = float(np.max(abs(batch_gradient.detach().numpy()-expected_batch)/np.maximum(1., abs(expected_batch))))
    contract.append({'check': 'noncontiguous batched VJP and float32 leaf gradient', 'input_contiguous': batch.is_contiguous(),
                     'output_shape': list(batch_values.shape), 'gradient_dtype': str(batch_gradient.dtype), 'error': batch_error,
                     'passed': not batch.is_contiguous() and batch_gradient.dtype == torch.float32 and batch_error <= protocol['gates']['chain_jacobian_scaled']})
    default_matrix = matrices[1]
    contract.append({'check': 'default R saturated while x preserves positive-state information',
                     'passed': default_matrix['features'][5] == 1. and default_matrix['features'][6] < 0
                     and np.max(abs(np.asarray(default_matrix['autograd_jacobian'])[5])) == 0
                     and np.linalg.norm(np.asarray(default_matrix['autograd_jacobian'])[6]) > 0})
    for m in matrices:
        if m['coordinate'] == 'log_distance':
            expected_x = np.zeros(10); expected_x[9] = 1
            contract.append({'check': 'independent x does not double-count boundary sensitivity: '+m['case'],
                             'passed': np.array_equal(np.asarray(m['autograd_jacobian'])[6], expected_x)})
    # NumPy predicates can produce np.bool_; normalize receipt-only flags.
    for record in contract:
        record['passed'] = bool(record['passed'])
    backend.verify(); verify(expected)
    required = len(fixtures['cases'])*14*len(protocol['finite_difference_steps'])
    passed = len(differences) == required and all(m['passed'] for m in matrices) and all(r['passed'] for r in differences) and all(r['passed'] for r in contract)
    result = {'schema': 'hcsn.hx-autograd-gradient-audit.v1', 'gate_passed': bool(passed), 'protocol_sha256': expected,
              'financial_protocol_sha256': protocol['financial_protocol_sha256'], 'binary_sha256': backend.protocol['binary_sha256'],
              'scope': 'Fixed first-order integration checks; represented-endpoint finite differences independent of the financial MP80 oracle. No higher-order, GPU or task-quality qualification.',
              'summary': {'cases': len(matrices), 'directional_checks': len(differences), 'passed_directional_checks': sum(r['passed'] for r in differences),
                          'max_directional_error': max((r.get('max_scaled_error', 0.) for r in differences), default=0.),
                          'max_chain_error': max(m['chain_error'] for m in matrices), 'contract_checks': len(contract),
                          'contract_passed': sum(r['passed'] for r in contract)},
              'runtime': {'torch': torch.__version__, 'numpy': np.__version__, 'cuda_available': torch.cuda.is_available(),
                          'wall_seconds': time.perf_counter()-start, 'process_cpu_seconds': time.process_time()-cpu,
                          'financial_calls': backend.calls, 'financial_states': backend.states},
              'base_matrices': matrices, 'directional_checks': differences, 'contract_checks': contract, 'errors': errors}
    artifact = write(output, result)
    print(json.dumps({'artifact': artifact, 'gate_passed': passed, 'summary': result['summary'], 'runtime': result['runtime']}, indent=2))
    return passed


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--frozen-root', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    try:
        passed = run(a.frozen_root, a.protocol_sha256, a.output)
    except Exception as error:
        if not a.output.exists():
            write(a.output, {'gate_passed': False, 'protocol_sha256': a.protocol_sha256, 'error': repr(error)})
        print(json.dumps({'gate_passed': False, 'error': repr(error)}))
        raise SystemExit(1)
    raise SystemExit(0 if passed else 1)
