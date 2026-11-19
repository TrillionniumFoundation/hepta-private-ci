"""Matched 66-parameter task-value and ordinary action distillation heads.

The architecture and information are identical; the intervention is the
training target/loss.  This is not a claim that two output channels alone
create extra information or a new universal architecture advantage.
"""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

from ..hcsn_free_boundary_v1.training import save_weights, load_weights
from .task_value import solve
from .task_value_common import sha, read_json, write_json


Q = 1 << 24
FAMILIES = ('bellman_value_head', 'ordinary_action_head', 'tabular_bellman',
            'validation_schedule', 'validation_risk')


class MatchedHead(nn.Module):
    def __init__(self, seed=34001):
        super().__init__()
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.network = nn.Sequential(nn.Linear(5, 8), nn.Tanh(), nn.Linear(8, 2))

    def forward(self, features):
        return self.network(features)


def features(prefix, state, ticks, tasks, price):
    values = np.broadcast_arrays(prefix, state, ticks, tasks, price)
    return np.stack([values[0] / 32, values[1] / 3, values[2] / 48,
                     values[3] / 3, values[4] / .02], axis=-1).astype(np.float32)


def confidence_state(confidence, prefix, edges):
    # A public quantizer makes the observation contract explicit.  It does not
    # guarantee that all different BLAS evaluation shapes have identical bins.
    confidence = np.rint(np.asarray(confidence, dtype=np.float64) * 10000) / 10000
    return np.asarray([np.searchsorted(edges[int(k)], float(c), side='right')
                       for c, k in zip(confidence.flat, np.asarray(prefix).flat)], dtype=np.int64).reshape(confidence.shape)


def make_solutions(model, prices):
    return {str(price): solve(model, horizon=48, tasks=3, price=price,
                              refractory=2, discount=1.) for price in prices}


def teacher_bank(solutions):
    x, y = [], []
    for price, solution in solutions.items():
        for tasks in range(1, 4):
            for ticks in range(1, 49):
                prefix, state = np.meshgrid(np.arange(1, 32), np.arange(4), indexing='ij')
                prefix, state = prefix.ravel(), state.ravel()
                x.append(features(prefix, state, ticks, tasks, float(price)))
                y.append(np.stack([solution.fire[tasks, ticks, prefix, state],
                                   solution.read[tasks, ticks, prefix, state]], -1))
    return torch.from_numpy(np.concatenate(x)), torch.from_numpy(np.concatenate(y).astype(np.float32))


