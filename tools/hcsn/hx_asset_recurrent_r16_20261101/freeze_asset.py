"""Freeze fixed physical states and the new asset recurrent model before use."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
PREFIX = 'tools/hcsn/hx_asset_recurrent_r16_20261101'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (ROOT/name).open('x') as f:
        f.write(json.dumps(value, indent=2, allow_nan=False)+'\n')


def f32(value):
    return np.asarray(value, dtype=np.float32).tolist()


def main(adapter_root, financial_root):
    adapter_root, financial_root = Path(adapter_root), Path(financial_root)
    adapter_sha = '9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72'
    financial_sha = '76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0'
    if sha(adapter_root/'ADAPTER_PROTOCOL.json') != adapter_sha or sha(financial_root/'RECOVERY_PROTOCOL_V1.json') != financial_sha:
        raise ValueError('Wrong frozen financial/adapter dependencies')
    base = json.loads((adapter_root/'ADAPTER_FIXTURES.json').read_text())['cases'][0]['packed'][:9]
    T, B = 16, 8
    phase = 2.*np.pi*np.arange(B)/B
    z_rest = float(np.float32(np.log(67.)))
    old_known_b = 67.44151430180042
    data = {'schema': 'hcsn.hx-fixed-potential-inputs.v1', 'base_theta': f32(base),
            'nominal_rest_asset': 67., 'fixed_z_rest': z_rest,
            'fixed_z_fixtures': f32([np.log(50.), np.log(67.), np.log(old_known_b)-1e-4, np.log(old_known_b)+1e-4, np.log(100.)]),
            'training': {'initial_z': f32(z_rest+np.array([-.02, -.01, 0., .01, .02, -.02, 0., .02])),
                         'initial_adaptation': f32(np.zeros(B)),
                         'drive': f32(.12*np.sin(2.*np.pi*(np.arange(T)[:, None]+.5)/T+phase[None, :])),
                         'target_z': f32(z_rest+.012*np.cos(phase+.2)),
                         'target_adaptation': f32(.025+.005*np.sin(phase)), 'adaptation_loss_weight': .25},
            'all_negative_control': {'initial_z': f32([np.log(50.)]), 'initial_adaptation': f32([0.]),
                                     'drive': f32(np.full((T, 1), -.08))},
            'generation': {'deterministic': True, 'random_seed': None,
                           'known_baseline_b_from_opened_margin_V1': old_known_b,
                           'z_rest': 'float32(log(67)); fixed once, never recomputed from theta or b',
                           'z0': 'float32(z_rest + fixed offsets); new fixed physical family, not rescaled using learned b',
                           'drive': 'float32(0.12*sin(2*pi*(t+0.5)/16 + 2*pi*j/8))',
                           'target_z': 'float32(z_rest + 0.012*cos(phase+0.2)); independent of theta',
                           'scope': 'Known deterministic functional fixtures; not a new accuracy or quality holdout'}}
    data['represented_float32_words'] = {name: np.asarray(value, dtype=np.float32).view(np.uint32).tolist() for name, value in
                                         [('base_theta', data['base_theta']), ('fixed_z_fixtures', data['fixed_z_fixtures']),
                                          ('initial_z', data['training']['initial_z']), ('target_z', data['training']['target_z']), ('drive', data['training']['drive'])]}
    write('ASSET_INPUTS.json', data)
    names = ['asset_model.py', 'asset_common.py', 'audit_asset.py', 'train_asset.py', 'freeze_asset.py', 'README.md', 'requirements.txt']
    protocol = {'schema': 'hcsn.hx-fixed-potential-protocol.v1', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
                'status_at_freeze': 'No evaluation or trajectory of this new fixed-potential candidate has been opened.',
                'scope': 'New fixed physical log-potential model, finite-step functional boundary-chain/BPTT experiment. Not an equivalent coordinate rewrite, independent financial holdout or quality benchmark.',
                'previous_margin_V1_protocol_sha256': '87f30e6c00ea88532cc1e2e7be89174a18d2caef2799a4b0712421b0e9c8f241',
                'previous_margin_V1_loss_observation': {'initial': 0.0004702643782366067, 'final': 0.0004702617588918656, 'interpretation': 'Nearly unchanged; retained, not replaced by this new model.'},
                'dependencies': {'adapter_protocol_sha256': adapter_sha, 'adapter_source_sha256': sha(adapter_root/'hx_autograd.py'),
                                 'financial_protocol_sha256': financial_sha, 'financial_binary_sha256': sha(financial_root/'recovered.so'),
                                 'financial_mode': 'float64', 'adapter_coordinate': 'asset'},
                'source_sha256': {name: sha(ROOT/name) for name in names}, 'inputs_sha256': sha(ROOT/'ASSET_INPUTS.json'),
                'cell': {'steps': T, 'dt': .05, 'leak': .5, 'k_equity': .15, 'k_risk': .04, 'tau': .4,
                         'theta_fraction': .03, 'z_rest': z_rest}, 'fixed_boundary_probe_asset': 67.,
                'training': {'updates': 12, 'batch_size': B, 'optimizer': 'torch.optim.Adam default betas/epsilon, no weight decay',
                             'learning_rate': .02, 'trainable_parameters': 'only one 9-vector raw_theta, theta=base*(1+0.03*tanh(raw_theta))',
                             'loss': 'mean((z_T-target_z)^2)+0.25*mean((a_T-target_a)^2)', 'loss_decrease_is_gate': False},
                'gates': {'gradient_atol': 2e-9, 'gradient_rtol': 2e-5, 'linear_state_gradient_atol': 2e-6,
                          'nonzero_gradient_floor': 1e-12, 'min_z': 3.5, 'max_z': 4.7, 'max_adaptation': .08,
                          'range_tolerance': 1e-10, 'max_exp_log_roundtrip_error': 2e-7, 'minimum_sampled_phase_changes': 1,
                          'required_fixed_z_fixtures': 5, 'required_contract_checks': 15, 'required_temporal_comparisons': 8,
                          'no_nonfinite_or_rejected_rows_discarded': True},
                'fixed_physical_state_contract': ['z0, z_rest, drive and targets are frozen numeric words independent of theta and b.',
                                                   'V_repr=FP32_exp(z) retains its first-order PyTorch graph; it is not b(theta)*exp(x).',
                                                   'Original V3 asset.readout supplies Q,R,x with full asset derivatives; no extra boundary shift is applied to the already-total asset Jacobian.',
                                                   'x=log(V_repr/b), retained diagnostically; it is not assumed exactly z-log(b) under floating arithmetic.',
                                                   'The trained terminal loss reads only z and adaptation. No direct x or b term, no trained head.',
                                                   'A before/after fixture holds z and represented V identical and checks margin shift=-log(b_after/b_before).',
                                                   'Nine theta changes also alter value-field shape; movement does not establish causal threshold benefit or optimal boundary policy.'],
                'precision_contract': ['Only finite CPU FP32 neural states/inputs and represented exp(z). No silent float64 input downcast.',
                                       'Actual frozen financial arithmetic and saved 5x10 Jacobian in FP64; Q/R explicitly cast to FP32 for Euler.',
                                       'First-order continuous-formula Jacobians at represented points, not classical derivatives of quantization.',
                                       'No create_graph or higher derivatives. Time-unrolled first-order reverse AD only.'],
                'temporal_contract': ['Simultaneous old-state Euler, 16 true dynamical steps. Fixed z_rest changes the dynamics relative to margin V1.',
                                      'No normal state detach/reset/clipping; explicit detached-state path is a diagnostic negative control.',
                                      'One extra final readout per trajectory is no-grad logging only; it cannot enter terminal loss.',
                                      'Manual local asset Jacobian composition includes V*Q_V, V*R_V and the full fixed-V theta derivatives.',
                                      'All-default direct theta sensitivity can be zero; earlier positive-state history is not erased by entering default.',
                                      'Phase changes are sampled input-driven observations, not analytic crossing times or limit cycles.'],
                'excluded_claims': ['New financial precision qualification', 'quality or generalization advantage', 'analytic temporal flow',
                                    'autonomous spike/limit-cycle/stability proof', 'GPU/event-sparse/power advantage',
                                    'financial first-hit calibration under the new feedback process', 'pure-threshold causal attribution'],
                'exit_semantics': {'audit_asset.py': '0 only when all frozen functional gates pass; nonzero on errors/failures, create-only result.',
                                   'train_asset.py': '0 only for complete finite 12-step optimizer history, actual theta and fixed-asset boundary motion, and unchanged physical fixtures; loss improvement is not required.'}}
    write('ASSET_PROTOCOL.json', protocol)
    names += ['ASSET_INPUTS.json', 'ASSET_PROTOCOL.json']
    mapping = {'schema': 'hcsn.hx-fixed-potential-publication-mapping.v1', 'publication_prefix': PREFIX,
               'protocol_sha256': sha(ROOT/'ASSET_PROTOCOL.json'), 'stage': 'prefrozen before new model evaluation',
               'files': [{'local_path': str(ROOT/name), 'repo_path': PREFIX+'/'+name, 'sha256': sha(ROOT/name), 'bytes': (ROOT/name).stat().st_size} for name in names]}
    write('PREVALIDATION_MAPPING.json', mapping)
    print(json.dumps({'protocol_sha256': mapping['protocol_sha256'], 'mapping': str(ROOT/'PREVALIDATION_MAPPING.json'),
                      'mapping_sha256': sha(ROOT/'PREVALIDATION_MAPPING.json'), 'files': len(names)}, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--adapter-root', type=Path, required=True); p.add_argument('--financial-root', type=Path, required=True)
    a = p.parse_args(); main(a.adapter_root, a.financial_root)
