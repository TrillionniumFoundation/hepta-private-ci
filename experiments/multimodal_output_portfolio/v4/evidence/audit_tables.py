"""Independent v4 neural, loss, Bellman and 21-plan artifact audit.

Only the frozen synthetic renderer is reused. No model, controller, metrics or
reporting implementation is imported. Audit compute is counted separately.
"""

import argparse
import hashlib
import importlib.util
from itertools import product
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np
import torch
from torch.nn import functional as F


MODALITIES = ('text', 'audio', 'image', 'video')
DIMENSIONS = dict(zip(MODALITIES, (40, 1024, 768, 3072)))
PLANS = [()] + [(m,) for m in range(4)] + list(product(range(4), repeat=2))
PROTOCOL_SHA256 = '4f90f435e3ce419a09f42412af1fc6fe3515f3c198e5e8555115b1996c1aab0b'
NODES = (32, 384, 4608)


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(actual, expected, label, tolerance):
    actual, expected = np.asarray(actual), np.asarray(expected)
    require(actual.shape == expected.shape, (label, 'shape', actual.shape, expected.shape))
    require(np.isfinite(actual).all() and np.isfinite(expected).all(), (label, 'nonfinite'))
    error = float(np.max(np.abs(actual.astype(np.float64) - expected.astype(np.float64))))
    require(error <= tolerance, (label, 'maximum absolute error', error, tolerance))
    return error


def ce(values, probabilities, gamma):
    values, probabilities = tuple(map(float, values)), tuple(map(float, probabilities))
    require(len(values) == len(probabilities) and len(values) > 0, 'CE support')
    require(all(math.isfinite(v) for v in values), 'CE nonfinite value')
    require(all(math.isfinite(p) and p >= 0 for p in probabilities)
            and abs(math.fsum(probabilities) - 1) <= 1e-12, 'CE probabilities')
    require(math.isfinite(gamma) and gamma >= 0, 'CE gamma')
    if gamma == 0:
        return math.fsum(p * v for p, v in zip(probabilities, values))
    floor = min(v for p, v in zip(probabilities, values) if p > 0)
    return floor - math.log(math.fsum(p * math.exp(-gamma * (v - floor))
                                    for p, v in zip(probabilities, values) if p > 0)) / gamma


def first_best(values, tolerance=1e-12):
    selected = 0
    for index in range(1, len(values)):
        if values[index] > values[selected] + tolerance:
            selected = index
    return selected


class NeuralReplay:
    """Saved tensor arithmetic, with no use of the learned-model class."""

    def __init__(self, checkpoint):
        saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
        require(saved['dimensions'] == DIMENSIONS, 'checkpoint dimensions')
        self.weights, self.macs = saved['state_dict'], 0
        require(all(value.dtype == torch.float32 and bool(torch.isfinite(value).all())
                    for value in self.weights.values()), 'checkpoint tensor contract')
        self.encoder_cost = sum(self.weights[f'base.encoders.text.{i}.weight'].numel() for i in (0, 2))
        self.anchor_cost = self.weights['base.initial_latent.weight'].numel()
        self.refine_cost = sum(self.weights[f'refinement.{i}.weight'].numel() for i in (0, 2))
        self.decoder_costs = {m: sum(self.weights[f'base.decoders.{m}.{i}.weight'].numel()
                                    for i in (0, 2)) for m in MODALITIES}

    def linear(self, value, name):
        weight = self.weights[name + '.weight']
        self.macs += len(value) * weight.numel()
        return F.linear(value, weight, self.weights[name + '.bias'])

    def anchor(self, q):
        return self.linear(q, 'base.initial_latent')

    def encode(self, raw):
        hidden = F.gelu(self.linear(torch.as_tensor(raw), 'base.encoders.text.0'))
        return torch.softmax(self.linear(hidden, 'base.encoders.text.2'), 1).argmax(1).numpy()

    def refine(self, q, anchor, latent, innovation):
        residual = latent - anchor
        hidden = F.gelu(self.linear(torch.cat((q, residual), 1), 'refinement.0'))
        gain = torch.sigmoid(self.linear(hidden, 'refinement.2'))
        return anchor + (1 - gain) * residual + innovation

    def decode(self, latents):
        return {m: self.linear(F.gelu(self.linear(latents[:, index], f'base.decoders.{m}.0')),
                               f'base.decoders.{m}.2').numpy()
                for index, m in enumerate(MODALITIES)}


