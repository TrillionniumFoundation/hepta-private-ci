"""Bind saved v4 causal trajectories to independent neural and native replay.

The renderer is supplied explicitly; all neural arithmetic, loss and decisions
come from independent audit modules. Identical audit neural calls may be cached
and their actually executed MACs are reported separately from production work.
"""

from collections import defaultdict
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path
import time

import numpy as np
import torch

from audit_metadata import audit_metadata
from audit_native import ACTIONS, BUDGET, DECODERS, EMIT, INITIAL, REFINE, bundle
from audit_tables import (DIMENSIONS, MODALITIES, PLANS, NeuralReplay, ce, compare,
                          first_best, require, score_outputs, sha_file, solve_tables)


def tensor_hash(value):
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def array(data, key, shape, dtype):
    value = data[key]
    require(value.shape == shape and value.dtype == dtype and np.isfinite(value).all(),
            ('artifact array contract', key, value.shape, str(value.dtype)))
    return value


def sequence_value(losses, depth, node, sequence, protocol):
    probabilities = protocol['disturbance_design']['branch_probabilities']
    values, weights = [], []
    for branches in product(range(3), repeat=len(sequence)):
        child, mass = node, 1.
        for modality, branch in zip(sequence, branches):
            child, mass = child * 12 + modality * 3 + branch, mass * probabilities[branch]
        values.append(-losses[depth + len(sequence)][child]
                      - protocol['objective']['mac_price_lambda'] * (EMIT + REFINE * len(sequence)))
        weights.append(mass)
    return ce(values, weights, protocol['objective']['gamma'])


def sibling_evidence(groups, probabilities):
    strong, stop, observed = [], [], []
    for key, branches in groups.items():
        condition, initial_hash, first_action, remaining = key
        common = dict(condition=condition, initial_joint_hash=initial_hash,
                      first_action=first_action, remaining_after_first=remaining)
        evidence = []
        for branch, actions in sorted(branches.items()):
            require(probabilities[branch] > 0 and len(actions) == 1, 'positive-probability deterministic sibling')
            action, worlds = next(iter(actions.items()))
            evidence.append({'branch': branch, 'second_action': action, 'world_ids': worlds,
                             'observed_count': len(worlds), 'branch_probability': probabilities[branch]})
        observed.append({**common, 'branches': evidence})
        for left in range(len(evidence)):
            for right in range(left + 1, len(evidence)):
                pair = evidence[left], evidence[right]
                a, b = (item['second_action'] for item in pair)
                if a != b:
                    target = strong if a > 0 and b > 0 else stop
                    target.append({**common, 'branches': list(pair)})
    return {'strong_modality_reallocation_passed': bool(strong), 'strong_pairs': strong,
            'stop_versus_refine_pairs': stop, 'observed_sibling_groups': observed}


class ReplayCache:
    def __init__(self, checkpoint, raw_text):
        self.neural = NeuralReplay(checkpoint)
        self.encoded = self.neural.encode(raw_text)
        self.q = torch.eye(8)
        self.anchors = self.neural.anchor(self.q)
        self.refinements, self.emissions = {}, {}

    def refinement(self, condition, current, modality, innovation):
        key = condition, modality, tensor_hash(current[modality]), tensor_hash(innovation)
        if key not in self.refinements:
            value = self.neural.refine(self.q[[condition]], self.anchors[[condition]],
                                      torch.from_numpy(current[modality][None]),
                                      torch.from_numpy(innovation[None]))
            self.refinements[key] = value.numpy()[0]
        return self.refinements[key]

    def emission(self, current):
        key = tensor_hash(current)
        if key not in self.emissions:
            self.emissions[key] = self.neural.decode(torch.from_numpy(current[None]))
        return self.emissions[key]


def native_snapshot(snapshot, row, version, remaining, counts, phase, hashes):
    expected = {'wire_session_id': row['wire_session_id'], 'session_id': row['session_id'],
                'native_session_id': row['wire_session_id'],
                'version': version, 'remaining': remaining, 'refinement_counts': counts,
                'total_refinements': sum(counts), 'phase': phase, 'joint_hash': bundle(hashes)}
    require(all(snapshot[key] == value for key, value in expected.items()), 'trace/native snapshot binding')


