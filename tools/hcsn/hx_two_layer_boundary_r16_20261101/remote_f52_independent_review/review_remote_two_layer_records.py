"""Recompose actual remote two-layer records; only provenance/path handling is adapted."""
import argparse
import datetime
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


EXPECTED_PROTOCOL = 'da07c580e258f51517f124d6d7b902a8ae3c6700fb58cb96948c18447c740ad7'
EXPECTED_REFERENCE = '35e8680e3faa501dcde7913a19b2998d2d799a1feb27667fbad6d55812c8ca69'
MODES = ('full', 'drive_only', 'conditioning_only', 'both_detached')


def identity(path):
    blob = Path(path).read_bytes()
    return {'local_path': str(path), 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}


def read(path):
    blob = Path(path).read_bytes()
    return json.loads(gzip.decompress(blob) if str(path).endswith('.gz') else blob)


def array(value):
    value = np.asarray(value, dtype=np.float64)
    assert np.isfinite(value).all()
    return value



EXPECTED_HEAD = 'f52dc359344cd0eb9b5dba84d4af3d5815aeb629'
EXPECTED_ARCHIVE = '7e45f10d267648e88db09a8b5d2b40dcfd606b2f065c894691695c18993897c3'


def remote_artifact_binding(root, artifact_root, financial_root, protocol, source):
    """Verify actual remote identities without treating earlier local runs as remote evidence."""
    import zipfile
    artifact_root, financial_root = Path(artifact_root), Path(financial_root)
    extracted = artifact_root/'extracted'
    archive, download = artifact_root/'REMOTE_ARTIFACT.zip', read(artifact_root/'DOWNLOAD_IDENTITY.json')
    assert identity(archive)['sha256'] == EXPECTED_ARCHIVE
    assert identity(archive)['bytes'] == download['bytes'] == 1551454
    assert download['sha256'] == EXPECTED_ARCHIVE and download['source_head'] == EXPECTED_HEAD
    assert download['artifact_id'] == 13107591722 and download['github_digest_matched'] is True
    expected_members = {item['path']: item for item in download['members']}
    assert len(expected_members) == len(download['members']) == 14
    member_identities = []
    with zipfile.ZipFile(archive) as zipped:
        assert len(zipped.namelist()) == len(set(zipped.namelist())) == 14
        assert set(zipped.namelist()) == set(expected_members)
        for name in zipped.namelist():
            assert Path(name).name == name and not name.startswith('.')
            blob = zipped.read(name)
            expected = expected_members[name]
            assert len(blob) == expected['bytes']
            assert hashlib.sha256(blob).hexdigest() == expected['sha256']
            assert (extracted/name).read_bytes() == blob
            member_identities.append(identity(extracted/name))
    bindings, check = read(extracted/'source-bindings.json'), read(extracted/'two-layer-check.json')
    assert bindings['head'] == EXPECTED_HEAD
    prefix = 'tools/hcsn/hx_two_layer_boundary_r16_20261101/'
    assert bindings['sha256'][prefix+'TWO_LAYER_PROTOCOL.json'] == EXPECTED_PROTOCOL
    assert bindings['sha256'][prefix+'check_two_layer_results.py'] == protocol['source_sha256']['check_two_layer_results.py']
    assert check['passed'] is True and check['protocol_sha256'] == EXPECTED_PROTOCOL
    assert check['checker_sha256'] == protocol['source_sha256']['check_two_layer_results.py']
    assert check['counts'] == {'modes':4, 'steps':16, 'batch':8, 'state_columns':4, 'trainable_parameters':18, 'optimizer_updates':12, 'readout_contracts':12, 'temporal_comparisons_per_mode':7}
    assert check['financial_kernel_calls'] == check['pytorch_calls'] == 0
    repo = '/home/runner/work/hepta-private-ci/hepta-private-ci/'
    result_prefix = '/home/runner/work/_temp/hcsn-financial-autograd-r16-results/'
    financial_prefix = 'tools/hcsn/compiled_fp32_r16_20261101/recovery/'
    bound = check['bound_artifact_sha256']
    expected_paths = {repo+prefix+n: digest for n, digest in source.items()}
    recovery = read(financial_root/'RECOVERY_PROTOCOL_V1.json')
    assert identity(financial_root/'RECOVERY_PROTOCOL_V1.json')['sha256'] == protocol['dependencies']['financial_protocol_sha256']
    finance_sources = dict(recovery['source_sha256'])
    finance_sources.update({'RECOVERY_PROTOCOL_V1.json': protocol['dependencies']['financial_protocol_sha256'], 'recovered.so': protocol['dependencies']['financial_binary_sha256'], 'RECOVERED_BUILD.json':recovery['build_receipt_sha256'], 'RECOVERY_CASES_V1.json':recovery['manifest_sha256']})
    expected_paths.update({repo+financial_prefix+n: digest for n,digest in finance_sources.items()})
    expected_paths.update({result_prefix+n:identity(extracted/n)['sha256'] for n in ('two-layer-audit.json.gz','two-layer-training.json.gz')})
    assert bound == expected_paths
    for name,digest in finance_sources.items():
        assert identity(financial_root/name)['sha256'] == digest
    for source_name,artifact_name in [('TWO_LAYER_AUDIT_V1.json.gz','two-layer-audit.json.gz'),('TWO_LAYER_TRAINING_V1.json.gz','two-layer-training.json.gz'),('TWO_LAYER_RESULT_CHECK_V1.json','two-layer-check.json')]:
        assert identity(root/source_name)['sha256'] == identity(extracted/artifact_name)['sha256']
    return {'artifact':identity(archive),'download_identity':identity(artifact_root/'DOWNLOAD_IDENTITY.json'),
            'artifact_id':download['artifact_id'], 'source_head':bindings['head'], 'source_bindings':identity(extracted/'source-bindings.json'),
            'all_archive_members_verified':member_identities, 'remote_checker':identity(extracted/'two-layer-check.json'),
            'remote_checker_source_input_financial_and_raw_bindings_verified':len(bound),
            'parent_reported_run_id':41366558836, 'parent_reported_job_id':125027835819,
            'provenance_limit':'Archive bytes and its declared head, frozen sources and raw results were independently bound here. The GitHub API digest/success status and head/merge tree equivalence were verified by the parent, not queried anew by this reviewer. No local execution receipt has been substituted for a remote run.'}