def load_renderer(repo, protocol):
    relative = 'experiments/multimodal_output_portfolio/world.py'
    path = Path(repo) / relative
    original = subprocess.check_output(['git', 'show',
        protocol['source_scientific_freeze_commit'] + ':' + relative], cwd=repo)
    require(hashlib.sha256(original).hexdigest() == sha_file(path), 'renderer source drift')
    spec = importlib.util.spec_from_file_location('independent_v4_renderer', path)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    return renderer


def score_outputs(outputs, targets, labels):
    """Raw float64 squared differences and six independent class-pair checks."""
    labels = np.asarray(labels, dtype=np.int64)
    per_modality, guesses = [], []
    for modality in MODALITIES:
        values = np.asarray(outputs[modality], dtype=np.float64)
        prototypes = np.asarray(targets[modality], dtype=np.float64)
        require(values.shape == (len(labels), DIMENSIONS[modality]) and np.isfinite(values).all(),
                ('saved output', modality))
        normalizer = math.fsum(float(np.mean((prototypes[a] - prototypes[b]) ** 2))
                              for a in range(8) for b in range(8) if a != b) / 56
        distances = np.stack([np.mean((values - prototype) ** 2, axis=1)
                              for prototype in prototypes], axis=1) / normalizer
        guesses.append(distances.argmin(1))
        per_modality.append(np.minimum(distances[np.arange(len(labels)), labels], 2.))
    guesses = np.stack(guesses, axis=1)
    contradiction = np.mean([guesses[:, a] != guesses[:, b]
                             for a in range(4) for b in range(a + 1, 4)], axis=0)
    raw = np.stack(per_modality, axis=1)
    return {'loss': raw.mean(1) + .25 * contradiction, 'per_modality_error': raw,
            'contradiction': contradiction, 'guesses': guesses,
            'quality': np.mean(guesses == labels[:, None], axis=1)}


def direction(seed, scale):
    vector = np.random.default_rng(seed).normal(size=64)
    return torch.tensor((vector * (scale / np.sqrt(np.mean(vector ** 2)))).astype(np.float32))