def verify_trace(row, actual, observed_count, outputs, native, replay, tree, reference,
                 losses, protocol, seed, world_id, mode, replicate, arm):
    condition = int(replay.encoded[world_id])
    clean, committed = arm == 'clean_no_disturbance_reference', arm == 'initial_feedback_committed_open_loop'
    require(row['status'] == 'completed' and row['world_id'] == world_id and row['condition'] == condition
            and row['initial_mode'] == mode and row['replicate'] == replicate, 'trace registered world identity')
    require(native is not None and row['wire_session_id'] == native['session_id']
            and native['condition'] == condition, 'trace/native session identity')
    expected_mode = 'CLEAN' if clean else 'COMMITTED' if committed else 'ADAPTIVE'
    require(native['policy_mode'] == expected_mode, 'registered native policy mode')
    events = row['events']
    require(len(events) == observed_count == len(native['events']) and 1 <= len(events) <= 3,
            'exact observed causal trace length')
    require(np.all(actual[observed_count:] == 0), 'unobserved latent slots must remain zero')
    noise = np.zeros((4, 64), np.float32) if clean else tree['initial_modes'][mode]
    maximum_neural = compare(actual[0], replay.anchors[condition].numpy()[None] + noise,
                             'actual initial learned anchor plus registered disturbances', 2e-5)
    root, parent, previous_modality, counts, maximum_scores = None, None, None, [0] * 4, 0.
    for depth, (event, native_event) in enumerate(zip(events, native['events'])):
        current = actual[depth]
        hashes = [tensor_hash(current[m]) for m in range(4)]
        remaining = BUDGET - INITIAL - depth * REFINE
        require(event['depth'] == event['version'] == depth and event['spent_before'] == BUDGET - remaining
                and event['remaining_before'] == remaining and event['counts_before'] == counts,
                'actual pre-action resource state')
        require(event['latent_hashes'] == hashes == native_event['latent_hashes_before']
                and event['joint_hash'] == bundle(hashes), 'actual four-latent byte binding')
        if depth == 0:
            require(hashes == native['initial_latent_hashes'] and row['q_hash'] == native['q_hash'], 'INIT tensor binding')
            native_snapshot(row['native_begin'], row, 0, remaining, counts, 'ready', hashes)
        anchor = replay.anchors[condition].numpy()
        update = noise if depth == 0 else current - actual[depth - 1]
        compare(event['residual_rms'], np.sqrt(np.mean((current - anchor) ** 2, axis=1)), 'residual feedback', 2e-5)
        compare(event['last_update_rms'], np.sqrt(np.mean(update ** 2, axis=1)), 'last-update feedback', 2e-5)
        candidates = ([condition] if clean else list(range(condition * 4, condition * 4 + 4))
                      if depth == 0 else list(range(parent * 12 + previous_modality * 3,
                                                   parent * 12 + previous_modality * 3 + 3)))
        support = tree['clean_latents'] if clean else tree[f'latents_{depth}']
        distances = np.max(np.abs(support[candidates] - current), axis=(1, 2))
        matches = np.asarray(candidates)[distances <= 2e-5]
        require(len(matches) > 0, 'observed state belongs to causal public support')
        if len(matches) > 1 and not clean:
            for policy_arm in ('dynamic', 'myopic'):
                values = reference[f'{policy_arm}_scores_{depth}'][matches]
                compare(values, np.broadcast_to(values[0], values.shape), 'ambiguous state action values', 1e-10)
        node = candidates[int(distances.argmin())]
        require(event['node'] == node, 'lookup uses observed latent and causal prior action')
        if depth == 0:
            root = node
            require(row['initial_root'] == root, 'initial feedback root')
            plan_index = int(reference['plan_choice'][root]) if committed else None
            plan = PLANS[plan_index] if committed else ()
            require(row['plan_index'] == plan_index and row['plan'] == (list(plan) if committed else None)
                    and native['plan'] == tuple(plan), 'best initial-state 21-plan and immutable native binding')
        expected_scores, eligible = np.zeros(5), np.zeros(5, dtype=bool)
        if clean:
            expected_scores[0] = -tree['clean_loss'][condition] - protocol['objective']['mac_price_lambda'] * EMIT
            eligible[0] = True
        elif committed:
            chosen = plan[depth] + 1 if depth < len(plan) else 0
            expected_scores[chosen] = sequence_value(losses, depth, node, plan[depth:], protocol)
            eligible[chosen] = True
        else:
            expected_scores = reference[f'{arm}_scores_{depth}'][node]
            eligible[:5 if depth < 2 else 1] = True
        maximum_scores = max(maximum_scores, compare(event['scores'], expected_scores, 'independent causal action values', 1e-10))
        require(np.array_equal(event['scores'], native_event['scores'])
                and np.array_equal(event['eligible'], eligible)
                and np.array_equal(native_event['eligible'], eligible), 'candidate values and feasible set sent to native')
        feasible = np.flatnonzero(eligible)
        action = int(feasible[first_best(expected_scores[feasible])])
        require(event['action'] == native_event['action'] == action and event['action_name'] == ACTIONS[action],
                'independent causal chosen action')
        cost = EMIT if action == 0 else REFINE
        after_counts = list(counts)
        if action:
            after_counts[action - 1] += 1
        native_snapshot(event['native_choice'], row, depth + 1, remaining - cost, after_counts,
                        'await_refinement' if action else 'await_outputs', hashes)
        require(event['native_choice']['action'] == action and event['native_choice']['action_name'] == ACTIONS[action]
                and event['native_choice']['value'] == native_event['selected_value'], 'choice snapshot selected utility')
        if action:
            require(depth + 1 < len(events), 'every committed refinement has observed feedback')
            modality = action - 1
            random = np.random.default_rng(np.random.SeedSequence([5200000, seed, world_id, depth + 1, modality]))
            branch = int(random.choice(3, p=protocol['disturbance_design']['branch_probabilities']))
            innovation = tree['future_banks'][depth, modality, branch]
            require(event['branch'] == branch and event['global_refinement_index'] == depth + 1
                    and event['innovation_sha256'] == tensor_hash(innovation), 'selected-action keyed fresh innovation')
            following = actual[depth + 1]
            require(all(np.array_equal(current[m], following[m]) for m in range(4) if m != modality),
                    'three unselected actual modality states unchanged')
            expected = replay.refinement(condition, current, modality, innovation)
            maximum_neural = max(maximum_neural, compare(following[modality], expected, 'actual selected neural refinement', 2e-5))
            next_hashes = [tensor_hash(following[m]) for m in range(4)]
            require(next_hashes == native_event['latent_hashes_after'], 'native ACK binds next actual latents')
            native_snapshot(event['native_ack'], row, depth + 1, remaining - cost, after_counts, 'ready', next_hashes)
            parent, previous_modality, counts = node, modality, after_counts
        else:
            require(depth == len(events) - 1 and all(event[key] is None for key in
                    ('branch', 'global_refinement_index', 'innovation_sha256')), 'terminal emission has no future draw')
            decoded = replay.emission(current)
            output_hashes = {m: tensor_hash(outputs[m][world_id]) for m in MODALITIES}
            for name in MODALITIES:
                maximum_neural = max(maximum_neural, compare(outputs[name][world_id], decoded[name][0], 'actual learned decoder output', 2e-5))
            require(row['output_hashes'] == native['output_hashes'] == output_hashes
                    and row['output_joint_hash'] == bundle(list(output_hashes.values()), 'outputs'), 'complete actual emitted byte binding')
            native_snapshot(event['native_ack'], row, depth + 1, remaining - cost, counts, 'sealed', hashes)
            require(event['native_ack']['output_hashes'] == output_hashes
                    and event['native_ack']['output_joint_hash'] == row['output_joint_hash'], 'trace emitted ACK outputs')
    expected_receipt = {'spent_macs': INITIAL + sum(counts) * REFINE + EMIT, 'budget_macs': BUDGET,
                        'remaining_macs': BUDGET - INITIAL - sum(counts) * REFINE - EMIT,
                        'version': len(events), 'refinement_counts': counts, 'sealed': True,
                        'feedback_events': len(events), 'allocated_macs': [c * REFINE + d for c, d in zip(counts, DECODERS)],
                        'reserved_emit_macs': 0, 'shared_init_macs': INITIAL}
    require(row['receipt'] == expected_receipt and native['spent_macs'] == expected_receipt['spent_macs'],
            'sealed actual work, complete outputs and native budget agree')
    return maximum_neural, maximum_scores


