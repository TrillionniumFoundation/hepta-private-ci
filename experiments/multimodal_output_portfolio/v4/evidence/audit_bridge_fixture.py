"""Independent replay of the retained four-modality real-kernel bridge fixture."""

import json
from pathlib import Path
import time

import numpy as np
import torch

from audit_native import NativeAudit, bundle
from audit_runtime import native_snapshot, tensor_hash
from audit_tables import MODALITIES, NeuralReplay, ce, compare, direction, require, score_outputs, sha_file


@torch.inference_mode()
def audit_bridge_fixture(repo, directory, checkpoint, protocol, renderer, binary_sha256):
    started, cpu = time.perf_counter(), time.process_time()
    repo, directory = Path(repo), Path(directory)
    receipt = json.loads((directory / 'receipt.json').read_text())
    require(receipt['schema'] == 'hepta-v4-four-action-development-v1' and receipt['status'] == 'passed'
            and receipt['development_seed'] == 5 and len(receipt['streams']) == 4, 'complete four-action development fixture')
    require(sha_file(checkpoint) == receipt['checkpoint_sha256'] == protocol['source_checkpoints']['17']['sha256'],
            'fixture inherited checkpoint binding')
    require(receipt['native']['binary_sha256'] == binary_sha256 and receipt['native']['exit_code'] == 0
            and receipt['native']['completed_sessions'] == 4 and receipt['native']['stderr'] == ''
            and not receipt['native']['terminated_after_timeout'] and receipt['native']['caller_failure'] is None,
            'successful fixture uses the audited native binary')
    for name, expected in receipt['artifact_sha256'].items():
        require(name in ('actual-arrays.npz', 'native.tsv.gz') and sha_file(directory / name) == expected,
                ('fixture artifact hash', name))
    require(set(receipt['artifact_sha256']) == {'actual-arrays.npz', 'native.tsv.gz'}, 'complete fixture artifact inventory')
    require(set(receipt['source_sha256']) == {'bridge_development.py', 'allocation_bridge.py', 'allocation_model.py'},
            'complete fixture source inventory')
    for name, expected in receipt['source_sha256'].items():
        require(name in ('bridge_development.py', 'allocation_bridge.py', 'allocation_model.py')
                and sha_file(repo / 'experiments/multimodal_output_portfolio/v4' / name) == expected,
                ('fixture source binding', name))
    replay, native, targets = NeuralReplay(checkpoint), NativeAudit(directory / 'native.tsv.gz'), renderer.canonical()
    maximum_neural, maximum_values, streams = 0., 0., []
    price, probabilities = .015 / 8704, [.25, .5, .25]
    with np.load(directory / 'actual-arrays.npz', allow_pickle=False) as data:
        initial = np.stack([direction(4300000 + 5000 + 10 * m, .8).numpy() for m in range(4)])
        coefficients = np.array([1., .75, .5, .25], np.float32)
        modes = np.stack([[initial[m] * coefficients[(m - j) % 4] for m in range(4)] for j in range(4)])
        compare(data['initial_modes'], modes, 'fixture initial disturbance formulas', 0.)
        for depth in range(2):
            for m in range(4):
                positive = direction(4600000 + 5000 + 100 * (depth + 1) + m, .8).numpy()
                compare(data['future_banks'][depth, m], np.stack((-positive, np.zeros(64, np.float32), positive)),
                        'fixture global-index innovation formula', 0.)
        for m, name in enumerate(MODALITIES):
            row, session = receipt['streams'][m], native.session()
            sid = 'development-one-refine-' + name
            raw = data[sid + '_raw_text']
            expected_raw = renderer._render_modality(np.array([m]), 'text', np.random.default_rng(6000 + m), True)
            compare(raw, expected_raw, 'actual fixture input', 0.)
            require(replay.encode(raw).tolist() == [m] and session['condition'] == m
                    and session['policy_mode'] == 'COMMITTED' and session['plan'] == (m,), 'actual encoder and bound one-step plan')
            q, before, after = torch.eye(8)[[m]], data[sid + '_initial_latents'], data[sid + '_refined_latents']
            anchor = replay.anchor(q)
            maximum_neural = max(maximum_neural, compare(before, anchor.numpy()[:, None] + modes[[m]], 'fixture actual anchor', 2e-5))
            candidates = data[sid + '_candidate_latents']
            expected = replay.refine(q.repeat(3, 1), anchor.repeat(3, 1), torch.from_numpy(np.repeat(before[:, m], 3, 0)),
                                     torch.from_numpy(data['future_banks'][0, m]))
            maximum_neural = max(maximum_neural, compare(candidates[:, m], expected.numpy(), 'offline candidate neural refinements', 2e-5))
            require(all(np.array_equal(candidates[:, j], np.repeat(before[:, j], 3, 0)) for j in range(4) if j != m),
                    'offline candidates change only the selected modality')
            candidate_outputs = {modality: data[sid + '_candidates_' + modality] for modality in MODALITIES}
            decoded = replay.decode(torch.from_numpy(candidates))
            for modality in MODALITIES:
                maximum_neural = max(maximum_neural, compare(candidate_outputs[modality], decoded[modality], 'offline real decoder candidates', 2e-5))
            stops = -score_outputs(candidate_outputs, targets, np.full(3, m))['loss'] - price * 330240
            plan_value = ce(stops, probabilities, 2.) - .015
            maximum_values = max(maximum_values, compare([row['plan_value'], session['events'][0]['selected_value']],
                                                         [plan_value, plan_value], 'real plan utility', 1e-10))
            random = np.random.default_rng(np.random.SeedSequence([5200000, 5, m, 1, m]))
            branch = int(random.choice(3, p=probabilities))
            require(row['modality'] == name and row['branch'] == branch, 'fixture selected causal innovation')
            actual_refined = replay.refine(q, anchor, torch.from_numpy(before[:, m]),
                                           torch.from_numpy(data['future_banks'][0, m, branch][None]))
            maximum_neural = max(maximum_neural, compare(after[:, m], actual_refined.numpy(), 'actual one-step refinement', 2e-5))
            require(all(np.array_equal(before[:, j], after[:, j]) for j in range(4) if j != m)
                    and not np.array_equal(before[:, m], after[:, m]), 'selected actual modality changes exclusively')
            old_hashes, new_hashes = ([tensor_hash(array[:, j]) for j in range(4)] for array in (before, after))
            require(session['initial_latent_hashes'] == old_hashes and session['events'][0]['latent_hashes_after'] == new_hashes,
                    'native ACK binds actual modality states')
            outputs = {modality: data[sid + '_output_' + modality] for modality in MODALITIES}
            decoded = replay.decode(torch.from_numpy(after))
            for modality in MODALITIES:
                maximum_neural = max(maximum_neural, compare(outputs[modality], decoded[modality], 'actual four-decoder output', 2e-5))
            hashes = {modality: tensor_hash(outputs[modality]) for modality in MODALITIES}
            require(session['output_hashes'] == hashes == row['native_emitted']['output_hashes']
                    and row['native_emitted']['output_joint_hash'] == bundle(list(hashes.values()), 'outputs'), 'actual sealed outputs')
            maximum_values = max(maximum_values, compare([session['events'][1]['selected_value']], [stops[branch]], 'emission utility', 1e-10))
            identity, counts = {'session_id': sid, 'wire_session_id': session['session_id']}, [int(j == m) for j in range(4)]
            for key, version, remaining, paid_counts, phase, latent_hashes in (
                ('native_begin', 0, 347648, [0] * 4, 'ready', old_hashes),
                ('native_choice', 1, 338944, counts, 'await_refinement', old_hashes),
                ('native_refined', 1, 338944, counts, 'ready', new_hashes),
                ('native_emit_choice', 2, 8704, counts, 'await_outputs', new_hashes),
                ('native_emitted', 2, 8704, counts, 'sealed', new_hashes)):
                native_snapshot(row[key], identity, version, remaining, paid_counts, phase, latent_hashes)
            require(row['online_linear_macs'] == session['spent_macs'] == row['model_receipt']['spent_macs'] == 342528
                    and row['offline_linear_macs'] == 1017344 and row['model_receipt']['sealed'], 'fixture online and full-search accounting')
            require(row['model_receipt'] == {'spent_macs': 342528, 'budget_macs': 351232, 'remaining_macs': 8704,
                'version': 2, 'refinement_counts': counts, 'sealed': True, 'feedback_events': 2,
                'allocated_macs': [c * 8704 + d for c, d in zip(counts, (6656, 69632, 53248, 200704))],
                'reserved_emit_macs': 0, 'shared_init_macs': 3584}, 'exact per-modality executed allocation receipt')
            streams.append({'modality': name, 'selected_action': m + 1, 'branch': branch, 'complete_four_outputs': True})
    counts = {'base.initial_latent': 8}
    for suffix in (0, 2):
        counts[f'base.encoders.text.{suffix}'], counts[f'refinement.{suffix}'] = 4, 16
        for name in MODALITIES:
            counts[f'base.decoders.{name}.{suffix}'] = 16
    require(receipt['actual_model_work'] == {'linear_macs': 5439488, 'linear_layer_examples': counts}, 'actual fixture Linear hooks')
    return {'passed': True, 'four_actions_physically_executed': True, 'streams': streams,
            'native': native.finish(receipt['native']), 'receipt_sha256': sha_file(directory / 'receipt.json'),
            'maximum_neural_error': maximum_neural, 'maximum_compiled_utility_error': maximum_values,
            'verified_fixture_linear_macs': 5439488, 'audit_linear_macs': replay.macs,
            'audit_wall_seconds': time.perf_counter() - started, 'audit_process_cpu_seconds': time.process_time() - cpu,
            'scope': 'Four real-kernel modality actions with a research native bridge; no production attestation.'}