def reference_tree(replay, study_seed, protocol):
    """32 roots, then parent-major/action-major/branch-major descendants."""
    scale = protocol['disturbance_design']['rms_direction_scale']
    base = np.asarray(protocol['disturbance_design']['initial_coefficient_base'], np.float32)
    coefficients = torch.from_numpy(base[(np.arange(4)[None, :] - np.arange(4)[:, None]) % 4])
    q8 = torch.eye(8)
    anchor8 = replay.anchor(q8)
    roots = anchor8.repeat_interleave(4, 0)
    directions = torch.stack([direction(4300000 + 1000 * study_seed + 10 * m, scale) for m in range(4)])
    latent = roots[:, None, :] + coefficients.repeat(8, 1)[:, :, None] * directions[None, :, :]
    for depth in range(3):
        yield depth, latent.numpy(), replay.decode(latent)
        if depth == 2:
            break
        count = len(latent)
        children = latent.repeat_interleave(12, 0).reshape(count, 4, 3, 4, 64)
        labels = np.repeat(np.arange(8), count // 8)
        qs = q8[labels].repeat_interleave(3, 0)
        anchors = anchor8[labels].repeat_interleave(3, 0)
        for m in range(4):
            positive = direction(4600000 + 1000 * study_seed + 100 * (depth + 1) + m, scale)
            innovations = torch.stack((-positive, torch.zeros(64), positive)).repeat(count, 1)
            changed = replay.refine(qs, anchors, latent[:, m].repeat_interleave(3, 0), innovations)
            children[:, m, :, m, :] = changed.reshape(count, 3, 64)
        latent = children.reshape(-1, 4, 64)
    clean = anchor8[:, None, :].expand(-1, 4, -1).clone()
    yield 'clean', clean.numpy(), replay.decode(clean)


def solve_tables(losses, protocol):
    gamma = protocol['objective']['gamma']
    price = protocol['objective']['mac_price_lambda']
    resource = protocol['resource_contract']
    emit_price = price * resource['emit_all_macs']
    refine_price = price * resource['refine_macs']['text']
    probabilities = protocol['disturbance_design']['branch_probabilities']
    tolerance = protocol['policies']['tie_tolerance']
    for depth, count in enumerate(NODES):
        require(np.asarray(losses[depth]).shape == (count,) and np.isfinite(losses[depth]).all(),
                ('loss table shape/finite', depth))
    result, maximum_gap = {}, 0.
    for mode in ('dynamic', 'myopic'):
        values = [None] * 3
        for depth in (2, 1, 0):
            scores = np.zeros((NODES[depth], 5), dtype=np.float64)
            scores[:, 0] = -losses[depth] - emit_price
            actions, current = np.zeros(NODES[depth], dtype=np.int64), np.empty(NODES[depth])
            for node in range(NODES[depth]):
                if depth < 2:
                    for m in range(4):
                        start = node * 12 + 3 * m
                        children = (values[depth + 1][start:start + 3] if mode == 'dynamic' else
                                    -losses[depth + 1][start:start + 3] - emit_price)
                        scores[node, m + 1] = ce(children, probabilities, gamma) - refine_price
                eligible = scores[node, :5 if depth < 2 else 1]
                action = first_best(eligible, tolerance)
                maximum_gap = max(maximum_gap, float(max(eligible) - eligible[action]))
                actions[node], current[node] = action, scores[node, action]
                if mode == 'myopic' and action:
                    start = node * 12 + 3 * (action - 1)
                    current[node] = ce(values[depth + 1][start:start + 3], probabilities, gamma) - refine_price
            values[depth] = current
            result[f'{mode}_scores_{depth}'] = scores
            result[f'{mode}_actions_{depth}'] = actions
            result[f'{mode}_values_{depth}'] = current
    plan_values = np.empty((32, 21), dtype=np.float64)
    for root in range(32):
        for index, plan in enumerate(PLANS):
            returns, weights = [], []
            for branches in product(range(3), repeat=len(plan)):
                node, probability = root, 1.
                for modality, branch in zip(plan, branches):
                    node = node * 12 + 3 * modality + branch
                    probability *= probabilities[branch]
                returns.append(-float(losses[len(plan)][node]) - emit_price - len(plan) * refine_price)
                weights.append(probability)
            plan_values[root, index] = ce(returns, weights, gamma)
    choices = np.array([first_best(row, tolerance) for row in plan_values], dtype=np.int64)
    selected = plan_values[np.arange(32), choices]
    plan_gap = float(np.max(plan_values.max(1) - selected))
    result.update(plan_values=plan_values, plan_choice=choices, plan_selected_value=selected)
    require(max(maximum_gap, plan_gap) <= tolerance + 1e-15, ('tie gap', maximum_gap, plan_gap))
    result['maximum_action_tie_gap'], result['maximum_plan_tie_gap'] = maximum_gap, plan_gap
    return result


def leaf_policy_value(root, losses, actions, protocol):
    """A separate complete-path CE, without reusing the Bellman backup."""
    probabilities = protocol['disturbance_design']['branch_probabilities']
    resources = protocol['resource_contract']
    price, gamma = protocol['objective']['mac_price_lambda'], protocol['objective']['gamma']
    returns, weights = [], []

    def visit(depth, node, probability):
        action = int(actions[depth][node])
        if action == 0:
            returns.append(-float(losses[depth][node]) - price *
                           (resources['emit_all_macs'] + depth * resources['refine_macs']['text']))
            weights.append(probability)
            return
        require(depth < 2 and 1 <= action <= 4, 'invalid independent policy action')
        for branch, weight in enumerate(probabilities):
            visit(depth + 1, node * 12 + 3 * (action - 1) + branch, probability * weight)

    visit(0, root, 1.)
    return ce(returns, weights, gamma)


def audit_tables(repo, protocol, checkpoint, study_seed, tree_path, policy_path):
    started, cpu_started = time.perf_counter(), time.process_time()
    development = protocol['development']
    source_seed = development['source_checkpoint_seed'] if study_seed == development['study_seed'] else study_seed
    require(study_seed in [*protocol['seeds'], development['study_seed']], 'study seed')
    require(sha_file(checkpoint) == protocol['source_checkpoints'][str(source_seed)]['sha256'], 'checkpoint hash')
    renderer = load_renderer(repo, protocol)
    targets = renderer.canonical()
    replay = NeuralReplay(checkpoint)
    resource = protocol['resource_contract']
    require(replay.encoder_cost == resource['text_encoder_macs']
            and replay.anchor_cost == resource['anchor_macs']
            and all(replay.refine_cost == v for v in resource['refine_macs'].values())
            and replay.decoder_costs == resource['decoder_macs'], 'actual weight MAC profile')
    texts = np.repeat(targets['text'], 2, axis=0)
    texts[1::2, -10:] = 0
    texts[1::2, -2] = 1
    maximum_latent_error, maximum_output_error, maximum_loss_error = 0., 0., 0.
    losses, clean_loss = [], None
    with torch.inference_mode(), np.load(tree_path, allow_pickle=False) as tables:
        require(np.array_equal(replay.encode(texts), np.repeat(np.arange(8), 2)), '16 clean encoder inputs')
        for depth, latent, outputs in reference_tree(replay, study_seed, protocol):
            latent_key = 'clean_latents' if depth == 'clean' else f'latents_{depth}'
            require(tables[latent_key].dtype == np.float32, (latent_key, 'dtype'))
            maximum_latent_error = max(maximum_latent_error, compare(tables[latent_key], latent, latent_key, 2e-5))
            actual = {}
            for modality in MODALITIES:
                key = f'clean_outputs_{modality}' if depth == 'clean' else f'outputs_{depth}_{modality}'
                actual[modality] = tables[key]
                require(actual[modality].dtype == np.float32, (key, 'dtype'))
                maximum_output_error = max(maximum_output_error, compare(actual[modality], outputs[modality], key, 2e-5))
            labels = np.arange(8) if depth == 'clean' else np.repeat(np.arange(8), NODES[depth] // 8)
            recomputed = score_outputs(actual, targets, labels)['loss']
            key = 'clean_loss' if depth == 'clean' else f'loss_{depth}'
            require(tables[key].dtype == np.float64, (key, 'dtype'))
            maximum_loss_error = max(maximum_loss_error, compare(tables[key], recomputed, key, 1e-10))
            if depth == 'clean':
                clean_loss = tables[key].copy()
            else:
                losses.append(tables[key].copy())
    independent = solve_tables(losses, protocol)
    maximum_value_error, action_checks = 0., 0
    with np.load(policy_path, allow_pickle=False) as tables:
        for key, value in independent.items():
            if key.startswith('maximum_'):
                continue
            if '_actions_' in key or key == 'plan_choice':
                require(tables[key].dtype == np.int64 and np.array_equal(tables[key], value), (key, 'selection mismatch'))
                action_checks += value.size
            else:
                require(tables[key].dtype == np.float64, (key, 'dtype'))
                maximum_value_error = max(maximum_value_error, compare(tables[key], value, key, 1e-10))
    root_values = {}
    for mode in ('dynamic', 'myopic'):
        actions = [independent[f'{mode}_actions_{d}'] for d in range(3)]
        leaves = [leaf_policy_value(root, losses, actions, protocol) for root in range(32)]
        maximum_value_error = max(maximum_value_error, compare(
            leaves, independent[f'{mode}_values_0'], mode + ' complete-leaf return', 1e-10))
        root_values[mode] = leaves
    root_values['initial_feedback_committed_open_loop'] = independent['plan_selected_value'].tolist()
    root_values['clean_no_disturbance_reference'] = np.repeat(-clean_loss -
        protocol['objective']['mac_price_lambda'] * resource['emit_all_macs'], 4).tolist()
    init_price = protocol['objective']['mac_price_lambda'] * resource['native_init_charge_macs']
    return {'schema': 'hepta.modality-allocation.independent-table-audit.v4', 'passed': True,
            'study_seed': study_seed, 'checkpoint_seed': source_seed,
            'checkpoint_sha256': sha_file(checkpoint), 'tree_sha256': sha_file(tree_path),
            'policy_sha256': sha_file(policy_path), 'renderer_sha256': sha_file(Path(repo) /
                'experiments/multimodal_output_portfolio/world.py'),
            'nodes_verified': sum(NODES), 'encoder_support_inputs': 16,
            'fixed_plans_verified': 32 * len(PLANS), 'action_and_plan_choices_verified': action_checks,
            'maximum_latent_error': maximum_latent_error, 'maximum_output_error': maximum_output_error,
            'maximum_saved_output_loss_error': maximum_loss_error,
            'maximum_same_table_value_error': maximum_value_error,
            'maximum_action_tie_gap': independent['maximum_action_tie_gap'],
            'maximum_plan_tie_gap': independent['maximum_plan_tie_gap'],
            'conditional_post_init_root_values': root_values,
            'J': {key: float(np.mean(value) - init_price) for key, value in root_values.items()},
            'audit_forward_linear_macs': replay.macs, 'audit_cost_separate': True,
            'wall_seconds': time.perf_counter() - started,
            'process_cpu_seconds': time.process_time() - cpu_started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'checkpoint', 'tree', 'policy', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args()
    protocol_path = args.repo / 'experiments/multimodal_output_portfolio/v4/protocol.json'
    require(sha_file(protocol_path) == PROTOCOL_SHA256, 'frozen v4 protocol hash')
    protocol = json.loads(protocol_path.read_text())
    torch.set_num_threads(protocol['runtime']['torch_threads'])
    report = audit_tables(args.repo, protocol, args.checkpoint, args.seed, args.tree, args.policy)
    report['protocol_sha256'] = PROTOCOL_SHA256
    report['auditor_sha256'] = sha_file(__file__)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': report['passed'], 'seed': args.seed,
                      'nodes': report['nodes_verified'], 'wall_seconds': report['wall_seconds']}))


if __name__ == '__main__':
    main()
