"""Independent v3 evidence audit, without importing the runner or its scoring.

Replays actual float32 neural operations from saved tensors, recomputes raw
output metrics and paired bootstrap estimates, and binds every native TSV
exchange to those replays. Audit work is separate from experimental cost.
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
from itertools import combinations_with_replacement
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F


MODALITIES = ('text', 'audio', 'image', 'video')
CONTROLLED = {'matched_supervised_feedback', 'ndu_feedback', 'ndu_myopic', 'ndu_robust'}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(value.detach().cpu().contiguous().numpy().tobytes())


def read(path):
    return json.loads(Path(path).read_text())


def require(value, detail):
    if not value:
        raise AssertionError(detail)


def close(actual, expected, detail, tolerance=1e-10):
    require(np.isfinite(actual) and np.isfinite(expected)
            and abs(float(actual) - float(expected)) <= tolerance,
            (detail, actual, expected))


def ce(values, probabilities, gamma):
    minimum = min(map(float, values))
    if gamma == 0:
        return math.fsum(float(p) * float(v) for p, v in zip(probabilities, values))
    return minimum - math.log(math.fsum(float(p) * math.exp(-gamma * (float(v) - minimum))
                                       for p, v in zip(probabilities, values))) / gamma


def tail_mean(values):
    ordered = np.sort(np.asarray(values, dtype=float))[::-1]
    mass = .1 * len(ordered)
    whole = int(math.floor(mass))
    return float((sum(ordered[:whole]) + (mass - whole) * ordered[whole]) / mass)


def bootstrap(left, right, repeats, statistic='mean'):
    """Independent paired nested seed/world percentile bootstrap."""
    left, right = np.asarray(left, float), np.asarray(right, float)
    require(left.shape == right.shape and left.ndim == 2, 'paired dimensions')
    seeds, worlds = left.shape
    fn = np.mean if statistic == 'mean' else tail_mean
    estimate = float(np.mean([fn(a) - fn(b) for a, b in zip(left, right)]))
    random = np.random.default_rng(2189)
    samples = []
    for _ in range(repeats):
        seed_indices = random.integers(seeds, size=seeds)
        indices = random.integers(worlds, size=(seeds, worlds))
        samples.append(np.mean([fn(left[s, w]) - fn(right[s, w])
                                for s, w in zip(seed_indices, indices)]))
    lo, hi = np.quantile(samples, [.025, .975])
    return {'estimate': estimate, 'ci_low': float(lo), 'ci_high': float(hi),
            'n_seeds': seeds, 'n_worlds_per_seed': worlds, 'bootstrap_replicates': repeats}


class Replay:
    """Manual tensor execution; no model/controller/evaluator functions called."""
    def __init__(self, checkpoint, targets):
        saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
        self.weights = saved['state_dict']
        self.dimensions = saved['dimensions']
        self.targets = {k: np.asarray(v, np.float64) for k, v in targets.items()}
        self.normalizers = {k: float(np.mean([np.mean((v[i] - v[j]) ** 2)
                             for i in range(8) for j in range(8) if i != j]))
                            for k, v in self.targets.items()}
        self.macs = 0
        groups = {k: hashlib.sha256() for k in saved['weight_sha256']}
        for name, value in sorted(self.weights.items()):
            require(bool(torch.isfinite(value).all()), ('nonfinite weight', name))
            group = ('.'.join(name.split('.')[1:3]) if name.startswith('base.decoders.')
                     else ('unused_v2_refinement' if name.startswith('base.refinement.')
                           else name.split('.')[1]) if name.startswith('base.') else 'refinement')
            array = value.numpy()
            header = repr((name, tuple(array.shape), str(array.dtype))).encode()
            for target in ('all', group):
                groups[target].update(len(header).to_bytes(8, 'little') + header + array.tobytes())
        self.hashes = {k: v.hexdigest() for k, v in groups.items()}
        require(self.hashes == saved['weight_sha256'], ('checkpoint weight hashes', str(checkpoint)))
        self.anchor_cost = self.weights['base.initial_latent.weight'].numel()
        self.refine_cost = sum(self.weights[f'refinement.{i}.weight'].numel() for i in (0, 2))
        self.emit_cost = sum(self.weights[f'base.decoders.{m}.{i}.weight'].numel()
                             for m in MODALITIES for i in (0, 2))
        self.encoder_cost = sum(self.weights[f'base.encoders.text.{i}.weight'].numel() for i in (0, 2))
        self.cache = {}

    def linear(self, value, name):
        weight = self.weights[name + '.weight']
        self.macs += len(value) * weight.numel()
        return F.linear(value, weight, self.weights[name + '.bias'])

    def anchor(self, q):
        return self.linear(q, 'base.initial_latent')

    def refine(self, q, anchor, latent, innovation):
        residual = latent - anchor
        gain = torch.sigmoid(self.linear(F.gelu(self.linear(torch.cat((q, residual), 1),
                                   'refinement.0')), 'refinement.2'))
        return anchor + (1 - gain) * residual + innovation

    def decode(self, latent):
        return {m: self.linear(F.gelu(self.linear(latent, f'base.decoders.{m}.0')),
                               f'base.decoders.{m}.2') for m in MODALITIES}

    def encode(self, text, modality='text'):
        logits = self.linear(F.gelu(self.linear(torch.as_tensor(text), f'base.encoders.{modality}.0')),
                             f'base.encoders.{modality}.2')
        return torch.softmax(logits, 1).numpy().argmax(1)

    def scores(self, outputs, truth):
        truth = np.asarray(truth)
        distances, guesses, omitted = [], [], []
        for modality in MODALITIES:
            values = np.asarray(outputs[modality], np.float64)
            distances.append(np.array([np.mean((values - prototype) ** 2, axis=1)
                             for prototype in self.targets[modality]]).T / self.normalizers[modality])
            guesses.append(distances[-1].argmin(1))
            nearest = np.sort(distances[-1], axis=1)[:, :2]
            omitted.append(nearest[:, 1] - nearest[:, 0] < .1)
        guesses = np.stack(guesses, 1)
        ambiguity = np.stack(omitted, 1)
        correct = guesses == truth[:, None]
        contradiction = np.mean(np.array([guesses[:, i] != guesses[:, j]
                                for i in range(4) for j in range(i + 1, 4)]), axis=0)
        raw = np.mean([np.minimum(d[np.arange(len(truth)), truth], 2.) for d in distances], axis=0)
        quality = correct.mean(1)
        color = (guesses // 2 == truth[:, None] // 2).mean(1)
        direction = (guesses % 2 == truth[:, None] % 2).mean(1)
        return {'loss': raw + .25 * contradiction, 'raw_error': raw, 'quality': quality,
                'correct_fraction': quality, 'class_error': 1 - quality,
                'color_accuracy': color, 'direction_accuracy': direction,
                'attribute_accuracy': (color + direction) / 2,
                'contradiction': contradiction, 'omission': ambiguity.mean(1),
                'resolved_correct_fraction': (correct & ~ambiguity).mean(1)}

    def trajectory(self, condition, branches, banks, clean=False):
        key = condition, tuple(branches), clean
        if key not in self.cache:
            q = torch.eye(8)[[condition]]
            anchor = self.anchor(q)
            latent = anchor + (torch.zeros(64) if clean else banks[0][branches[0]])
            latents = [latent]
            for depth, branch in enumerate(branches[1:], 1):
                latent = self.refine(q, anchor, latent, banks[depth][branch])
                latents.append(latent)
            self.cache[key] = (anchor, latents, self.decode(latent))
        return self.cache[key]

    def tree(self, banks):
        q = torch.eye(8)
        anchor = self.anchor(q)
        latents, losses = [], []
        for depth, bank in enumerate(banks):
            paths = 3 ** (depth + 1)
            qs = q.repeat_interleave(paths, 0)
            anchors = anchor.repeat_interleave(paths, 0)
            innovation = bank.repeat(8 * paths // 3, 1)
            latent = anchors + innovation if depth == 0 else self.refine(
                qs, anchors, latents[-1].reshape(-1, 64).repeat_interleave(3, 0), innovation)
            outputs = self.decode(latent)
            targets = np.repeat(np.arange(8), paths)
            losses.append(self.scores(outputs, targets)['loss'].reshape(8, paths))
            latents.append(latent.reshape(8, paths, 64))
        return latents, losses


def banks_for(seed, settings):
    result = []
    for depth in range(settings['maximum_refinements'] + 1):
        direction = np.random.default_rng(700000 + 101 * seed + depth).normal(size=64)
        direction *= settings['noise_scale'] / np.sqrt(np.mean(direction ** 2))
        result.append(torch.tensor(np.stack((-direction, np.zeros(64), direction)).astype(np.float32)))
    return result


def oracle(losses, settings, mode, gamma=None):
    gamma = settings['gamma'] if gamma is None else gamma
    probabilities = settings['nominal_branch_probabilities']
    rows = settings['ambiguity_rows'] if mode == 'robust' else [probabilities]
    values = [np.zeros_like(x) for x in losses]
    actions = [np.full(x.shape, 'emit', dtype='U6') for x in losses]
    continues = [None] * len(losses)
    values[-1] = -losses[-1]
    for depth in range(len(losses) - 2, -1, -1):
        continues[depth] = np.zeros_like(losses[depth])
        for q, node in np.ndindex(losses[depth].shape):
            children = values[depth + 1][q, 3 * node:3 * node + 3]
            value = min(ce(children, row, gamma) for row in rows) - settings['cost_penalty_per_refinement']
            selection = (ce(-losses[depth + 1][q, 3 * node:3 * node + 3], probabilities, gamma)
                         - settings['cost_penalty_per_refinement']) if mode == 'myopic' else value
            continues[depth][q, node] = selection
            take = selection > -losses[depth][q, node] + 1e-12
            values[depth][q, node] = value if take else -losses[depth][q, node]
            actions[depth][q, node] = 'refine' if take else 'emit'
    utility = np.mean([ce(row, probabilities, gamma) for row in values[0]])
    return {'actions': actions, 'continuation': continues, 'values': values, 'utility': utility}


class NativeTranscript:
    def __init__(self, path):
        self.stream = gzip.open(path, 'rt')
        self.digest = hashlib.sha256()
        self.requests, self.sessions = 0, 0

    def exchange(self, command, response):
        left, right = self.stream.readline(), self.stream.readline()
        self.digest.update((left + right).encode())
        require(left.startswith('> ') and right.startswith('< '), 'native transcript framing')
        actual_command, actual_response = left[2:].rstrip('\n').split('\t'), right[2:].rstrip('\n').split('\t')
        require(actual_command == list(map(str, command)), ('native command binding', command, actual_command))
        expected = list(map(str, response))
        if command[0] == 'CHOOSE':
            require(actual_response[:7] == expected[:7] and len(actual_response) == 8, 'native choice binding')
            close(float(actual_response[7]), float(expected[7]), 'native selected value', 1e-12)
        else:
            require(actual_response == expected, ('native acknowledgement', expected, actual_response))
        self.requests += 1

    def world(self, row, replay, horizon):
        self.sessions += 1
        sid, version, depth = self.sessions, 0, 0
        remaining = replay.emit_cost + horizon * replay.refine_cost
        self.exchange(['INIT', sid, remaining, replay.emit_cost, replay.refine_cost,
                       horizon, row['condition'], row['trace'][0]['latent_sha256']],
                      ['OK', 'INIT', sid, 0, remaining, 0, 'ready'])
        for event in row['trace']:
            command = ['CHOOSE', sid, version, depth, row['condition'], event['latent_sha256'],
                       'emit', repr(event['stop_value']), replay.emit_cost]
            if event['continue_value'] is not None:
                command += ['refine', repr(event['continue_value']), replay.refine_cost]
            expected_action = ('refine' if event['continue_value'] is not None and depth < horizon
                               and remaining >= replay.refine_cost + replay.emit_cost
                               and event['continue_value'] > event['stop_value'] + 1e-12 else 'emit')
            require(event['action'] == expected_action, 'independent native feasible argmax')
            remaining -= replay.refine_cost if expected_action == 'refine' else replay.emit_cost
            version += 1
            depth += int(expected_action == 'refine')
            value = event['continue_value'] if expected_action == 'refine' else event['stop_value']
            self.exchange(command, ['OK', 'CHOOSE', sid, version, remaining, depth, expected_action, repr(value)])
            if expected_action == 'refine':
                self.exchange(['REFINED', sid, version, depth, row['condition'],
                               row['trace'][depth]['latent_sha256']],
                              ['OK', 'REFINED', sid, version, remaining, depth, 'ready'])
            else:
                self.exchange(['EMITTED', sid, version] + [row['output_sha256'][m] for m in MODALITIES],
                              ['OK', 'EMITTED', sid, version, remaining, depth, 'sealed'])
        require(remaining == row['remaining'], 'native/model terminal budget agreement')

    def finish(self, receipt):
        require(self.stream.read() == '', 'unexpected extra native commands')
        self.stream.close()
        require(self.requests == receipt['requests'] and self.sessions == receipt['sessions'], 'native counts')
        require(self.digest.hexdigest() == receipt['transcript_sha256'], 'native uncompressed transcript hash')
        return {'sessions': self.sessions, 'requests': self.requests, 'hash_verified': True}


@torch.inference_mode()
def audit(args):
    started, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(4)
    repo, run = args.repo.resolve(), args.run.resolve()
    protocol, runtime = read(run / 'protocol.json'), read(run / 'runtime-start.json')
    completion, results = read(run / 'completion.json'), read(run / 'results.json')
    require(completion['completed'] and completion['source_unchanged'], 'incomplete run')
    require(not (run / 'failure.json').exists(), 'run retains failure marker')
    smoke = runtime['smoke']
    require(not smoke or args.allow_development, 'confirmation audit refuses a smoke run')
    manifest = read(run / 'artifact-manifest.json')
    require(set(manifest) == {str(p.relative_to(run)) for p in run.rglob('*')
                             if p.is_file() and p.name != 'artifact-manifest.json'}, 'artifact inventory')
    for name, receipt in manifest.items():
        payload = (run / name).read_bytes()
        require(len(payload) == receipt['bytes'] and sha(payload) == receipt['sha256'], ('artifact hash', name))
    source_drift = []
    for name, expected in runtime['source_sha256'].items():
        if sha((repo / name).read_bytes()) != expected:
            source_drift.append(name)
        if not smoke:
            committed = subprocess.check_output(['git', 'show', runtime['implementation_commit'] + ':' + name], cwd=repo)
            require(sha(committed) == expected, ('committed source binding', name))
    require(smoke or not source_drift, ('frozen source drift', source_drift))
    require(smoke or runtime['all_source_bytes_committed'], 'uncommitted confirmation source')
    protocol_matches = read(repo / 'experiments/multimodal_output_portfolio/v3/protocol.json') == protocol
    require(smoke or protocol_matches, 'protocol drift')
    sys.path.insert(0, str(repo / 'experiments/multimodal_output_portfolio'))
    # Only the frozen benchmark renderer is reused. Neural execution, action
    # backups, scoring, statistics and native checking are independent above.
    from world import canonical, render, sample_worlds
    targets = canonical()
    settings = protocol['feedback']
    horizon = settings['maximum_refinements']
    seeds = [protocol['development_seed']] if smoke else protocol['seeds']
    count = 24 if smoke else settings['heldout_worlds_per_seed_per_scenario']
    namespace = protocol['rng_namespace'] + ('-development' if smoke else '-confirmation')
    models, banks, trees, policies, training, static = {}, {}, {}, {}, [], {}
    compiled_states = 0
    for seed in seeds:
        banks[seed] = banks_for(seed, settings)
        saved_compilation = read(run / f'seed-{seed}/compiled-policies.json')
        static[seed] = read(run / f'seed-{seed}/static-selection.json')
        paired = {}
        for mode in ('supervised', 'ndu'):
            model = Replay(run / f'seed-{seed}/{mode}-model.pt', targets)
            models[seed, mode] = model
            receipt = read(run / f'seed-{seed}/{mode}-training.json')
            paired[mode] = receipt
            require(model.hashes == receipt['final_hashes'], 'model/training hash agreement')
            for group in model.hashes:
                if group not in ('all', 'refinement'):
                    require(receipt['initial_hashes'][group] == model.hashes[group], 'frozen source group')
            latents, losses = model.tree(banks[seed])
            trees[seed, mode] = latents, losses
            states = sum(x.size for x in losses)
            forward_cost = 8 * model.anchor_cost + states * model.emit_cost + (states - 24) * model.refine_cost
            expected_steps = 2 if smoke else settings[mode + '_steps' if mode == 'ndu' else 'matched_supervised_steps']
            require(receipt['steps'] == expected_steps and len(receipt['history']) == expected_steps, 'training steps')
            require(receipt['cost']['linear_macs'] == expected_steps * forward_cost, 'full-tree training MAC count')
            require(receipt['cost']['anchor_examples'] == expected_steps * 8, 'training anchor count')
            require(receipt['cost']['refinement_examples'] == expected_steps * (states - 24), 'training refiner count')
            require(all(n == expected_steps * states for n in receipt['cost']['decoder_examples'].values()), 'training decoder count')
            if mode == 'ndu':
                gradients = [r['refinement_objective_gradient_l2'] for r in receipt['history']]
                require(all(np.isfinite(v) for v in gradients) and receipt['gradient_is_utility_only']
                        and not receipt['auxiliary_loss_used'], 'gradient provenance flags')
                training.append({'seed': seed, 'steps': expected_steps,
                                 'nonzero_utility_only_steps': sum(v > 0 for v in gradients),
                                 'recorded_gradient_gate': sum(v > 0 for v in gradients) >= expected_steps / 2})
            for policy_mode in (('feedback',) if mode == 'supervised' else ('feedback', 'myopic', 'robust')):
                key = mode + '_' + policy_mode
                policy = oracle(losses, settings, policy_mode)
                policies[seed, key] = policy
                compiled_states += states
                close(policy['utility'], saved_compilation[key]['initial_nominal_utility'], 'independent root utility')
                require(saved_compilation[key]['offline_forward_linear_macs'] == forward_cost, 'compile MAC count')
                require(saved_compilation[key]['nodes'] == states, 'compile node count')
            utilities = []
            for depth, loss in enumerate(losses):
                probability = np.array(settings['nominal_branch_probabilities'])
                for _ in range(depth):
                    probability = np.kron(probability, settings['nominal_branch_probabilities'])
                utilities.append(np.mean([ce(-row, probability, settings['gamma']) for row in loss])
                                 - depth * settings['cost_penalty_per_refinement'])
            require(int(np.argmax(utilities)) == static[seed][mode]['depth'], 'independent static comparator')
            for actual, expected in zip(static[seed][mode]['nominal_utilities'], utilities):
                close(actual, expected, 'static expected utility')
        require(paired['supervised']['initial_hashes'] == paired['ndu']['initial_hashes'], 'matched initial tensors')
        require(paired['supervised']['cost'] == paired['ndu']['cost'], 'matched actual forward counts')
        if args.source_run is not None:
            origin_seed = protocol['seeds'][0] if smoke else seed
            source = protocol['source_checkpoints'][str(origin_seed)]
            checkpoint = args.source_run / source['path']
            require(sha(checkpoint.read_bytes()) == source['sha256'], 'frozen v2 checkpoint file')
            original = torch.load(checkpoint, map_location='cpu', weights_only=True)['state_dict']
            require(all(torch.equal(value, models[seed, 'ndu'].weights['base.' + key])
                        for key, value in original.items()), 'base checkpoint tensors preserved')
    audits = read(run / 'oracle-audits.json')
    require(len(audits) == 4 * len(seeds) and all(r['policy_mismatches'] == 0
            and r['max_value_error'] <= 1e-10 for r in audits), 'recorded finite oracle audits')
    native_receipt = read(run / 'native-execution.json')
    native = NativeTranscript(run / 'native-transcript.tsv.gz')
    binary = args.native_binary or Path(native_receipt['binary'])
    binary_matches = sha(binary.read_bytes()) == native_receipt['binary_sha256']
    require(smoke or binary_matches, 'executed native binary hash')
    if not smoke:
        build_path = repo / 'experiments/multimodal_output_portfolio/v3/evidence/native_build_final.json'
        build = read(build_path)
        require(sha(build_path.read_bytes()) == runtime['native_build_receipt_sha256'], 'final build receipt binding')
        require(build['binary_sha256'] == native_receipt['binary_sha256'] and build['exit_code'] == 0, 'final binary build')
        for path, expected in build['source_sha256'].items():
            require(sha((repo / path).read_bytes()) == expected, ('native final source', path))
    groups, batch_hashes, action_groups = {}, {}, defaultdict(set)
    inputs = {}
    for seed in seeds:
        for scenario_index, scenario in enumerate(settings['scenarios']):
            label_seed = 1400000 + (9000000 if smoke else 0) + 100 * seed + scenario_index
            labels = np.random.default_rng(label_seed).integers(8, size=count)
            raw = render(labels, label_seed + 400000, nuisance=True)
            condition = models[seed, 'ndu'].encode(raw['text'])
            inputs[seed, scenario] = labels, condition, label_seed + 200000
    with gzip.open(run / 'feedback-worlds.jsonl.gz', 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            key = row['seed'], row['scenario'], row['arm']
            seed, scenario, arm = key
            group = groups.setdefault(key, defaultdict(list))
            row_index = len(group['world_id'])
            require(row['world_id'] == f'{namespace}:{seed}:{scenario}:{row_index}', 'ordered distinct world IDs')
            labels, conditions, noise_seed = inputs[seed, scenario]
            require(row['truth'] == int(labels[row_index]) and row['condition'] == int(conditions[row_index]), 'raw input binding')
            mode = 'supervised' if arm.startswith('matched_supervised') else 'ndu'
            model = models[seed, mode]
            depth = int(row['depth'])
            require(depth == row['depth'] and 0 <= depth <= horizon, 'depth domain')
            require(len(row['trace']) == len(row['noise_branches']) == row['feedback_events'] == depth + 1, 'causal event count')
            probabilities = settings['nominal_branch_probabilities' if scenario == 'nominal_noise' else 'shift_branch_probabilities']
            rng = np.random.default_rng(noise_seed + 97 * row_index)
            require(row['noise_branches'] == [int(rng.choice(3, p=probabilities)) for _ in range(depth + 1)], 'paired causal innovations')
            anchor, latents, outputs = model.trajectory(row['condition'], row['noise_branches'], banks[seed],
                                                       arm == 'clean_no_disturbance_reference')
            require(set(row['output_sha256']) == set(MODALITIES), 'all four outputs')
            hashes = batch_hashes.setdefault(key, {m: hashlib.sha256() for m in MODALITIES})
            for modality, value in outputs.items():
                require(digest(value) == row['output_sha256'][modality], 'actual output tensor hash')
                hashes[modality].update(value.numpy().tobytes())
            require(row['linear_macs'] == model.encoder_cost + model.anchor_cost + depth * model.refine_cost + model.emit_cost, 'actual trajectory MAC')
            require(row['remaining'] == (horizon - depth) * model.refine_cost, 'terminal reserve')
            for d, (event, latent) in enumerate(zip(row['trace'], latents)):
                require(event['depth'] == d and event['latent_sha256'] == digest(latent), 'observed current latent hash')
                require(event['remaining_before'] == model.emit_cost + (horizon - d) * model.refine_cost, 'before-action budget')
                require(event['action'] == ('emit' if d == depth else 'refine'), 'no operation after sealing')
                close(event['residual_rms'], float((latent - anchor).square().mean().sqrt()), 'actual observed residual', 1e-7)
                if arm in CONTROLLED:
                    pkey = 'ndu_' + arm.removeprefix('ndu_') if arm in ('ndu_myopic', 'ndu_robust') else mode + '_feedback'
                    policy = policies[seed, pkey]
                    support, losses = trees[seed, mode]
                    errors = np.max(np.abs(support[d][row['condition']].numpy() - latent.numpy()[0]), axis=1)
                    index = int(errors.argmin())
                    require(index == event['node'] and errors[index] <= 2e-5, 'actual latent finite-node binding')
                    close(event['latent_match_max_error'], errors[index], 'latent matching roundoff', 1e-7)
                    close(event['stop_value'], -losses[d][row['condition'], index], 'independent STOP score')
                    if d < horizon:
                        close(event['continue_value'], policy['continuation'][d][row['condition'], index], 'independent continuation')
                    else:
                        require(event['continue_value'] is None, 'terminal horizon')
                    require(event['action'] == policy['actions'][d][row['condition'], index], 'independent Bellman action')
                action_groups[key + (row['condition'], d)].add(event['action'])
            if arm in CONTROLLED:
                native.world(row, model, horizon)
            else:
                expected_depth = 0 if arm in ('ndu_no_refine', 'clean_no_disturbance_reference') else static[seed][mode]['depth']
                require(depth == expected_depth, 'fixed-depth comparator execution')
            scores = model.scores(outputs, [row['truth']])
            for metric, value in scores.items():
                close(row[metric], value[0], 'independent raw output metric', 1e-12)
                group[metric].append(float(value[0]))
            for name in ('world_id', 'truth', 'depth', 'linear_macs'):
                group[name].append(row[name])
    native_audit = native.finish(native_receipt)
    native_audit['current_binary_matches_run'] = binary_matches
    native_audit['final_source_build_receipt_verified'] = not smoke
    summaries = read(run / 'feedback-summaries.json')
    require(len(groups) == len(summaries) == len(seeds) * len(settings['scenarios']) * len(settings['arms']), 'complete feedback grid')
    for summary in summaries:
        key = summary['seed'], summary['scenario'], summary['arm']
        group = groups[key]
        require(len(group['loss']) == count, 'all registered feedback worlds retained')
        for metric in group:
            if metric != 'world_id' and 'mean_' + metric in summary:
                close(summary['mean_' + metric], np.mean(group[metric]), 'feedback summary mean')
        require(summary['linear_macs'] == sum(group['linear_macs']), 'feedback total cost')
        require(summary['output_sha256'] == {m: h.hexdigest() for m, h in batch_hashes[key].items()}, 'batch output hashes')
        require(summary['depth_counts'] == {str(d): group['depth'].count(d) for d in range(horizon + 1)}, 'real depth distribution')
        both = sum(len(value) == 2 for k, value in action_groups.items() if k[:3] == key)
        require(summary['condition_depth_groups_with_both_actions'] == both, 'actual adaptive groups')
    return finish_audit(args, protocol, runtime, completion, results, groups, summaries,
                        models, policies, trees, training, native_audit, manifest,
                        source_drift, namespace, started, cpu, sample_worlds, render)


def source_audit(run, protocol, models, namespace, smoke, seeds, sample_worlds, render):
    settings = protocol['robust_sources']
    count = 24 if smoke else settings['heldout_worlds_per_scenario']
    groups = defaultdict(list)
    with gzip.open(run / 'source-worlds.jsonl.gz', 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            groups[row['seed'], row['scenario'], row['arm']].append(row)
    grid = [np.bincount(indices, minlength=8) / 4.
            for indices in combinations_with_replacement(range(8), 4)] + [np.full(8, .125)]
    grid = np.array(grid)
    stress = []
    summaries = read(run / 'source-summaries.json')
    require(len(groups) == len(summaries) == len(seeds) * len(settings['scenarios']) * len(settings['arms']), 'source study grid')
    for summary in summaries:
        seed, scenario, arm = summary['seed'], summary['scenario'], summary['arm']
        rows = groups[seed, scenario, arm]
        require(len(rows) == count, 'source world count')
        world_seed = 1300000 + 100 * seed + settings['scenarios'].index(scenario)
        world = sample_worlds(count, world_seed, namespace + '-source-heldout-' + scenario, scenario)
        require([r['world_id'] for r in rows] == world['ids'], 'source world IDs')
        require([r['truth'] for r in rows] == world['truth'].tolist(), 'source evaluation labels')
        selected = np.array([r['queried'] for r in rows])
        indices = np.array([r['portfolio_index'] for r in rows])
        require(np.all((indices >= 0) & (indices < len(grid))), 'source portfolio indices')
        model = models[seed, 'ndu']
        if arm in ('nominal', 'robust'):
            require(not selected.any(), 'no unauthorized witness in non-query arm')
        if arm == 'verifier_only':
            require(selected.all(), 'verifier-only queries all worlds')
        if selected.any():
            rng = np.random.default_rng(world_seed ^ 0x639812)
            wrong = (world['truth'] + rng.integers(1, 8, count)) % 8
            witness_class = np.where(rng.random(count) < settings['independent_verifier_error'], wrong, world['truth'])
            witness = render(witness_class, world_seed ^ 0x51777, nuisance=True)['text']
            report = model.encode(witness[selected])
            require(np.array_equal(grid[indices[selected]], np.eye(8)[report]), 'paid raw witness actually determines fallback')
        q = torch.as_tensor(grid[indices], dtype=torch.float32)
        output = model.decode(model.anchor(q))
        require({m: digest(v) for m, v in output.items()} == summary['output_sha256'], 'source actual decoder batch hashes')
        scores = model.scores(output, world['truth'])
        for metric, values in scores.items():
            require(np.max(np.abs(values - np.array([r[metric] for r in rows]))) <= 1e-12, 'source raw-output scoring')
            close(summary['mean_' + metric], values.mean(), 'source summary scoring')
        close(summary['cvar90'], tail_mean(scores['loss']), 'source CVaR')
        source_cost = 0
        if arm != 'verifier_only':
            for m in MODALITIES:
                unit = sum(model.weights[f'base.encoders.{m}.{i}.weight'].numel() for i in (0, 2))
                source_cost += int(np.any(world['raw'][m] != 0, axis=1).sum()) * unit
        source_cost += int(selected.sum()) * model.encoder_cost + count * (model.anchor_cost + model.emit_cost)
        require(source_cost == summary['forward_linear_macs'] and int(selected.sum()) == summary['queried'], 'source and witness cost')
        if arm == 'robust_verified' and scenario != 'iid':
            quality = float(scores['quality'].mean())
            stress.append({'seed': seed, 'scenario': scenario, 'quality': quality,
                           'pass': quality >= settings['gates']['robust_verified_quality_min_per_stress_scenario']})
    return {'arm_worlds_replayed': sum(map(len, groups.values())), 'stress_gates': stress,
            'scope': 'raw decoder outputs, paid witness binding and scores; source policy calibration/optimality not independently re-solved here'}


def finish_audit(args, protocol, runtime, completion, results, groups, summaries,
                 models, policies, trees, training, native_audit, manifest,
                 source_drift, namespace, started, cpu, sample_worlds, render):
    run, repo = args.run.resolve(), args.repo.resolve()
    smoke = runtime['smoke']
    seeds = [protocol['development_seed']] if smoke else protocol['seeds']
    repeats = 100 if smoke else protocol['statistics']['bootstrap_replicates']

    def contrast(scenario, candidate, baseline, metric='loss', statistic='mean'):
        left = [groups[seed, scenario, candidate] for seed in seeds]
        right = [groups[seed, scenario, baseline] for seed in seeds]
        for a, b in zip(left, right):
            require(a['world_id'] == b['world_id'] and a['truth'] == b['truth'], 'paired world/label identity')
        return bootstrap([a[metric] for a in left], [b[metric] for b in right], repeats, statistic)

    primary = contrast('nominal_noise', 'ndu_feedback', 'ndu_static')
    ratio = np.mean([np.mean(groups[s, 'nominal_noise', 'ndu_feedback']['linear_macs']) for s in seeds]) / np.mean([
        np.mean(groups[s, 'nominal_noise', 'ndu_static']['linear_macs']) for s in seeds])
    thresholds = protocol['feedback']['primary_gates']
    gates = {'mean_external_loss': primary['estimate'] <= thresholds['mean_external_loss_delta_max'],
             'paired_ci_upper': primary['ci_high'] < thresholds['paired_ci95_upper_below'],
             'online_linear_mac_ratio': ratio <= thresholds['online_linear_mac_ratio_max'],
             'output_budget_contracts': True, 'registered_seeds': not smoke and len(seeds) == len(protocol['seeds'])}
    gates = {name: bool(value) for name, value in gates.items()}
    for name in ('estimate', 'ci_low', 'ci_high'):
        close(results['primary'][name], primary[name], 'primary independent statistic')
    close(results['primary']['linear_mac_ratio'], ratio, 'primary cost ratio')
    require(results['primary']['gates'] == gates, 'primary gate truth values')
    require(results['primary']['pass'] == completion['primary_pass'] == all(gates.values()), 'preserve primary outcome')
    primary.update({'linear_mac_ratio': float(ratio), 'gates': gates, 'pass': all(gates.values())})
    secondary = {}
    for label, stored in results['secondary'].items():
        scenario, pair = label.split(':')
        candidate, baseline = pair.split('-')
        contrasts = {}
        for name, metric, statistic in [('mean_loss', 'loss', 'mean'), ('cvar90', 'loss', 'cvar90'),
                                        ('mean_quality', 'quality', 'mean')]:
            values = contrast(scenario, candidate, baseline, metric, statistic)
            for field in ('estimate', 'ci_low', 'ci_high'):
                close(values[field], stored[name][field], 'secondary independent statistic')
            contrasts[name] = values
        secondary[label] = contrasts
    refinement = [d for seed in seeds for d in groups[seed, 'nominal_noise', 'ndu_feedback']['depth']]
    fraction = sum(d > 0 for d in refinement) / len(refinement)
    adaptive = sum(r['condition_depth_groups_with_both_actions'] for r in summaries
                   if r['arm'] == 'ndu_feedback' and r['scenario'] == 'nominal_noise')
    close(fraction, results['mechanisms']['nominal_refined_fraction'], 'nondegenerate refinement')
    require(adaptive == results['mechanisms']['condition_depth_groups_with_both_actions'], 'adaptive mechanism')
    for observed, recorded in zip(training, results['mechanisms']['refinement_gradient']):
        require(observed['seed'] == recorded['seed'] and observed['nonzero_utility_only_steps'] == recorded['nonzero_utility_only_steps']
                and observed['recorded_gradient_gate'] == recorded['pass'], 'gradient mechanism gate')
    preference = read(run / 'preference-results.json')
    require([row['seed'] for row in preference] == seeds, 'all preference training seeds')
    errors, action_changes = [], []
    for seed_result in preference:
        seed = seed_result['seed']
        require([p['true_synthetic_gamma'] for p in seed_result['profiles']] == protocol['preference']['profiles'],
                'all registered preference profiles')
        for profile in seed_result['profiles']:
            gamma = profile['fit']['gamma']
            error = abs(gamma - profile['true_synthetic_gamma'])
            close(error, profile['absolute_error'], 'synthetic gamma error')
            errors.append(error)
            fitted = oracle(trees[seed, 'ndu'][1], protocol['feedback'], 'feedback', gamma)
            fixed = policies[seed, 'ndu_feedback']
            changed = sum(np.count_nonzero(a != b) for a, b in zip(fitted['actions'], fixed['actions']))
            require(changed == profile['changed_actions_vs_fixed_gamma2'], 'fitted preference changes real policy')
            close(fitted['utility'], profile['compiled_policy']['initial_nominal_utility'], 'fitted preference utility')
            action_changes.append({'seed': seed, 'gamma': gamma, 'changed_nodes': int(changed)})
    close(max(errors), results['preference']['max_absolute_error'], 'preference maximum error')
    require(results['preference']['registered_error_gate'] ==
            (max(errors) <= protocol['preference']['acceptance_absolute_gamma_error']), 'preference acceptance gate')
    sources = source_audit(run, protocol, models, namespace, smoke, seeds, sample_worlds, render)
    require(sources['stress_gates'] == results['new_witness_stress_gates'], 'source stress gate results')
    bsde = read(run / 'bsde-special-case.json')
    close(bsde['exact_U0'], -.49, 'analytic Gaussian utility')
    close(bsde['exact_Z'], .7, 'analytic Gaussian Z')
    for row in bsde['mesh']:
        steps = row['steps']
        value = -steps * math.log(math.cosh(1.4 / math.sqrt(steps))) / 2
        close(row['U0'], value, 'independent binomial entropic limit')
        close(row['Z'], .7, 'discrete Z')
    old_files = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only',
        protocol['parent_evidence_commit'], 'experiments/multimodal_output_portfolio'], cwd=repo, text=True).splitlines()
    preservation = subprocess.run(['git', 'diff', '--exit-code', protocol['parent_evidence_commit'],
        runtime['implementation_commit'], '--', *old_files], cwd=repo, capture_output=True)
    require(preservation.returncode == 0, 'v1/v2 historical source/evidence preservation')
    per_seed = []
    for seed in seeds:
        candidate = groups[seed, 'nominal_noise', 'ndu_feedback']
        baseline = groups[seed, 'nominal_noise', 'ndu_static']
        myopic = groups[seed, 'nominal_noise', 'ndu_myopic']
        per_seed.append({'seed': seed,
            'primary_mean_loss_delta': float(np.mean(candidate['loss']) - np.mean(baseline['loss'])),
            'primary_linear_mac_ratio': float(np.mean(candidate['linear_macs']) / np.mean(baseline['linear_macs'])),
            'recursive_minus_myopic_mean_loss': float(np.mean(candidate['loss']) - np.mean(myopic['loss'])),
            'recursive_and_myopic_loss_arrays_identical': candidate['loss'] == myopic['loss'],
            'recursive_and_myopic_depth_arrays_identical': candidate['depth'] == myopic['depth']})
    nominal_losses = {arm: float(np.mean([np.mean(groups[s, 'nominal_noise', arm]['loss']) for s in seeds]))
                      for arm in protocol['feedback']['arms']}
    return {'schema': 'hepta.feedback-generation.independent-audit.v3', 'audit_passed': True,
            'confirmatory': not smoke, 'run': str(run), 'source_commit': runtime['implementation_commit'],
            'audit_script_sha256': sha(Path(__file__).read_bytes()),
            'artifact_manifest_sha256': sha((run / 'artifact-manifest.json').read_bytes()),
            'artifact_hashes_verified': len(manifest), 'source_hashes_verified': len(runtime['source_sha256']) - len(source_drift),
            'development_source_drift': source_drift, 'old_files_unchanged': len(old_files),
            'current_protocol_matches_run': read(repo / 'experiments/multimodal_output_portfolio/v3/protocol.json') == protocol,
            'native': native_audit, 'primary_independent': primary, 'secondary_independent': secondary,
            'per_seed_primary_and_continuation': per_seed, 'nominal_arm_mean_external_loss': nominal_losses,
            'independent_bellman_trees': len(policies),
            'independent_bellman_states': sum(sum(a.size for a in p['actions']) for p in policies.values()),
            'feedback_arm_worlds_replayed': sum(len(g['loss']) for g in groups.values()),
            'feedback_discrete_trajectory_cache_entries': sum(len(m.cache) for m in models.values()),
            'nominal_ndu_depth_counts': {str(d): refinement.count(d) for d in range(protocol['feedback']['maximum_refinements'] + 1)},
            'nominal_refined_fraction': fraction, 'observed_latent_adaptive_groups': adaptive,
            'training_gradient_receipts': training, 'synthetic_preference_action_changes': action_changes,
            'training_gradient_steps_checked': sum(row['steps'] for row in training),
            'synthetic_preference_profiles_checked': len(errors),
            'source_replay': sources, 'bsde_scope': 'analytic entropic Gaussian special case only',
            'audit_wall_seconds': time.perf_counter() - started,
            'audit_process_cpu_seconds': time.process_time() - cpu,
            'audit_forward_linear_macs': sum(m.macs for m in models.values()),
            'audit_cost_separate_from_experiment': True,
            'limits': ['No reporting, metrics, controller or neural model implementation used for neural replay/statistics.',
                       'Frozen benchmark renderer is reused to reconstruct input and canonical target data.',
                       'Gradient values are source-reviewed recorded training receipts, not an independent optimizer replay.',
                       'Native hashes are local integrity evidence, not authenticated remote/kernel attestations.',
                       'No natural-data, general FBSDE, global-optimizer, production-runtime or dedicated-runner claim.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--native-binary', type=Path)
    parser.add_argument('--source-run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-development', action='store_true')
    args = parser.parse_args()
    with torch.inference_mode():
        report = audit(args)
    serialized = json.dumps(report, indent=2, allow_nan=False)
    with args.output.open('x') as destination:
        destination.write(serialized + '\n')
    print(json.dumps({key: report[key] for key in ('audit_passed', 'confirmatory', 'primary_independent',
                                                 'feedback_arm_worlds_replayed', 'audit_wall_seconds')}))


if __name__ == '__main__':
    main()
