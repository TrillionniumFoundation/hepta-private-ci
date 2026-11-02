"""Recompute descriptive results from sealed records; no new model execution."""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

PROTOCOL = 'da07c580e258f51517f124d6d7b902a8ae3c6700fb58cb96948c18447c740ad7'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.name.endswith('.gz') else raw)


def trace_summary(trace, steps):
    result = {}
    for layer in ('layer1', 'layer2'):
        row = trace[layer]; boundary = np.asarray(row['boundary']); obs = np.asarray(row['Q_R_x'])
        result[layer] = {'actual_default_count': row['actual_default_count'], 'logged_state_count': int(boundary.size),
                         'default_percent': 100.*row['actual_default_count']/boundary.size,
                         'sampled_phase_changes': len(row['sampled_phase_changes']),
                         'boundary_min_all_logged_states': float(boundary.min()), 'boundary_max_all_logged_states': float(boundary.max()),
                         'used_step_boundary_range_by_sample': np.ptp(boundary[:steps], axis=0).tolist(),
                         'Q_range': [float(obs[..., 0].min()), float(obs[..., 0].max())],
                         'R_range': [float(obs[..., 1].min()), float(obs[..., 1].max())]}
    return result


def main(root, output):
    if sha(root/'TWO_LAYER_PROTOCOL.json') != PROTOCOL: raise ValueError('Wrong scientific protocol')
    protocol = read(root/'TWO_LAYER_PROTOCOL.json')
    for name, digest in protocol['source_sha256'].items():
        if sha(root/name) != digest: raise ValueError('Frozen source changed '+name)
    if sha(root/'TWO_LAYER_INPUTS.json') != protocol['inputs_sha256']: raise ValueError('Frozen inputs changed')
    audit_path, training_path = root/'TWO_LAYER_AUDIT_V1.json.gz', root/'TWO_LAYER_TRAINING_V1.json.gz'
    audit, training, check = read(audit_path), read(training_path), read(root/'TWO_LAYER_RESULT_CHECK_V1.json')
    if not (audit['audit_passed'] and training['training_passed'] and check['passed']): raise ValueError('Cannot summarize a failed run as passed')
    executions = {kind: read(root/('TWO_LAYER_'+kind+'_EXECUTION_V1.json')) for kind in ('AUDIT', 'TRAINING', 'CHECK')}
    if any(row['actual_returncode'] != 0 for row in executions.values()): raise ValueError('Execution failed')
    modes = {}
    for mode, row in audit['modes'].items():
        actual = row['actual']
        modes[mode] = {'raw1_gradient': actual['raw1'], 'raw2_gradient': actual['raw2'],
                       'raw1_gradient_l2': float(np.linalg.norm(actual['raw1'])), 'raw2_gradient_l2': float(np.linalg.norm(actual['raw2'])),
                       'layer1_initial_state_vjp_l2': float(np.linalg.norm(np.asarray(actual['initial_state'])[:, :2])),
                       'first_external_drive1_vjp_l2': float(np.linalg.norm(np.asarray(actual['drive1'])[0])),
                       'earliest_theta1_node_vjp_l2': float(np.linalg.norm(np.asarray(actual['theta1_nodes'])[0])),
                       'max_absolute_chain_comparison_error': max(v['max_absolute_error'] for v in row['comparisons'].values()),
                       'max_chain_error_over_frozen_allowance': max(v['max_error_over_allowance'] for v in row['comparisons'].values())}
    identity = audit['identification']; direct = {}
    for name in ('direct_boundary_condition_step', 'direct_boundary_condition_total', 'direct_boundary_drive_step', 'direct_boundary_drive_total', 'conditioning_state_history_remainder'):
        direct[name] = identity[name]; direct[name+'_l2'] = float(np.linalg.norm(identity[name]))
    initial, final = training['initial_loss'], training['final_loss']
    checkpoint_time = datetime.fromisoformat(executions['AUDIT']['checkpoint_commit_utc'].replace('Z', '+00:00'))
    launch_time = datetime.fromisoformat(executions['AUDIT']['controller_started_at_utc'])
    result = {'schema': 'hcsn.hx-two-layer-descriptive-summary.v1', 'protocol_sha256': PROTOCOL,
              'source_sha256': protocol['source_sha256'], 'input_sha256': protocol['inputs_sha256'],
              'evidence_sha256': {p.name: sha(p) for p in (audit_path, training_path, root/'TWO_LAYER_RESULT_CHECK_V1.json')},
              'remote_checkpoint_commit': executions['AUDIT']['checkpoint_commit'],
              'checkpoint_commit_before_first_launch': checkpoint_time < launch_time,
              'first_controller_launch_utc': executions['AUDIT']['controller_started_at_utc'],
              'first_financial_evaluation_utc': audit['runtime']['evaluation_started_at_utc'],
              'four_mode_gradients': modes, 'boundary_path_decomposition': direct,
              'conditioning_to_full_upstream_gradient_norm_ratio': modes['conditioning_only']['raw1_gradient_l2']/modes['full']['raw1_gradient_l2'],
              'ratio_interpretation': 'Vector norm ratio only; not a causal fraction of training benefit.',
              'training': {'initial_loss': initial, 'final_loss': final, 'relative_loss_decrease_percent': 100.*(initial-final)/initial,
                           'loss_before_each_update': [row['loss_before_update'] for row in training['history']],
                           'parameters': training['parameters'], 'parameter_update_l2': training['parameter_update_l2'],
                           'initial_trajectory': trace_summary(training['history'][0]['trajectory'], protocol['cell']['steps']),
                           'final_trajectory': trace_summary(training['final_trajectory'], protocol['cell']['steps'])},
              'runtime': {'audit': audit['runtime'], 'training': training['runtime'],
                          'controller_wall_seconds': {key: row['wall_seconds_including_process_startup'] for key, row in executions.items()},
                          'audit_counter_note': '1359 attempted financial states includes the deliberate five-row invalid-maturity contract batch; it is not a count of successful financial rows.'},
              'checker_counts': check['counts'],
              'limits': ['Same deterministic eight synthetic sequences only; no validation or generalization set.',
                         'The ordinary drive route has a much larger upstream gradient norm in this fixture.',
                         'Layer-2 default saturation remains and increases in logged-state count after training.',
                         'No analytic time-varying financial PDE or temporal flow, stability or autonomous spike claim.',
                         'Four audit graphs have independently composed local Jacobian chains; the other eleven training gradients are finite records, not independently replayed gradients.',
                         'Checker uses archived financial values/Jacobians from the frozen kernel, not an independent financial oracle; Adam is not replayed.',
                         'Runtime is a local CPU observation, not a comparative speed, GPU or energy benchmark.']}
    with output.open('x') as target: target.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'summary': str(output), 'sha256': sha(output), 'relative_loss_decrease_percent': result['training']['relative_loss_decrease_percent'], 'modes': len(modes)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); main(args.root, args.output)
