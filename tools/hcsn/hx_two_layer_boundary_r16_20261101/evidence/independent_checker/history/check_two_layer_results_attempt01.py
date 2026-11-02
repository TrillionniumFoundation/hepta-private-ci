"""Independent record gate for the frozen two-layer first-order experiment.

Only NumPy algebra and sealed files are used. Archived financial values and
Jacobians are inputs, not a second financial oracle. No model, optimizer,
PyTorch, shared library, or new financial point is executed by this checker.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np

MODES = ('full', 'drive_only', 'conditioning_only', 'both_detached')
CONTRACTS = {name: 'ValueError' for name in (
    'bad_shared_theta_shape', 'bad_batched_theta_shape', 'empty_z', 'nan_z',
    'positive_infinite_z', 'negative_infinite_z', 'nan_theta',
    'exp_overflow', 'exp_underflow',
)}
CONTRACTS.update({'float64_z': 'TypeError', 'float64_theta': 'TypeError',
                  'financial_reject_propagates': 'ArithmeticError'})
TRACE_CHECKS = {
    'state_shape', 'state_finite', 'fixed_initial_state', 'bounded_z',
    'bounded_adaptation', 'layer1_boundary_constant_within_rollout',
    'layer2_boundary_changes_within_used_steps', 'theta2_shape_and_bound',
} | {layer+'_'+name for layer in ('layer1', 'layer2') for name in (
    'shapes', 'finite_positive_b_V', 'actual_default_values', 'Q_R_range')}
IDENTIFICATION_CHECKS = {
    'four_modes_present', 'conditioning_only_upstream_gradient_nonzero',
    'direct_boundary_conditioning_path_nonzero', 'full_upstream_gradient_nonzero',
    'both_detached_upstream_gradient_zero',
    'both_detached_layer1_initial_state_gradient_zero',
    'both_detached_external_u1_gradient_zero',
    'normal_initial_layer1_state_gradient_nonzero',
    'normal_early_drive1_gradient_nonzero',
} | {mode+'_forward_exact_numerical_equality' for mode in MODES[1:]}
TRAINING_CHECKS = TRACE_CHECKS | {
    'complete_training_history', 'only_eighteen_raw_parameters',
    'finite_final_loss', 'finite_parameters_and_gradients',
    'layer1_parameters_updated', 'layer2_parameters_updated',
}
FINANCIAL_PROTOCOL = '76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0'
FINANCIAL_BINARY = 'a96fbe8ee36be2fdaa2a5894462f415f9724acf199ae31745c471092c26f6615'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key: '+key)
        result[key] = value
    return result


def finite_json(value):
    if isinstance(value, float):
        require(math.isfinite(value), 'Nonfinite JSON number')
    elif isinstance(value, dict):
        for child in value.values():
            finite_json(child)
    elif isinstance(value, list):
        for child in value:
            finite_json(child)


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    if path.name.endswith('.gz'):
        raw = gzip.decompress(raw)
    value = json.loads(raw, object_pairs_hook=unique_object)
    finite_json(value)
    return value


def seal(path, expected, seals):
    path = Path(path).resolve()
    digest = sha(path)
    require(expected is None or digest == expected, 'File identity mismatch: '+str(path))
    require(str(path) not in seals or seals[str(path)] == digest, 'File changed while binding')
    seals[str(path)] = digest


def array(value, shape):
    native = np.asarray(value)
    require(native.dtype.kind in 'iuf', 'Expected numeric record array')
    result = native.astype(np.float64)
    require(result.shape == shape and np.isfinite(result).all(), 'Wrong shape or nonfinite array: '+str(shape))
    return result


def words(value, shape):
    result = array(value, shape)
    with np.errstate(over='ignore'):
        converted = result.astype(np.float32)
    require(np.array_equal(result, converted.astype(np.float64)), 'Record is not exact FP32 words')
    return converted


def close(observed, expected, gates, label):
    expected = np.asarray(expected, dtype=np.float64)
    observed = array(observed, expected.shape)
    require(np.isfinite(expected).all(), 'Nonfinite reference '+label)
    allowance = gates['gradient_atol']+gates['gradient_rtol']*np.abs(expected)
    require(np.all(np.abs(observed-expected) <= allowance), 'Comparison failed: '+label)


def ulp_close(observed, expected, gates, label):
    expected = np.asarray(expected, dtype=np.float32)
    observed = words(observed, expected.shape).astype(np.float64)
    require(np.isfinite(expected).all(), 'Nonfinite represented reference '+label)
    allowance = gates['fp32_transcendental_ulps']*np.abs(np.spacing(expected)).astype(np.float64)
    require(np.all(np.abs(observed-expected.astype(np.float64)) <= allowance), 'FP32 nonlinear record mismatch: '+label)


def comparison(record, observed, reference, gates, label):
    observed = np.asarray(observed, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    require(record['passed'] is True, 'Writer comparison failed: '+label)
    require(np.array_equal(array(record['observed'], observed.shape), observed), 'Comparison observed binding: '+label)
    stored_reference = array(record['reference'], reference.shape)
    close(stored_reference, reference, gates, label+' stored reference')
    close(observed, reference, gates, label)
    error = np.abs(observed-stored_reference)
    allowance = gates['gradient_atol']+gates['gradient_rtol']*np.abs(stored_reference)
    require(record['max_absolute_error'] == float(error.max()) and record['max_error_over_allowance'] == float((error/allowance).max()), 'Comparison error summary mismatch: '+label)


def flags(record, expected_names, label):
    require(set(record) == set(expected_names) and all(v is True for v in record.values()), 'Missing or failed flags: '+label)


def check_loss(value, state, data, gates):
    expected = np.mean((state[-1, :, 2]-np.asarray(data['target_z2']))**2)
    expected += data['loss_a_weight']*np.mean((state[-1, :, 3]-np.asarray(data['target_a2']))**2)
    close(value, expected, gates, 'terminal physical loss')


def check_trace(row, data, protocol, raw1, raw2, mode, internal):
    c, g = protocol['cell'], protocol['gates']
    T, B = c['steps'], protocol['experiment']['batch_size']
    require(row['state_order'] == ['z1', 'a1', 'z2', 'a2'] and row['gradient_mode'] == mode, 'State/mode contract changed')
    state = words(row['state'], (T+1, B, 4))
    require(np.array_equal(state[0], words(data['initial_state'], (B, 4))), 'Initial physical state changed')
    require(np.min(state[..., [0, 2]]) >= g['min_z'] and np.max(state[..., [0, 2]]) <= g['max_z'], 'Physical state outside frozen range')
    require(np.min(state[..., [1, 3]]) >= -g['range_tolerance'] and np.max(state[..., [1, 3]]) <= g['max_adaptation'], 'Adaptation outside frozen range')
    raw1, raw2 = words(raw1, (9,)), words(raw2, (9,))
    require(np.array_equal(words(row['raw_theta1'], (9,)), raw1) and np.array_equal(words(row['raw_theta2'], (9,)), raw2), 'Raw parameter/trajectory binding')
    coefficients = {k: np.float32(c[k]) for k in ('dt', 'leak', 'k_equity', 'k_risk', 'tau', 'fraction', 'coupling_gain', 'conditioning_gain', 'z_rest1', 'z_rest2')}
    layer_rows = []
    for layer, coordinate in (('layer1', 0), ('layer2', 2)):
        block = row[layer]
        readout = array(block['Q_R_x'], (T+1, B, 3))
        boundary = array(block['boundary'], (T+1, B))
        asset = words(block['asset'], (T+1, B))
        require(np.all(boundary > 0.) and np.all(asset > 0.), 'Nonpositive asset or boundary')
        ulp_close(asset, np.exp(state[..., coordinate].astype(np.float64)).astype(np.float32), g, layer+' exp(z)')
        close(readout[..., 2], np.log(asset.astype(np.float64)/boundary), g, layer+' margin')
        default = asset.astype(np.float64) <= boundary
        require(np.all(readout[..., 0][default] == 0.) and np.all(readout[..., 1][default] == 1.), 'Wrong actual default-side values')
        require(np.min(readout[..., 0]) >= -g['range_tolerance'] and np.min(readout[..., 1]) >= -g['range_tolerance'] and np.max(readout[..., 1]) <= 1.+g['range_tolerance'], 'Q/R outside frozen range')
        phase = np.sign(asset.astype(np.float64)-boundary).astype(int)
        require(np.array_equal(np.asarray(block['phase']), phase), 'Raw boundary branch record mismatch')
        require(type(block['actual_default_count']) is int and block['actual_default_count'] == int(default.sum()), 'Default count mismatch')
        crossings = [{'step': t, 'sample': j, 'from': int(phase[t, j]), 'to': int(phase[t+1, j])}
                     for t in range(T) for j in range(B) if phase[t, j] != phase[t+1, j]]
        require(block['sampled_phase_changes'] == crossings, 'Sampled crossing count/identity mismatch')
        layer_rows.append((readout, boundary, asset))
    first, second = layer_rows
    require(np.max(np.abs(first[1]-first[1][0, 0])) <= g['constant_boundary_atol'], 'Layer-1 boundary not constant')
    require(np.max(np.ptp(second[1][:T], axis=0)) > g['minimum_boundary2_range'], 'Layer-2 used-step boundary did not move')
    all_links = first[0][..., 2].astype(np.float32)
    link = words(row['links'], (T, B))
    require(np.array_equal(link, all_links[:T]), 'Interlayer margin link is not the represented readout')
    used_drive2 = words(row['used_drive2'], (T, B))
    u1, u2 = words(data['drive1'], (T, B)), words(data['drive2'], (T, B))
    require(np.array_equal(used_drive2, u2+coefficients['coupling_gain']*link), 'Linear drive link mismatch')
    base1, base2 = words(data['base1'], (9,)), words(data['base2'], (9,))
    theta1 = words(row['layer1']['effective_theta'], (9,))
    theta2 = words(row['layer2']['effective_theta'], (T+1, B, 9))
    preactivation = raw2+coefficients['conditioning_gain']*all_links[..., None]
    tanh1 = np.tanh(raw1)
    tanh2 = np.tanh(preactivation)
    internal_names = {'theta1_tanh', 'theta2_preactivation', 'theta2_tanh'}
    if internal or any(name in row for name in internal_names):
        require(internal_names <= set(row), 'Incomplete internal tangent record')
        actual_tanh1 = words(row['theta1_tanh'], (9,))
        actual_tanh2 = words(row['theta2_tanh'], (T, B, 9))
        require(np.array_equal(words(row['theta2_preactivation'], (T, B, 9)), preactivation[:T]), 'Exact FP32 conditioning preactivation mismatch')
        ulp_close(actual_tanh1, tanh1, g, 'tanh(raw1)')
        ulp_close(actual_tanh2, tanh2[:T], g, 'conditioned tanh2')
        require(np.array_equal(theta1, base1*(np.float32(1.)+coefficients['fraction']*actual_tanh1)), 'Theta1/recorded tanh mismatch')
        require(np.array_equal(theta2[:T], base2*(np.float32(1.)+coefficients['fraction']*actual_tanh2)), 'Theta2/recorded tanh mismatch')
    ulp_close(theta1, base1*(np.float32(1.)+coefficients['fraction']*tanh1), g, 'theta1 nonlinear map')
    ulp_close(theta2, base2*(np.float32(1.)+coefficients['fraction']*tanh2), g, 'theta2 nonlinear map')
    require(np.max(np.abs(theta1.astype(np.float64)/base1-1.)) <= c['fraction']+2e-7 and np.max(np.abs(theta2.astype(np.float64)/base2-1.)) <= c['fraction']+2e-7, 'Parameter fraction bound')
    expected_drift = []
    for coordinate, readout, drive, rest in ((0, first[0], u1, coefficients['z_rest1']), (2, second[0], used_drive2, coefficients['z_rest2'])):
        z, adaptation = state[:T, :, coordinate], state[:T, :, coordinate+1]
        q, risk = readout[:T, :, 0].astype(np.float32), readout[:T, :, 1].astype(np.float32)
        dz = drive-coefficients['leak']*(z-rest)-coefficients['k_equity']*q-coefficients['k_risk']*risk+adaptation
        da = (coefficients['k_risk']*risk-adaptation)/coefficients['tau']
        expected_drift.extend((dz, da))
    drift = np.stack(expected_drift, axis=-1)
    require(np.array_equal(words(row['drift'], (T, B, 4)), drift), 'Exact FP32 drift mismatch')
    require(np.array_equal(state[1:], state[:-1]+coefficients['dt']*drift), 'Exact simultaneous FP32 Euler mismatch')
    return state.astype(np.float64)


def bind_financial(root, protocol, seals):
    root = Path(root)
    require(protocol['dependencies']['financial_protocol_sha256'] == FINANCIAL_PROTOCOL and protocol['dependencies']['financial_binary_sha256'] == FINANCIAL_BINARY, 'Wrong financial dependency contract')
    path = root/'RECOVERY_PROTOCOL_V1.json'
    seal(path, FINANCIAL_PROTOCOL, seals)
    original = read(path)
    require(original['binary_sha256'] == FINANCIAL_BINARY, 'Wrong sealed financial binary')
    files = dict(original['source_sha256'])
    files.update({'recovered.so': FINANCIAL_BINARY, 'RECOVERED_BUILD.json': original['build_receipt_sha256'], 'RECOVERY_CASES_V1.json': original['manifest_sha256']})
    for name, digest in files.items():
        seal(root/name, digest, seals)


def load_reference(root):
    spec = importlib.util.spec_from_file_location('_sealed_two_layer_chain_reference', root/'two_layer_reference.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forward_equal(left, right):
    fields = ('state', 'links', 'used_drive2', 'drift', 'raw_theta1', 'raw_theta2')
    require(all(np.array_equal(left[name], right[name]) for name in fields), 'Same-value intervention changed a forward field')
    for layer in ('layer1', 'layer2'):
        for name in ('Q_R_x', 'boundary', 'asset', 'effective_theta', 'phase'):
            require(np.array_equal(left[layer][name], right[layer][name]), 'Same-value intervention changed '+layer+'/'+name)


def check_modes(audit, data, protocol, reference):
    T, B, gates = protocol['cell']['steps'], protocol['experiment']['batch_size'], protocol['gates']
    modes = audit['modes']
    require(set(modes) == set(MODES), 'Missing or extra gradient mode')
    financial = audit['financial_reference']
    require(len(financial) == T and all(type(r['step']) is int for r in financial) and [r['step'] for r in financial] == list(range(T)), 'Financial reference step count/identity')
    for t, row in enumerate(financial):
        for layer in (1, 2):
            raw, jac = array(row['raw'+str(layer)], (B, 5)), array(row['jac'+str(layer)], (B, 5, 10))
            block = modes['full']['trajectory']['layer'+str(layer)]
            require(np.array_equal(raw[:, 0], array(block['boundary'][t], (B,))), 'Archived raw boundary/trajectory binding')
            require(np.count_nonzero(jac[:, 0, 9]) == 0, 'Financial boundary has forbidden asset derivative')
            close(array(block['Q_R_x'][t], (B, 3))[:, 0], raw[:, 1]/raw[:, 0], gates, 'Archived equity readout')
            close(array(block['Q_R_x'][t], (B, 3))[:, 1], 1.-(1.-raw[:, 2])**2, gates, 'Archived risk readout')
    results = {}
    for mode in MODES:
        record = modes[mode]
        require(record['passed'] is True, 'Mode writer rejected')
        flags(record['trace_checks'], TRACE_CHECKS, mode+' trajectory')
        trace = record['trajectory']
        state = check_trace(trace, data, protocol, np.zeros(9), np.zeros(9), mode, True)
        check_loss(record['loss'], state, data, gates)
        forward_equal(modes['full']['trajectory'], trace)
        require(record['loss'] == modes['full']['loss'], 'Same-value intervention changed loss')
        local = [reference.compose_local(raw1=row['raw1'], jac1=row['jac1'], asset1=trace['layer1']['asset'][t], raw2=row['raw2'], jac2=row['jac2'], asset2=trace['layer2']['asset'][t], base1=data['base1'], base2=data['base2'], tanh1=trace['theta1_tanh'], tanh2=trace['theta2_tanh'][t], config=protocol['cell'], mode=mode) for t, row in enumerate(financial)]
        stacked = {name: np.stack([row[name] for row in local]) for name in local[0]}
        terminal = np.zeros((B, 4))
        terminal[:, 2] = 2.*(state[-1, :, 2]-np.asarray(data['target_z2']))/B
        terminal[:, 3] = 2.*data['loss_a_weight']*(state[-1, :, 3]-np.asarray(data['target_a2']))/B
        reverse = reference.reverse_steps(stacked['A'], stacked['B'], terminal)
        expected_reference = {'A': stacked['A'], 'B': stacked['B'], **reverse}
        require(set(record['reference']) == set(expected_reference), 'Reference field count mismatch')
        for name, value in expected_reference.items():
            close(record['reference'][name], value, gates, mode+' reference '+name)
        actual_shapes = {'raw1': (9,), 'raw2': (9,), 'initial_state': (B, 4), 'drive1': (T, B), 'drive2': (T, B), 'theta1_nodes': (T, 9), 'theta2_nodes': (T, B, 9), 'step_raw_credit': (T, 18)}
        require(set(record['actual']) == set(actual_shapes), 'Actual gradient field count mismatch')
        actual = {name: words(record['actual'][name], shape).astype(np.float64) for name, shape in actual_shapes.items()}
        unused_names = {'raw1', 'raw2', 'initial_state', 'drive1', 'drive2'} | {'theta'+str(layer)+'_node_'+str(t) for layer in (1, 2) for t in range(T)}
        require(set(record['unused']) == unused_names and all(type(v) is bool for v in record['unused'].values()), 'Unused gradient record incomplete')
        for name, unused in record['unused'].items():
            if not unused:
                continue
            value = actual[name] if name in actual else actual[name.split('_node_')[0]+'_nodes'][int(name.split('_node_')[1])]
            require(np.count_nonzero(value) == 0, 'Unused gradient has nonzero materialized data')
        dt = float(np.float32(protocol['cell']['dt']))
        comparisons = {
            'shared_raw': (np.concatenate((actual['raw1'], actual['raw2'])), reverse['shared_raw']),
            'step_raw_credit': (actual['step_raw_credit'], reverse['step_raw']),
            'initial_state': (actual['initial_state'], reverse['state_adj'][0]),
            'drive1': (actual['drive1'], dt*reverse['state_adj'][1:, :, 0]),
            'drive2': (actual['drive2'], dt*reverse['state_adj'][1:, :, 2]),
            'raw1_equals_time_sum': (actual['raw1'], actual['step_raw_credit'][:, :9].sum(axis=0)),
            'raw2_equals_time_sum': (actual['raw2'], actual['step_raw_credit'][:, 9:].sum(axis=0)),
        }
        require(len(comparisons) == gates['required_temporal_comparisons'] and set(record['comparisons']) == set(comparisons), 'Temporal comparison count mismatch')
        for name, pair in comparisons.items():
            comparison(record['comparisons'][name], *pair, gates, mode+'/'+name)
        for t in range(T):
            k = (mode in ('full', 'drive_only'))*stacked['K_drive'][t]+(mode in ('full', 'conditioning_only'))*stacked['K_condition'][t]
            theta1_j = dt*np.concatenate((stacked['G1'][t], k[:, :, None]*stacked['margin_theta'][t][:, None, :]), axis=1)
            close(actual['theta1_nodes'][t], np.einsum('bi,bij->j', reverse['state_adj'][t+1], theta1_j), gates, mode+' theta1 node VJP')
            close(actual['theta2_nodes'][t], dt*np.einsum('bi,bij->bj', reverse['state_adj'][t+1, :, 2:], stacked['G2'][t]), gates, mode+' theta2 node VJP')
        results[mode] = {'actual': actual, 'local': stacked, 'reverse': reverse}
    return results


def check_identification(audit, results, protocol):
    gates = protocol['gates']
    full, drive, condition, detached = [results[name] for name in MODES]
    identity = audit['identification']
    require(identity['passed'] is True, 'Identification writer rejected')
    flags(identity['checks'], IDENTIFICATION_CHECKS, 'route identification')
    close(full['actual']['raw1'], drive['actual']['raw1']+condition['actual']['raw1'], gates, 'Upstream route additivity')
    for mode in (drive, condition, detached):
        close(mode['actual']['raw2'], full['actual']['raw2'], gates, 'Downstream VJP invariant across modes')
    require(np.linalg.norm(condition['actual']['raw1']) > gates['minimum_conditioning_vjp'], 'Dead conditioning route')
    require(np.linalg.norm(full['actual']['raw1']) > gates['nonzero_gradient_floor'], 'No full upstream VJP')
    require(np.count_nonzero(detached['actual']['raw1']) == 0 and np.count_nonzero(detached['actual']['initial_state'][:, :2]) == 0 and np.count_nonzero(detached['actual']['drive1']) == 0, 'Both-detached upstream influence remains')
    require(np.linalg.norm(full['actual']['initial_state'][:, :2]) > gates['nonzero_gradient_floor'] and np.linalg.norm(full['actual']['drive1'][0]) > gates['nonzero_gradient_floor'], 'Missing early layer-1 influence')
    require(set(audit['full_local_decomposition']) == set(full['local']), 'Local decomposition incomplete')
    for name, value in full['local'].items():
        close(audit['full_local_decomposition'][name], value, gates, 'Full local decomposition '+name)
    adjoint = full['reverse']['state_adj'][1:, :, 2:]
    direct_condition = np.einsum('tbi,tbij->tj', adjoint, full['local']['boundary_raw1_condition'])
    direct_drive = np.einsum('tbi,tbij->tj', adjoint, full['local']['boundary_raw1_drive'])
    require(np.linalg.norm(direct_condition) > gates['minimum_direct_boundary_vjp'], 'Dead direct boundary-conditioning block')
    for name, values in (('condition', direct_condition), ('drive', direct_drive)):
        close(identity['direct_boundary_'+name+'_step'], values, gates, 'Direct boundary '+name+' steps')
        close(identity['direct_boundary_'+name+'_total'], values.sum(axis=0), gates, 'Direct boundary '+name+' total')
    close(identity['conditioning_state_history_remainder'], condition['actual']['raw1']-direct_condition.sum(axis=0), gates, 'Conditioning state-history remainder')
    for name, record in (('conditioning', condition), ('drive', drive), ('full', full)):
        close(identity[name+'_vjp_l2'], np.linalg.norm(record['actual']['raw1']), gates, name+' VJP magnitude')
    checks = {
        'raw1_route_additivity': (full['actual']['raw1'], drive['actual']['raw1']+condition['actual']['raw1']),
        'raw2_drive_mode_same': (drive['actual']['raw2'], full['actual']['raw2']),
        'raw2_conditioning_mode_same': (condition['actual']['raw2'], full['actual']['raw2']),
        'raw2_both_detached_same': (detached['actual']['raw2'], full['actual']['raw2']),
    }
    require(set(identity['comparisons']) == set(checks), 'Identification comparison count mismatch')
    for name, pair in checks.items():
        comparison(identity['comparisons'][name], *pair, gates, name)
    return {'conditioning_vjp_l2': float(np.linalg.norm(condition['actual']['raw1'])), 'direct_boundary_condition_step_l2': float(np.linalg.norm(direct_condition))}


def check_training(training, audit, data, protocol, results):
    g, updates = protocol['gates'], protocol['experiment']['updates']
    require(training['data'] == data, 'Training inputs/targets changed')
    require(set(training['parameters']) == {'raw_theta1', 'raw_theta2'}, 'Wrong trainable parameter groups')
    history = training['history']
    require(len(history) == updates and all(type(r['iteration']) is int for r in history) and [r['iteration'] for r in history] == list(range(updates)), 'Incomplete optimizer history')
    previous = [np.zeros(9), np.zeros(9)]
    for key in training['parameters']:
        require(np.array_equal(words(training['parameters'][key]['initial'], (9,)), np.zeros(9)), 'Nonzero initial raw parameters')
    for iteration, row in enumerate(history):
        before = [words(row['raw'+str(layer)+'_before'], (9,)) for layer in (1, 2)]
        require(all(np.array_equal(left, right) for left, right in zip(before, previous)), 'Raw parameter update chain broken')
        gradient = [words(row['grad_raw'+str(layer)], (9,)) for layer in (1, 2)]
        state = check_trace(row['trajectory'], data, protocol, *before, 'full', False)
        check_loss(row['loss_before_update'], state, data, g)
        flags(row['trace_checks'], TRACE_CHECKS, 'training trajectory')
        if iteration == 0:
            forward_equal(audit['modes']['full']['trajectory'], row['trajectory'])
            for layer in (1, 2):
                close(gradient[layer-1], results['full']['actual']['raw'+str(layer)], g, 'Initial audit/training gradient binding')
        previous = [words(row['raw'+str(layer)+'_after'], (9,)) for layer in (1, 2)]
    for layer in (1, 2):
        key = 'raw_theta'+str(layer)
        final = words(training['parameters'][key]['final'], (9,))
        require(np.array_equal(final, previous[layer-1]) and np.linalg.norm(final.astype(np.float64)) > g['nonzero_gradient_floor'], 'Parameter group did not update or final chain mismatch')
        close(training['parameter_update_l2'][key], np.linalg.norm(final.astype(np.float64)), g, 'Parameter update magnitude')
    final_state = check_trace(training['final_trajectory'], data, protocol, *previous, 'full', False)
    check_loss(training['final_loss'], final_state, data, g)
    require(training['initial_loss'] == history[0]['loss_before_update'], 'Initial loss binding mismatch')
    flags(training['checks'], TRAINING_CHECKS, 'training')


def run(root, expected, audit_path, training_path, financial_root, output):
    root = Path(root)
    seals = {}
    seal(root/'TWO_LAYER_PROTOCOL.json', expected, seals)
    protocol = read(root/'TWO_LAYER_PROTOCOL.json')
    seal(root/'TWO_LAYER_INPUTS.json', protocol['inputs_sha256'], seals)
    require({'two_layer_model.py', 'two_layer_common.py', 'two_layer_reference.py', 'audit_two_layer.py', 'train_two_layer.py', 'check_two_layer_results.py'} <= set(protocol['source_sha256']), 'Required runnable source is not sealed')
    for name, digest in protocol['source_sha256'].items():
        seal(root/name, digest, seals)
    seal(__file__, protocol['source_sha256']['check_two_layer_results.py'], seals)
    seal(audit_path, None, seals); seal(training_path, None, seals)
    bind_financial(financial_root, protocol, seals)
    data, audit, training = read(root/'TWO_LAYER_INPUTS.json'), read(audit_path), read(training_path)
    require(protocol['cell']['steps'] == 16 and protocol['experiment']['batch_size'] == 8 and protocol['experiment']['updates'] == 12, 'Wrong frozen experiment dimensions')
    require(audit['schema'] == 'hcsn.hx-two-layer-audit.v1' and training['schema'] == 'hcsn.hx-two-layer-training.v1', 'Wrong result schema')
    require(audit['protocol_sha256'] == expected == training['protocol_sha256'], 'Result/protocol identity mismatch')
    require(audit['audit_passed'] is True and training['training_passed'] is True, 'Writer reported failure')
    T, B, gates = protocol['cell']['steps'], protocol['experiment']['batch_size'], protocol['gates']
    for name, shape in {'base1': (9,), 'base2': (9,), 'initial_state': (B, 4), 'drive1': (T, B), 'drive2': (T, B), 'target_z2': (B,), 'target_a2': (B,), 'readout_fixture_z': (5,)}.items():
        words(data[name], shape)
    wrapper = audit['readout_equivalence']
    require(wrapper['passed'] is True, 'Readout-equivalence writer rejected')
    shapes = {'values': (5, 3), 'theta_vjp': (5, 9), 'z_vjp': (5,)}
    require(set(wrapper['comparisons']) == set(shapes), 'Readout comparison count mismatch')
    for name, shape in shapes.items():
        row = wrapper['comparisons'][name]
        comparison(row, array(row['observed'], shape), array(row['reference'], shape), gates, 'Readout '+name)
    contracts = wrapper['contracts']
    require(len(contracts) == gates['required_readout_contracts'] == len(CONTRACTS) and {r['name'] for r in contracts} == set(CONTRACTS), 'Contract check identity/count mismatch')
    require(all(r['passed'] is True and r['exception_type'] == CONTRACTS[r['name']] for r in contracts), 'Contract rejection missing or wrong exception class')
    reference = load_reference(root)
    results = check_modes(audit, data, protocol, reference)
    magnitudes = check_identification(audit, results, protocol)
    check_training(training, audit, data, protocol, results)
    for path, digest in seals.items():
        require(sha(path) == digest, 'Bound file changed during check: '+path)
    receipt = {
        'schema': 'hcsn.hx-two-layer-independent-result-check.v1', 'passed': True,
        'protocol_sha256': expected, 'checker_sha256': sha(__file__), 'bound_artifact_sha256': seals,
        'counts': {'modes': len(MODES), 'steps': T, 'batch': B, 'state_columns': 4, 'trainable_parameters': 18, 'optimizer_updates': len(training['history']), 'readout_contracts': len(contracts), 'temporal_comparisons_per_mode': gates['required_temporal_comparisons']},
        'identification_magnitudes': magnitudes, 'financial_kernel_calls': 0, 'pytorch_calls': 0,
        'scope': 'Independent NumPy record, represented Euler, four audit modes with archived local-Jacobian chain and route-identification consistency. Training checks every parameter-update link and finite gradient, with only the first gradient tied to the independent audit chain. No optimizer replay, new financial point, independent financial oracle, quality or stability claim.',
    }
    with Path(output).open('x') as target:
        target.write(json.dumps(receipt, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': True, 'counts': receipt['counts'], 'output': str(output), 'sha256': sha(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--protocol-sha256', required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--financial-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.root, arguments.protocol_sha256, arguments.audit, arguments.training, arguments.financial_root, arguments.output)