class Policy:
    def __init__(self, family, solutions, edges, head=None, settings=None):
        self.family, self.solutions, self.edges = family, solutions, edges
        self.head, self.settings = head, settings or {}

    def score(self, prefix, state, ticks, tasks, price):
        prefix, state, ticks, tasks = np.broadcast_arrays(prefix, state, ticks, tasks)
        if self.family in FAMILIES[:2]:
            with torch.no_grad():
                q = self.head(torch.from_numpy(features(prefix, state, ticks, tasks, price)))
                score = (q[..., 1] - q[..., 0]).numpy().astype(np.float64)
        elif self.family == 'tabular_bellman':
            solution = self.solutions[str(price)]
            score = solution.read[tasks, ticks, prefix, state] - solution.fire[tasks, ticks, prefix, state]
        elif self.family == 'validation_schedule':
            setting = self.settings[str(price)]
            target = np.full(prefix.shape, setting['prefix'], dtype=float)
            if setting['balanced']:
                fair = np.maximum(1, (ticks + prefix - 2 * (tasks - 1)) // tasks)
                target = np.minimum(target, fair)
            score = target - prefix
        elif self.family == 'validation_risk':
            setting = self.settings[str(price)]
            score = (setting['threshold_bin'] - state).astype(float)
            if setting['balanced']:
                fair = np.maximum(1, (ticks + prefix - 2 * (tasks - 1)) // tasks)
                score = np.where(prefix >= fair, -1., score)
        else:
            raise ValueError('Unknown registered policy family')
        forced = (ticks == 0) | (prefix == 32)
        score = np.where(forced, -1., score)
        if not np.isfinite(score).all():
            raise FloatingPointError('Nonfinite feasible policy score')
        return score


def cached_rollouts(policy, trace, price, queue_seed, *, stream_limit=None):
    """Counterfactual paid-read ledger, not an actual inference-saving claim."""
    order = np.random.default_rng(queue_seed).permutation(len(trace['labels']))
    count = len(order) // 3
    queues = order[:count * 3].reshape(count, 3)
    if stream_limit is not None:
        queues = queues[:stream_limit]
        count = len(queues)
    row = np.arange(count)
    task = np.zeros(count, dtype=np.int64)
    prefix = np.zeros(count, dtype=np.int64)
    ticks = np.full(count, 48, dtype=np.int64)
    active = np.ones(count, dtype=bool)
    reads = np.zeros((count, 3), dtype=np.int64)
    correct = np.zeros_like(reads)
    predictions = np.full_like(reads, -1)
    fire_clock = np.full_like(reads, -1)
    first_future = np.zeros(count)
    for _ in range(96):
        index = np.flatnonzero(active)
        if not len(index):
            break
        if np.any(ticks[index] <= 0):
            raise AssertionError('Attempted a read beyond the deadline')
        image = queues[index, task[index]]
        observation = prefix[index]
        confidence = trace['confidence'][image, observation]
        prediction = trace['prediction'][image, observation]
        prefix[index] += 1
        ticks[index] -= 1
        reads[index, task[index]] += 1
        state = confidence_state(confidence, prefix[index], policy.edges)
        score = policy.score(prefix[index], state, ticks[index], 3 - task[index], price)
        firing = np.rint(np.tanh(score) * Q) <= 0
        stopped = index[firing]
        if len(stopped):
            image = queues[stopped, task[stopped]]
            correct[stopped, task[stopped]] = prediction[firing] == trace['labels'][image]
            predictions[stopped, task[stopped]] = prediction[firing]
            fire_clock[stopped, task[stopped]] = 48 - ticks[stopped]
            first = stopped[task[stopped] == 0]
            if len(first):
                first_future[first] = policy.solutions[str(price)].future_after_reset[3, ticks[first]]
            task[stopped] += 1
            active[stopped] = (task[stopped] < 3) & (ticks[stopped] > 2)
            reset = stopped[active[stopped]]
            ticks[reset] -= 2
            prefix[reset] = 0
    if active.any():
        raise AssertionError('Finite counterfactual task queue did not terminate')
    utility = correct.sum(-1) - price * reads.sum(-1)
    return {'queues': queues, 'task_reads': reads, 'task_correct': correct,
            'task_predictions': predictions, 'fire_clock': fire_clock,
            'utility': utility, 'first_fire_predicted_future': first_future,
            'actual_later_correct': correct[:, 1:].sum(-1),
            'actual_later_net_reward': correct[:, 1:].sum(-1) - price * reads[:, 1:].sum(-1)}


def validation_score(policy, trace, prices):
    by_price = {}
    for price in prices:
        raw = cached_rollouts(policy, trace, price, 73012)
        by_price[str(price)] = {'mean_utility': float(raw['utility'].mean()),
                                'mean_reads': float(raw['task_reads'].sum(-1).mean()),
                                'mean_correct': float(raw['task_correct'].sum(-1).mean())}
    return {'macro_utility': float(np.mean([row['mean_utility'] for row in by_price.values()])),
            'streams': len(raw['utility']), 'by_price': by_price}


def train_heads(output, protocol, solutions, edges, validation):
    output = Path(output)
    bank_clock = time.process_time()
    bank_x, bank_y = teacher_bank(solutions)
    with (output / 'teacher_bank.npz').open('xb') as stream:
        np.savez_compressed(stream, x=bank_x.numpy(), q=bank_y.numpy())
    bank_cpu = time.process_time() - bank_clock
    all_candidates, selections = {}, {}
    for family in FAMILIES[:2]:
        candidates = []
        for lr in protocol['learning_rates']:
            directory = output / family / ('lr_' + str(lr))
            directory.mkdir(parents=True, exist_ok=False)
            started = time.process_time()
            head = MatchedHead(protocol['head_seed'])
            if sum(p.numel() for p in head.parameters()) != 66:
                raise AssertionError('Matched head parameter count changed')
            initial = {name: p.detach().clone() for name, p in head.named_parameters()}
            ever = {name: torch.zeros_like(p, dtype=torch.bool) for name, p in head.named_parameters()}
            initial_sha = save_weights(directory / 'initial.npz', head)
            optimizer = torch.optim.Adam(head.parameters(), lr=lr)
            rng = torch.Generator().manual_seed(protocol['head_seed'] + 1)
            chain = hashlib.sha256()
            update_cpu = validation_cpu = 0.
            checkpoints = []
            with (directory / 'updates.jsonl').open('x') as log:
                for update in range(1, protocol['updates'] + 1):
                    clock = time.process_time()
                    indexes = torch.randint(len(bank_x), (protocol['batch_size'],), generator=rng)
                    chain.update(indexes.numpy().tobytes())
                    optimizer.zero_grad(set_to_none=True)
                    prediction = head(bank_x[indexes])
                    target = bank_y[indexes]
                    if family == 'bellman_value_head':
                        loss = (prediction - target).square().mean() + 25 * (
                            (prediction[:, 1] - prediction[:, 0]) - (target[:, 1] - target[:, 0])).square().mean()
                    else:
                        teacher_action = (torch.round(torch.tanh(
                            target[:, 1] - target[:, 0]) * Q) > 0).long()
                        loss = nn.functional.cross_entropy(prediction, teacher_action)
                    if not torch.isfinite(loss):
                        raise FloatingPointError('Nonfinite head loss')
                    loss.backward()
                    for name, p in head.named_parameters():
                        if p.grad is None or not torch.isfinite(p.grad).all():
                            raise FloatingPointError('Absent/nonfinite head gradient')
                        ever[name] |= p.grad != 0
                    norm = nn.utils.clip_grad_norm_(head.parameters(), 2.)
                    optimizer.step()
                    update_cpu += time.process_time() - clock
                    log.write(json.dumps({'update': update, 'loss': float(loss.detach()),
                               'gradient_norm_before_clip': float(norm), 'batch_indices': indexes.tolist(),
                               'batch_prefix_sha256': chain.hexdigest(), 'training_cpu_seconds': update_cpu}) + '\n')
                    if update in protocol['checkpoints']:
                        clock = time.process_time()
                        metrics = validation_score(Policy(family, solutions, edges, head), validation, protocol['prices'])
                        validation_cpu += time.process_time() - clock
                        path = directory / ('update_' + str(update) + '.npz')
                        digest = save_weights(path, head)
                        checkpoints.append({'update': update, 'path': str(path.relative_to(output)),
                                             'sha256': digest, 'validation': metrics,
                                             'parameter_changes': {name: {
                                                 'nonzero_gradient_parameters': int(ever[name].sum()),
                                                 'changed_parameters': int((p.detach() != initial[name]).sum()),
                                                 'parameters': p.numel()}
                                                 for name, p in head.named_parameters()}})
            changes = {name: {'nonzero_gradient_parameters': int(ever[name].sum()),
                              'changed_parameters': int((p.detach() != initial[name]).sum()),
                              'parameters': p.numel()} for name, p in head.named_parameters()}
            if any(v['nonzero_gradient_parameters'] != v['parameters']
                   or v['changed_parameters'] != v['parameters'] for v in changes.values()):
                raise AssertionError('Not all matched-head parameters participated')
            record = {'family': family, 'learning_rate': lr, 'initial_sha256': initial_sha,
                      'final_batch_prefix_sha256': chain.hexdigest(), 'parameter_changes': changes,
                      'training_cpu_seconds': update_cpu, 'validation_cpu_seconds': validation_cpu,
                      'complete_candidate_parent_cpu_seconds': time.process_time() - started,
                      'checkpoints': checkpoints}
            write_json(directory / 'SUMMARY.json', record)
            candidates.append(record)
        options = [(c, p) for c in candidates for p in c['checkpoints']]
        candidate, selected = max(options, key=lambda pair: (
            pair[1]['validation']['macro_utility'], -pair[1]['update'], -pair[0]['learning_rate']))
        if any(row['changed_parameters'] != row['parameters']
               or row['nonzero_gradient_parameters'] != row['parameters']
               for row in selected['parameter_changes'].values()):
            raise AssertionError('Selected head has an inactive/unchanged parameter')
        source = output / selected['path']
        destination = output / family / 'selected.npz'
        with destination.open('xb') as handle:
            handle.write(source.read_bytes())
        selection = {'family': family, 'learning_rate': candidate['learning_rate'], **selected,
                     'selected_checkpoint_sha256': sha(destination), 'selection_split': 'val',
                     'selection_utility_is_actual_prefix_correctness_minus_paid_reads': True}
        write_json(output / family / 'SELECTION.json', selection)
        all_candidates[family], selections[family] = candidates, selection
    initial_hashes = {c['initial_sha256'] for rows in all_candidates.values() for c in rows}
    batch_hashes = {c['final_batch_prefix_sha256'] for rows in all_candidates.values() for c in rows}
    if len(initial_hashes) != 1 or len(batch_hashes) != 1:
        raise AssertionError('Head initialization/minibatch pairing differs')
    return {'selections': selections, 'candidates': all_candidates,
            'teacher_bank_parent_cpu_seconds': bank_cpu,
            'all_initial_weights_identical': True, 'all_minibatch_prefixes_identical': True,
            'equal_update_and_selection_opportunities': True, 'equal_cpu_budget': False}


def select_ordinary(output, solutions, edges, validation, prices):
    candidates = {
        'validation_schedule': [{'prefix': k, 'balanced': balance} for k in (1, 2, 4, 8, 16, 32)
                                 for balance in (False, True)],
        'validation_risk': [{'threshold_bin': k, 'balanced': balance} for k in range(5)
                           for balance in (False, True)]}
    all_rows, selected, family_cpu = {}, {}, {}
    for family, settings in candidates.items():
        clock = time.process_time()
        selected[family], all_rows[family] = {}, {}
        for price in prices:
            rows = []
            for number, setting in enumerate(settings):
                policy = Policy(family, solutions, edges, settings={str(price): setting})
                raw = cached_rollouts(policy, validation, price, 73012)
                rows.append({'candidate': number, 'setting': setting,
                             'mean_utility': float(raw['utility'].mean()),
                             'mean_reads': float(raw['task_reads'].sum(-1).mean())})
            best = max(rows, key=lambda row: (row['mean_utility'], -row['mean_reads'], -row['candidate']))
            all_rows[family][str(price)] = rows
            selected[family][str(price)] = best['setting']
        family_cpu[family] = time.process_time() - clock
    result = {'selected': selected, 'all_validation_candidates': all_rows,
              'family_parent_cpu_seconds': family_cpu,
              'selection_split': 'val', 'teacher_or_test_labels_used_for_selection': False}
    write_json(Path(output) / 'ORDINARY_SELECTION.json', result)
    return result


def load_policies(output, solutions, edges):
    output = Path(output)
    policies = {}
    for family in FAMILIES[:2]:
        head = MatchedHead().eval()
        load_weights(output / family / 'selected.npz', head)
        head.requires_grad_(False)
        policies[family] = Policy(family, solutions, edges, head)
    policies['tabular_bellman'] = Policy('tabular_bellman', solutions, edges)
    ordinary = read_json(output / 'ORDINARY_SELECTION.json')['selected']
    for family in FAMILIES[3:]:
        policies[family] = Policy(family, solutions, edges, settings=ordinary[family])
    return policies
