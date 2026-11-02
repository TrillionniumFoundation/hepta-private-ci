"""Create-only preparation: fixed inputs and source seals, no new model calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
PREFIX = 'tools/hcsn/hx_two_layer_boundary_r16_20261101'
ADAPTER_PROTOCOL = '9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72'
FINANCIAL_PROTOCOL = '76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0'
REFERENCE = '35e8680e3faa501dcde7913a19b2998d2d799a1feb27667fbad6d55812c8ca69'
SOURCES = ('two_layer_model.py', 'two_layer_common.py', 'two_layer_reference.py',
           'audit_two_layer.py', 'train_two_layer.py', 'check_two_layer_results.py',
           'freeze_two_layer.py', 'README.md', 'requirements.txt')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (ROOT/name).open('x') as target:
        target.write(json.dumps(value, indent=2, allow_nan=False)+'\n')


def f32(value):
    return np.asarray(value, dtype=np.float32).tolist()


def main(adapter_root, financial_root):
    adapter_root, financial_root = Path(adapter_root), Path(financial_root)
    for name in ('TWO_LAYER_INPUTS.json', 'TWO_LAYER_PROTOCOL.json', 'PREVALIDATION_MAPPING.json'):
        if (ROOT/name).exists(): raise FileExistsError(name+' already exists; do not replace a frozen candidate')
    source_hashes = {name: sha(ROOT/name) for name in SOURCES}
    if source_hashes['two_layer_reference.py'] != REFERENCE:
        raise ValueError('Independent reference changed')
    if sha(adapter_root/'ADAPTER_PROTOCOL.json') != ADAPTER_PROTOCOL or sha(financial_root/'RECOVERY_PROTOCOL_V1.json') != FINANCIAL_PROTOCOL:
        raise ValueError('Wrong frozen dependencies')
    adapter = json.loads((adapter_root/'ADAPTER_PROTOCOL.json').read_text())
    financial = json.loads((financial_root/'RECOVERY_PROTOCOL_V1.json').read_text())
    for directory, protocol in ((adapter_root, adapter), (financial_root, financial)):
        for name, digest in protocol['source_sha256'].items():
            if sha(directory/name) != digest: raise ValueError('Dependency source changed '+name)
    if sha(financial_root/'recovered.so') != financial['binary_sha256']:
        raise ValueError('Financial binary changed')
    base = json.loads((adapter_root/'ADAPTER_FIXTURES.json').read_text())['cases'][0]['packed'][:9]
    T, B = 16, 8
    phase = 2.*np.pi*np.arange(B)/B
    nominal1 = np.asarray([50., 67., 100., 65., 70., 50., 100., 67.])
    nominal2 = np.asarray([100., 50., 70., 100., 67., 100., 50., 70.])
    z1, z2 = np.log(nominal1).astype(np.float32), np.log(nominal2).astype(np.float32)
    state = np.stack((z1, np.zeros(B, dtype=np.float32), z2, np.zeros(B, dtype=np.float32)), axis=-1)
    rest = float(np.float32(np.log(67.)))
    inputs = {'schema': 'hcsn.hx-two-layer-inputs.v1', 'base1': f32(base), 'base2': f32(base),
              'initial_state': f32(state),
              'drive1': f32(.12*np.sin(2.*np.pi*(np.arange(T)[:, None]+.5)/T+phase[None, :])),
              'drive2': f32(.08*np.sin(2.*np.pi*(np.arange(T)[:, None]+.5)/T+phase[None, :]+.35)),
              'target_z2': f32(z2.astype(np.float64)+.012*np.cos(phase+.2)),
              'target_a2': f32(.025+.005*np.sin(phase)), 'loss_a_weight': .25,
              'readout_fixture_z': f32(np.log(np.asarray([40., 50., 67., 70., 100.]))),
              'generation': {'deterministic': True, 'random_seed': None,
                             'nominal_initial_asset1': nominal1.tolist(), 'nominal_initial_asset2': nominal2.tolist(),
                             'initial_state': 'FP32(log(fixed nominal assets)), zero adaptations; independent of theta and b',
                             'rest': 'FP32(log(67)), fixed for both layers',
                             'drive1': 'FP32(0.12*sin(2*pi*(t+0.5)/16+2*pi*j/8))',
                             'drive2': 'FP32(0.08*sin(2*pi*(t+0.5)/16+2*pi*j/8+0.35)) before the layer-1 link',
                             'target_z2': 'FP32(represented initial z2+0.012*cos(2*pi*j/8+0.2))',
                             'target_a2': 'FP32(0.025+0.005*sin(2*pi*j/8))',
                             'scope': 'Known physical-range functional fixtures selected before new model evaluation, not a financial or quality holdout'}}
    numeric_names = ('base1', 'base2', 'initial_state', 'drive1', 'drive2', 'target_z2', 'target_a2', 'readout_fixture_z')
    inputs['represented_float32_words'] = {name: np.asarray(inputs[name], dtype=np.float32).view(np.uint32).tolist() for name in numeric_names}
    write('TWO_LAYER_INPUTS.json', inputs)
    protocol = {
        'schema': 'hcsn.hx-two-layer-protocol.v1', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'status_at_freeze': 'New financial evaluations, trajectories and optimizer updates of this candidate: zero. Only source review and independent non-financial synthetic chain tests have occurred.',
        'scope': 'Two one-way-coupled physical-potential states, continuous margin transmission and time-conditioned static H-X boundary; bounded functional first-order experiment only.',
        'publication_prefix': PREFIX,
        'dependencies': {'adapter_protocol_sha256': ADAPTER_PROTOCOL, 'adapter_source_sha256': sha(adapter_root/'hx_autograd.py'),
                         'financial_protocol_sha256': FINANCIAL_PROTOCOL, 'financial_binary_sha256': sha(financial_root/'recovered.so'),
                         'financial_mode': 'float64', 'adapter_coordinate': 'asset', 'independent_chain_source_sha256': REFERENCE},
        'source_sha256': source_hashes, 'inputs_sha256': sha(ROOT/'TWO_LAYER_INPUTS.json'),
        'cell': {'steps': T, 'dt': .05, 'leak': .5, 'k_equity': .15, 'k_risk': .04, 'tau': .4,
                 'fraction': .03, 'coupling_gain': .2, 'conditioning_gain': .5, 'z_rest1': rest, 'z_rest2': rest},
        'experiment': {'batch_size': B, 'updates': 12, 'learning_rate': .02,
                       'optimizer': 'torch.optim.Adam default betas/epsilon, no weight decay',
                       'trainable_parameters': ['raw_theta1[9]', 'raw_theta2[9]'],
                       'loss': 'mean((z2_T-target_z2)^2)+0.25*mean((a2_T-target_a2)^2)', 'loss_improvement_is_gate': False},
        'gates': {'gradient_atol': 2e-9, 'gradient_rtol': 2e-5, 'fp32_transcendental_ulps': 4,
                  'min_z': 3.5, 'max_z': 4.7, 'max_adaptation': .08, 'range_tolerance': 1e-10,
                  'constant_boundary_atol': 1e-10, 'minimum_boundary2_range': 1e-10,
                  'minimum_conditioning_vjp': 1e-12, 'minimum_direct_boundary_vjp': 1e-12, 'nonzero_gradient_floor': 1e-12,
                  'required_readout_contracts': 12, 'required_temporal_comparisons': 7,
                  'required_gradient_modes': 4, 'no_nonfinite_or_rejected_rows_discarded': True},
        'gradient_modes': {'full': 'both links active', 'drive_only': 'conditioning link detached',
                           'conditioning_only': 'drive link detached', 'both_detached': 'both links detached'},
        'identification_contract': [
            'The four graphs have exact numerical forward equality; they are derivative interventions, not forward-model quality ablations.',
            'Full upstream raw1 VJP equals drive-only plus conditioning-only; raw2 VJP is invariant across modes.',
            'Conditioning-only upstream VJP and the norm of its time-resolved [T,9] direct b1 boundary contributions must be nonzero; their net time sum can cancel. Zero in a required test is a retained failure, not permission to retune.',
            'Both-detached raw1, upstream initial-state and upstream external-drive VJPs must be zero; full early input/state influence must be nonzero.',
            'The independent NumPy reference composes archived full 5x10 financial Jacobians using actual tanh intermediates and reverse adjoints.',
            'G denotes continuous drift derivatives: every discrete parameter/cross-layer block includes dt. The direct b1 term is -b1_theta/b1.',
            'The direct conditioning boundary contribution and remaining state-history contribution are separately recorded.'],
        'precision_contract': [
            'Finite CPU FP32 states, assets, raw and effective parameters, links and Euler updates; FP64 financial arithmetic and saved raw Jacobians.',
            'Q/R are explicitly cast to FP32 inside each drift. Margin is explicitly cast to FP32 before both interlayer routes.',
            'First-order continuous-formula VJPs at represented points; rounding is not a differentiable model operation.',
            'The V3 bridge rejects create_graph=True; no second derivatives or C2 force are supplied.',
            'Four FP32 ULPs apply only to cross-library exp/tanh and derived theta record consistency. Linear links, preactivation and Euler checks require exact FP32 numerical equality. Financial accuracy and gradient gates are unchanged.'],
        'temporal_and_branch_contract': [
            'Sixteen simultaneous old-state Euler steps, no normal state detach, hard reset or binary event.',
            'z0, rest, drives and terminal z2/a2 targets remain fixed independently of b. No direct x or b loss and no trainable head.',
            'The scalar layer1 margin changes both layer2 drive and its static financial parameters at each time and sample.',
            'Raw V<=b determines the financial default branch. Q=0,R=1 there; x and its full boundary chain remain.',
            'b1 is constant within a rollout; b2 must vary within the first sixteen used states, not merely final logging.',
            'Two final no-grad financial readouts are logging only. Sampled branch transitions are not exact event times.',
            'Every time-conditioned H-X evaluation remains a static feature map, not the solution of a time-dependent financial PDE or analytic neural temporal flow.'],
        'prior_negative_results_retained': {
            'fixed_margin_V1': {'protocol_sha256': '87f30e6c00ea88532cc1e2e7be89174a18d2caef2799a4b0712421b0e9c8f241',
                                'loss_initial': .0004702643782366067, 'loss_final': .0004702617588918656},
            'fixed_asset_V1': {'protocol_sha256': '7e4791bee5b934f0aa55f603529d7ada5362b6908e70955f1441f5378691ddaa',
                               'loss_initial': .00047014461597427726, 'loss_final': .0004700341960415244,
                               'default_initial': 107, 'default_final': 127, 'sampled_crossings_initial': 8, 'sampled_crossings_final': 4},
            'interpretation': 'Nearly flat training and increased saturation are not superseded by this new architecture. No expected loss-improvement threshold is imposed.'},
        'excluded_claims': ['new financial precision qualification', 'unseen quality or multimodal benchmark', 'task or generalization advantage',
                            'analytic time-varying financial PDE solution', 'analytic recurrent flow', 'autonomous regenerative spikes or limit cycle',
                            'global stability or step-size convergence', 'GPU, event sparsity, power or speed advantage', 'pure boundary causal task benefit'],
        'exit_semantics': {'audit_two_layer.py': '0 only when every frozen audit gate passes; failures retain complete available records and exit nonzero.',
                           'train_two_layer.py': '0 only for complete finite twelve-update history, both parameter groups updated and all trajectory gates; loss decrease is not required.',
                           'check_two_layer_results.py': '0 only after independent source/input/raw binding, represented Euler, archived Jacobian chain, four-route and full history checks; no optimizer replay or financial calls.'}}
    write('TWO_LAYER_PROTOCOL.json', protocol)
    names = list(SOURCES)+['TWO_LAYER_INPUTS.json', 'TWO_LAYER_PROTOCOL.json']
    mapping = {'schema': 'hcsn.hx-two-layer-publication-mapping.v1', 'publication_prefix': PREFIX,
               'protocol_sha256': sha(ROOT/'TWO_LAYER_PROTOCOL.json'), 'stage': 'Frozen before any new candidate evaluation; waiting for remote checkpoint',
               'files': [{'local_path': str(ROOT/name), 'repo_path': PREFIX+'/'+name, 'sha256': sha(ROOT/name), 'bytes': (ROOT/name).stat().st_size} for name in names]}
    write('PREVALIDATION_MAPPING.json', mapping)
    print(json.dumps({'protocol_sha256': mapping['protocol_sha256'], 'mapping': str(ROOT/'PREVALIDATION_MAPPING.json'),
                      'mapping_sha256': sha(ROOT/'PREVALIDATION_MAPPING.json'), 'files': len(names)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--adapter-root', type=Path, required=True); parser.add_argument('--financial-root', type=Path, required=True)
    args = parser.parse_args(); main(args.adapter_root, args.financial_root)
