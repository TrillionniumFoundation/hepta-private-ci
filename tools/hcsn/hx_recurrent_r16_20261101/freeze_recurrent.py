"""Freeze the small functional experiment before any recurrent evaluation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
PREFIX = 'tools/hcsn/hx_recurrent_r16_20261101'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (ROOT/name).open('x') as f:
        f.write(json.dumps(value, indent=2, allow_nan=False)+'\n')


def f32(value):
    return np.asarray(value, dtype=np.float32).tolist()


def main(adapter_root, financial_root):
    adapter_root, financial_root = Path(adapter_root), Path(financial_root)
    expected_adapter = '9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72'
    expected_finance = '76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0'
    if sha(adapter_root/'ADAPTER_PROTOCOL.json') != expected_adapter or sha(financial_root/'RECOVERY_PROTOCOL_V1.json') != expected_finance:
        raise ValueError('Wrong immutable dependencies')
    base = json.loads((adapter_root/'ADAPTER_FIXTURES.json').read_text())['cases'][0]['packed'][:9]
    T, B = 16, 8
    phase = 2.*np.pi*np.arange(B)/B
    drive = .12*np.sin(2.*np.pi*(np.arange(T)[:, None]+.5)/T+phase[None, :])
    data = {'schema': 'hcsn.hx-recurrent-inputs.v1', 'base_theta': f32(base),
            'signed_fixture_x': f32([-.01, 0., .0001, .001, .01]),
            'training': {'initial_x': f32([-.02, -.01, 0., .01, .02, -.02, 0., .02]),
                         'initial_adaptation': f32(np.zeros(B)), 'drive': f32(drive),
                         'target_x': f32(.012*np.cos(phase+.2)),
                         'target_adaptation': f32(.025+.005*np.sin(phase)), 'adaptation_loss_weight': .25},
            'all_negative_control': {'initial_x': f32([-.05]), 'initial_adaptation': f32([0.]),
                                     'drive': f32(np.full((T, 1), -.08))},
            'generation': {'deterministic': True, 'random_seed': None,
                           'phase': '2*pi*j/8', 'drive': '0.12*sin(2*pi*(t+0.5)/16+phase_j), then quantize once to float32',
                           'x_target': '0.012*cos(phase+0.2), then float32',
                           'a_target': '0.025+0.005*sin(phase), then float32',
                           'scope': 'Functional integration fixtures, not statistical train/validation/test samples'}}
    data['represented_float32_words'] = {
        'base_theta': np.asarray(base, dtype=np.float32).view(np.uint32).tolist(),
        'drive': np.asarray(data['training']['drive'], dtype=np.float32).view(np.uint32).tolist(),
        'initial_x': np.asarray(data['training']['initial_x'], dtype=np.float32).view(np.uint32).tolist()}
    write('RECURRENT_INPUTS.json', data)
    names = ['recurrent.py', 'recurrent_common.py', 'audit_recurrent.py', 'train_recurrent.py', 'freeze_recurrent.py', 'README.md', 'requirements.txt']
    protocol = {'schema': 'hcsn.hx-recurrent-protocol.v1', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
                'status_at_freeze': 'No recurrent kernel evaluation, trajectory, gradient audit or training output has been opened.',
                'scope': 'Bounded functional proof of an actual finite-maturity H-X value readout and 16-step explicit Euler first-order BPTT. Not a new financial holdout, population benchmark or analytic temporal solution.',
                'dependencies': {'adapter_protocol_sha256': expected_adapter,
                                 'adapter_source_sha256': sha(adapter_root/'hx_autograd.py'),
                                 'financial_protocol_sha256': expected_finance,
                                 'financial_binary_sha256': sha(financial_root/'recovered.so'),
                                 'financial_mode': 'float64', 'adapter_version': 'V3 explicit create_graph rejection'},
                'source_sha256': {name: sha(ROOT/name) for name in names},
                'inputs_sha256': sha(ROOT/'RECURRENT_INPUTS.json'),
                'cell': {'steps': T, 'dt': .05, 'leak': .5, 'k_equity': .15, 'k_risk': .04, 'tau': .4, 'theta_fraction': .03},
                'training': {'updates': 12, 'batch_size': B, 'optimizer': 'torch.optim.Adam with default betas/epsilon and no weight decay', 'learning_rate': .02,
                             'trainable_parameters': 'one shared 9-vector raw_theta; theta=base*(1+0.03*tanh(raw_theta)); no output head or trainable gains',
                             'loss': 'mean((x_T-target_x)^2)+0.25*mean((a_T-target_a)^2)',
                             'loss_decrease_is_gate': False},
                'gates': {'gradient_atol': 2e-9, 'gradient_rtol': 2e-5, 'linear_state_gradient_atol': 2e-6,
                          'nonzero_gradient_floor': 1e-12, 'max_abs_x': .2, 'max_adaptation': .08,
                          'range_tolerance': 1e-10, 'minimum_sampled_phase_changes': 1,
                          'required_signed_fixtures': 5, 'required_contract_checks': 13,
                          'required_temporal_comparisons': 8, 'no_nonfinite_or_rejected_rows_discarded': True},
                'precision_contract': ['Only finite CPU torch.float32 theta, x, adaptation and drive inputs.',
                                       'Frozen actual financial kernel evaluates five fields and all ten Jacobian columns in FP64 at represented FP32 words.',
                                       'Signed Q/R outputs are FP64; explicit FP32 conversion precedes the FP32 Euler state update. VJP returns FP32.',
                                       'Analytic Jacobians of the underlying continuous formulas at represented values, as ordinary floating AD; not derivatives of the quantization map.',
                                       'Only first-order reverse mode; V3 rejects create_graph=True. BPTT composes first-order local Jacobians.'],
                'boundary_contract': ['Original log_distance requires x>=0 and x=0 right derivatives; unchanged.',
                                      'New signed neural readout uses original call at max(x,0) and explicit Q=0,R=1 for x<=0, retaining unclamped x.',
                                      'Negative/zero Q,R local theta/state derivatives are zero; x has state derivative 1 and theta derivative 0.',
                                      'Signed extension outputs only Q,R,x; raw F/G/debt at clamped zero are never represented as negative-x asset default outputs.',
                                      'Joint C1 requires regular positive boundary and the ideal smooth-pasting model. No C2 force or F/G C1 claim.'],
                'temporal_contract': ['All updates use old states; no hard reset, clipping or binary spike output.',
                                      'Normal graph has no state detach. Explicit detach_state mode is only a diagnostic negative control.',
                                      'Only terminal loss for temporal credit audit; separate theta_t clones expose per-step financial contribution.',
                                      'Manual reverse composition uses raw kernel Jacobians, Q quotient rule and R chain, independently of the PyTorch recurrence graph.',
                                      'All-negative control has exactly zero direct theta sensitivity; prior positive history can still propagate through later negative states.',
                                      'Sampled phase changes are discrete forced-trajectory observations, not limit-cycle, stability or continuous-time event proofs.'],
                'excluded_claims': ['Financial F/R calibration under the new feedback process', 'analytic recurrent flow', 'event sparsity or reset/refractory closure',
                                    'GPU or speed advantage', 'biological validity', 'generalization or multimodal quality advantage', 'second-order derivatives'],
                'exit_semantics': {'audit_recurrent.py': '0 only if all frozen checks pass; any exception/gate failure is nonzero; create-only full receipt.',
                                   'train_recurrent.py': '0 only for complete finite 12-update history and genuine bounded parameter update; loss decrease is not required.'}}
    write('RECURRENT_PROTOCOL.json', protocol)
    all_names = names+['RECURRENT_INPUTS.json', 'RECURRENT_PROTOCOL.json']
    mapping = {'schema': 'hcsn.hx-recurrent-publication-mapping.v1', 'publication_prefix': PREFIX,
               'protocol_sha256': sha(ROOT/'RECURRENT_PROTOCOL.json'), 'stage': 'prefrozen before evaluation',
               'files': [{'local_path': str(ROOT/name), 'repo_path': PREFIX+'/'+name,
                          'sha256': sha(ROOT/name), 'bytes': (ROOT/name).stat().st_size} for name in all_names]}
    write('PREVALIDATION_MAPPING.json', mapping)
    print(json.dumps({'protocol_sha256': mapping['protocol_sha256'], 'mapping': str(ROOT/'PREVALIDATION_MAPPING.json'),
                      'mapping_sha256': sha(ROOT/'PREVALIDATION_MAPPING.json'), 'files': len(mapping['files'])}, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--adapter-root', type=Path, required=True); p.add_argument('--financial-root', type=Path, required=True)
    args = p.parse_args()
    main(args.adapter_root, args.financial_root)