def run(root, reference_path, output, artifact_root, financial_root):
    root, reference_path = Path(root), Path(reference_path)
    assert identity(root/'TWO_LAYER_PROTOCOL.json')['sha256'] == EXPECTED_PROTOCOL
    assert identity(reference_path)['sha256'] == EXPECTED_REFERENCE
    p, data = read(root/'TWO_LAYER_PROTOCOL.json'), read(root/'TWO_LAYER_INPUTS.json')
    source = dict(p['source_sha256'], **{'TWO_LAYER_PROTOCOL.json': EXPECTED_PROTOCOL,
                                     'TWO_LAYER_INPUTS.json': p['inputs_sha256']})
    for name, digest in source.items():
        assert identity(root/name)['sha256'] == digest
    audit, training = read(root/'TWO_LAYER_AUDIT_V1.json.gz'), read(root/'TWO_LAYER_TRAINING_V1.json.gz')
    assert audit['protocol_sha256'] == training['protocol_sha256'] == EXPECTED_PROTOCOL
    assert audit['audit_passed'] is True and training['training_passed'] is True
    spec = importlib.util.spec_from_file_location('sealed_independent_chain', reference_path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    assert set(audit['modes']) == set(MODES)
    T, B = p['cell']['steps'], p['experiment']['batch_size']
    assert (T, B, p['experiment']['updates']) == (16, 8, 12)
    comparisons = {}

    def compare(name, observed, expected):
        observed, expected = array(observed), array(expected)
        assert observed.shape == expected.shape, name
        error = np.abs(observed-expected)
        allowance = p['gates']['gradient_atol'] + p['gates']['gradient_rtol']*np.abs(expected)
        assert np.all(error <= allowance), name
        comparisons[name] = {'max_absolute_error': float(error.max()),
                             'max_error_over_frozen_allowance': float((error/allowance).max())}

    full_trace = audit['modes']['full']['trajectory']
    assert len(audit['financial_reference']) == T
    locals_by_mode, reverse_by_mode, route_summary = {}, {}, {}
    for mode in MODES:
        row = audit['modes'][mode]
        trace, actual = row['trajectory'], row['actual']
        assert len(row['comparisons']) == 7 and row['passed'] is True
        assert all(v['passed'] is True for v in row['comparisons'].values())
        for name in ('state', 'links', 'used_drive2', 'drift'):
            assert np.array_equal(trace[name], full_trace[name]), (mode, name)
        for layer in ('layer1', 'layer2'):
            for name in ('Q_R_x', 'boundary', 'asset', 'effective_theta', 'phase'):
                assert np.array_equal(trace[layer][name], full_trace[layer][name]), (mode, layer, name)
        local = []
        for t, raw in enumerate(audit['financial_reference']):
            assert raw['step'] == t
            for n in ('1', '2'):
                values, jac = array(raw['raw'+n]), array(raw['jac'+n])
                assert np.array_equal(values[:, 0], trace['layer'+n]['boundary'][t])
                default = array(trace['layer'+n]['asset'][t]) <= values[:, 0]
                assert np.all(values[default, 1:4] == [0., 1., 1.])
                assert np.count_nonzero(jac[default, 1:4, :]) == 0
                assert np.count_nonzero(jac[:, 0, 9]) == 0
            local.append(reference.compose_local(
                raw1=raw['raw1'], jac1=raw['jac1'], asset1=trace['layer1']['asset'][t],
                raw2=raw['raw2'], jac2=raw['jac2'], asset2=trace['layer2']['asset'][t],
                base1=data['base1'], base2=data['base2'], tanh1=trace['theta1_tanh'],
                tanh2=trace['theta2_tanh'][t], config=p['cell'], mode=mode))
        stacked = {key: np.stack([item[key] for item in local]) for key in local[0]}
        state = array(trace['state']); terminal = np.zeros((B, 4))
        terminal[:, 2] = 2.*(state[-1, :, 2]-array(data['target_z2']))/B
        terminal[:, 3] = 2.*data['loss_a_weight']*(state[-1, :, 3]-array(data['target_a2']))/B
        reverse = reference.reverse_steps(stacked['A'], stacked['B'], terminal)
        for name in ('A', 'B'):
            compare(mode+'/stored_'+name, row['reference'][name], stacked[name])
        for name in reverse:
            compare(mode+'/stored_'+name, row['reference'][name], reverse[name])
        compare(mode+'/actual_raw', np.r_[actual['raw1'], actual['raw2']], reverse['shared_raw'])
        compare(mode+'/actual_step_credit', actual['step_raw_credit'], reverse['step_raw'])
        compare(mode+'/initial_state', actual['initial_state'], reverse['state_adj'][0])
        dt = float(np.float32(p['cell']['dt']))
        compare(mode+'/drive1', actual['drive1'], dt*reverse['state_adj'][1:, :, 0])
        compare(mode+'/drive2', actual['drive2'], dt*reverse['state_adj'][1:, :, 2])
        compare(mode+'/raw1_credit_sum', actual['raw1'], array(actual['step_raw_credit'])[:, :9].sum(axis=0))
        compare(mode+'/raw2_credit_sum', actual['raw2'], array(actual['step_raw_credit'])[:, 9:].sum(axis=0))
        locals_by_mode[mode], reverse_by_mode[mode] = stacked, reverse
        route_summary[mode] = {name+'_l2': float(np.linalg.norm(array(actual[name]))) for name in ('raw1', 'raw2')}
    gradients = {m: array(audit['modes'][m]['actual']['raw1']) for m in MODES}
    compare('upstream_route_additivity', gradients['full'], gradients['drive_only']+gradients['conditioning_only'])
    for mode in MODES[1:]:
        assert np.array_equal(audit['modes'][mode]['actual']['raw2'], audit['modes']['full']['actual']['raw2'])
    detached = audit['modes']['both_detached']['actual']
    assert all(np.count_nonzero(x) == 0 for x in (gradients['both_detached'], array(detached['initial_state'])[:, :2], array(detached['drive1'])))
    assert np.linalg.norm(gradients['conditioning_only']) > p['gates']['minimum_conditioning_vjp']
    adj = reverse_by_mode['full']['state_adj'][1:, :, 2:]
    direct = {}
    for route, field in [('conditioning', 'condition'), ('drive', 'drive')]:
        step = np.einsum('tbi,tbij->tj', adj, locals_by_mode['full']['boundary_raw1_'+field])
        compare('direct_boundary_'+route+'_step', audit['identification']['direct_boundary_'+field+'_step'], step)
        compare('direct_boundary_'+route+'_sum', audit['identification']['direct_boundary_'+field+'_total'], step.sum(axis=0))
        direct[route] = {'time_resolved_l2': float(np.linalg.norm(step)), 'net_time_sum_l2': float(np.linalg.norm(step.sum(axis=0)))}
        if route == 'conditioning':
            assert np.linalg.norm(step) > p['gates']['minimum_direct_boundary_vjp']
            remainder = gradients['conditioning_only']-step.sum(axis=0)
            compare('conditioning_state_history_remainder', audit['identification']['conditioning_state_history_remainder'], remainder)
            direct[route]['state_history_remainder_l2'] = float(np.linalg.norm(remainder))
    assert len(audit['readout_equivalence']['contracts']) == 12
    assert len(audit['identification']['checks']) == 12 and all(audit['identification']['checks'].values())

    def trajectory_summary(trace):
        state = array(trace['state']); assert state.shape == (17, 8, 4)
        assert np.array_equal(state[0], data['initial_state'])
        result = {'z_min': float(state[..., [0, 2]].min()), 'z_max': float(state[..., [0, 2]].max())}
        for layer in ('layer1', 'layer2'):
            block = trace[layer]; v, b = array(block['asset']), array(block['boundary'])
            obs = array(block['Q_R_x']); default = v <= b
            phase = np.sign(v-b).astype(int)
            assert np.array_equal(phase, block['phase'])
            assert int(default.sum()) == block['actual_default_count']
            assert np.all(obs[..., 0][default] == 0.) and np.all(obs[..., 1][default] == 1.)
            changes = [{'step': t, 'sample': j, 'from': int(phase[t, j]), 'to': int(phase[t+1, j])}
                       for t in range(T) for j in range(B) if phase[t, j] != phase[t+1, j]]
            assert changes == block['sampled_phase_changes']
            result[layer] = {'default_states': int(default.sum()), 'recorded_states': int(default.size),
                             'sampled_phase_changes': len(changes), 'positive_to_nonpositive': sum(r['from'] > 0 and r['to'] <= 0 for r in changes),
                             'nonpositive_to_positive': sum(r['from'] <= 0 and r['to'] > 0 for r in changes),
                             'used_boundary_min': float(b[:T].min()), 'used_boundary_max': float(b[:T].max()),
                             'used_time_boundary_range_per_sample': np.ptp(b[:T], axis=0).tolist()}
        return result

    assert len(training['history']) == 12 and training['data'] == data
    histories = []
    for i, item in enumerate(training['history']):
        assert item['iteration'] == i
        for n in ('1', '2'):
            previous = training['parameters']['raw_theta'+n]['initial'] if i == 0 else training['history'][i-1]['raw'+n+'_after']
            assert np.array_equal(item['raw'+n+'_before'], previous)
            assert np.array_equal(item['raw'+n+'_before'], item['trajectory']['raw_theta'+n])
            assert array(item['grad_raw'+n]).shape == (9,)
            assert array(item['raw'+n+'_after']).shape == (9,)
        histories.append(trajectory_summary(item['trajectory']))
    final_summary = trajectory_summary(training['final_trajectory'])
    changed = {}
    for n in ('1', '2'):
        params = training['parameters']['raw_theta'+n]
        assert np.array_equal(params['final'], training['history'][-1]['raw'+n+'_after'])
        assert np.array_equal(params['final'], training['final_trajectory']['raw_theta'+n])
        delta = array(params['final'])-array(params['initial'])
        changed['raw_theta'+n] = {'changed_coordinates': int(np.count_nonzero(delta)), 'l2': float(np.linalg.norm(delta))}
        assert changed['raw_theta'+n]['changed_coordinates'] == 9
        compare('initial_training_gradient_'+n, training['history'][0]['grad_raw'+n], audit['modes']['full']['actual']['raw'+n])
    for i, trace in enumerate([h['trajectory'] for h in training['history']]+[training['final_trajectory']]):
        state = array(trace['state'])[-1]
        loss = np.mean((state[:, 2]-array(data['target_z2']))**2) + data['loss_a_weight']*np.mean((state[:, 3]-array(data['target_a2']))**2)
        observed = training['history'][i]['loss_before_update'] if i < 12 else training['final_loss']
        compare('terminal_loss_'+str(i), observed, loss)
    executions = remote_artifact_binding(root, artifact_root, financial_root, p, source)
    receipt = {'schema': 'hcsn.two-layer-remote-result-independent-review.v1', 'passed': True,
               'reviewed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'protocol_sha256': EXPECTED_PROTOCOL,
               'review_source': identity(__file__), 'reference': identity(reference_path), 'remote_artifact_evidence': executions,
               'comparison_count': len(comparisons), 'comparisons': comparisons,
               'maximum_absolute_gradient_error': max(v['max_absolute_error'] for k, v in comparisons.items() if 'terminal_loss' not in k),
               'route_gradient_norms': route_summary, 'direct_boundary_credit': direct,
               'conditioning_to_drive_gradient_norm_ratio': float(np.linalg.norm(gradients['conditioning_only'])/np.linalg.norm(gradients['drive_only'])),
               'initial_trajectory': trajectory_summary(full_trace), 'final_trajectory': final_summary,
               'all_twelve_training_trajectory_summaries': histories, 'parameter_updates': changed,
               'loss': {'initial': training['initial_loss'], 'final': training['final_loss'], 'relative_reduction': (training['initial_loss']-training['final_loss'])/training['initial_loss']},
               'financial_kernel_calls': 0, 'pytorch_calls': 0, 'new_candidate_rollouts': 0,
               'scope': 'Archived source/identity checks and NumPy reassembly of four-mode full local/temporal chains, direct boundary credit, branch counts, parameter update continuity and terminal losses. No new financial points, no Torch run, no optimizer replay, and no independent recomputation of later eleven training gradients.',
               'interpretation_limits': ['Derivative route identity is demonstrated on the fixed functional traces, not a causal task-quality advantage.',
                   'The direct boundary gate concerns the time-resolved norm; its net sum and remaining state-history term are reported separately.',
                   'The recorded relative loss reduction is a twelve-update deterministic functional observation with no matched baseline or held-out assessment.',
                   'Boundary phase changes are sampled input-driven transitions, not precise events or demonstrated autonomous spikes.',
                   'The dynamic boundary belongs to repeated static H-X operator evaluations, not a solved time-dependent financial PDE.',
                   'Default-side Q/R saturation is retained and reported. Finite traces do not prove global or step-size stability.']}
    for name, digest in source.items():
        assert identity(root/name)['sha256'] == digest
    with Path(output).open('x') as handle:
        json.dump(receipt, handle, indent=2, allow_nan=False); handle.write('\n')
    print(json.dumps({k: receipt[k] for k in ('passed','comparison_count','maximum_absolute_gradient_error','route_gradient_norms','direct_boundary_credit','conditioning_to_drive_gradient_norm_ratio','parameter_updates','loss')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--artifact-root', required=True)
    parser.add_argument('--financial-root', required=True)
    args = parser.parse_args()
    run(args.root, args.reference, args.output, args.artifact_root, args.financial_root)