@torch.inference_mode()
def audit_runtime_seed(directory, checkpoint, seed, protocol, renderer, native, replicates):
    started, cpu = time.perf_counter(), time.process_time()
    directory, count = Path(directory), 32 * replicates
    development = seed == protocol['development']['study_seed']
    settings = protocol['development' if development else 'confirmation']
    require(seed in [protocol['development']['study_seed'], *protocol['seeds']]
            and replicates == settings['worlds_per_condition_initial_mode'], 'registered seed and complete strata')
    source_seed = protocol['development']['source_checkpoint_seed'] if development else seed
    require(sha_file(checkpoint) == protocol['source_checkpoints'][str(source_seed)]['sha256'], 'registered runtime checkpoint')
    with np.load(directory / 'worlds.npz', allow_pickle=False) as data:
        worlds = {key: data[key] for key in data.files}
    raw = array(worlds, 'raw_text', (count, 40), np.float32)
    for key in ('truth', 'initial_mode', 'replicate', 'world_id'):
        array(worlds, key, (count,), np.int64)
    require(np.array_equal(worlds['world_id'], np.arange(count)), 'paired complete world order')
    for world_id in range(count):
        root, replicate = divmod(world_id, replicates)
        condition, mode = divmod(root, 4)
        require((worlds['truth'][world_id], worlds['initial_mode'][world_id], worlds['replicate'][world_id])
                == (condition, mode, replicate), 'registered balanced world strata')
        random = np.random.default_rng(np.random.SeedSequence([5100000, seed, condition, mode, replicate]))
        expected = renderer._render_modality(np.array([condition], np.int64), 'text', random, nuisance=True)[0]
        compare(raw[world_id], expected, 'registered fresh raw input', 0.)
    replay = ReplayCache(checkpoint, raw)
    require(np.array_equal(replay.encoded, worlds['truth']), 'real encoder clean-condition contract')
    with np.load(directory / 'tree.npz', allow_pickle=False) as data:
        tree = {key: data[key] for key in data.files if not key.startswith(('outputs_', 'clean_outputs_'))}
    with np.load(directory / 'policy.npz', allow_pickle=False) as policy:
        metadata = audit_metadata(tree, policy, seed)
    losses = [tree[f'loss_{depth}'] for depth in range(3)]
    reference = solve_tables(losses, protocol)
    targets, summaries, labels, groups = renderer.canonical(), {}, set(), {}
    maximum_neural, maximum_loss, maximum_scores, online_macs = 0., 0., 0., 0
    for arm in protocol['policies']['arms']:
        folder = directory / arm
        with np.load(folder / 'outputs.npz', allow_pickle=False) as data:
            outputs = {m: array(data, m, (count, DIMENSIONS[m]), np.float32) for m in MODALITIES}
        with np.load(folder / 'latents.npz', allow_pickle=False) as data:
            latents = array(data, 'latents', (count, 3, 4, 64), np.float32)
            observed = array(data, 'observed_count', (count,), np.int64)
        with np.load(folder / 'scores.npz', allow_pickle=False) as data:
            scores = {key: data[key] for key in data.files}
        expected_scores = score_outputs(outputs, targets, worlds['truth'])
        for key, shape in (('loss', (count,)), ('per_modality_error', (count, 4)), ('contradiction', (count,))):
            array(scores, key, shape, np.float64)
            maximum_loss = max(maximum_loss, compare(scores[key], expected_scores[key], 'saved-output external ' + key, 1e-10))
        for key, shape in (('macs', (count,)), ('refinement_counts', (count, 4)), ('condition', (count,)), ('world_id', (count,))):
            array(scores, key, shape, np.int64)
        compare(scores['world_id'], worlds['world_id'], 'score world order', 0.)
        compare(scores['condition'], replay.encoded, 'score actual condition', 0.)
        with np.load(folder / 'control.npz', allow_pickle=False) as control:
            for key in ('macs', 'refinement_counts', 'condition', 'world_id'):
                compare(control[key], scores[key], 'actual control receipt ' + key, 0.)
        with gzip.open(folder / 'traces.jsonl.gz', 'rt') as traces:
            for world_id in range(count):
                row = json.loads(traces.readline())
                require(row['session_id'] not in labels, 'unique external session labels')
                labels.add(row['session_id'])
                neural_error, score_error = verify_trace(row, latents[world_id], int(observed[world_id]), outputs,
                    native.session(), replay, tree, reference, losses, protocol, seed, world_id,
                    int(worlds['initial_mode'][world_id]), int(worlds['replicate'][world_id]), arm)
                maximum_neural, maximum_scores = max(maximum_neural, neural_error), max(maximum_scores, score_error)
                require(scores['macs'][world_id] == row['receipt']['spent_macs']
                        and np.array_equal(scores['refinement_counts'][world_id], row['receipt']['refinement_counts']),
                        'scored cost equals actual sealed trajectory')
                events = row['events']
                if arm == 'dynamic' and len(events) >= 2:
                    first, second = events[:2]
                    key = (row['condition'], first['joint_hash'], first['action'], second['remaining_before'])
                    actions = groups.setdefault(key, {}).setdefault(first['branch'], defaultdict(list))
                    actions[second['action']].append(world_id)
            require(traces.read() == '', 'no omitted or extra worlds')
        array(scores, 'return', (count,), np.float64)
        compare(scores['return'], -expected_scores['loss'] - protocol['objective']['mac_price_lambda'] * scores['macs'], 'priced return once', 1e-10)
        summary = json.loads((folder / 'summary.json').read_text())
        require(summary['status'] == 'completed' and summary['completed_worlds'] == summary['requested_worlds'] == count
                and summary['all_four_outputs'], 'successful complete arm')
        refinements = int(scores['refinement_counts'].sum())
        expected_layers = {'base.initial_latent': count}
        for suffix in (0, 2):
            expected_layers[f'base.encoders.text.{suffix}'] = count
            if refinements:
                expected_layers[f'refinement.{suffix}'] = refinements
            for name in MODALITIES:
                expected_layers[f'base.decoders.{name}.{suffix}'] = count
        paid = int(scores['macs'].sum())
        require(summary['actual_model_work'] == {'linear_macs': paid, 'linear_layer_examples': expected_layers},
                'actual Linear invocation hooks reconcile all encoders/refiners/four decoders')
        online_macs += paid
        summaries[arm] = {'worlds': count, 'actual_linear_macs': paid,
                          'refinement_counts': scores['refinement_counts'].sum(0).tolist(),
                          'mean_external_loss': float(expected_scores['loss'].mean())}
    return {'passed': True, 'seed': seed, 'arms': summaries, 'metadata': metadata,
            'sibling_evidence': sibling_evidence(groups, protocol['disturbance_design']['branch_probabilities']),
            'maximum_neural_error': maximum_neural, 'maximum_saved_output_loss_error': maximum_loss,
            'maximum_action_value_error': maximum_scores, 'verified_online_linear_macs': online_macs,
            'audit_neural_linear_macs': replay.neural.macs, 'audit_cache_unique_refinements': len(replay.refinements),
            'audit_cache_unique_emissions': len(replay.emissions), 'audit_wall_seconds': time.perf_counter() - started,
            'audit_process_cpu_seconds': time.process_time() - cpu, 'production_attestation_claim': False}
