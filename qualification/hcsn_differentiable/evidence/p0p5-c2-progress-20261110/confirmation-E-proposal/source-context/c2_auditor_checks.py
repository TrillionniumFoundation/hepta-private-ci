"""Independent metadata rules. Never imports the C2 producer or an optimizer."""
import hashlib
import json
import math
from pathlib import Path
import random

from audit_io import require


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def matrix_metrics(row):
    matrix = row['confusion_matrix']
    require(len(matrix) == 11 and all(len(r) == 11 for r in matrix), 'CM geometry')
    require(all(type(n) is int and n >= 0 for r in matrix for n in r), 'CM counts')
    total = sum(map(sum, matrix))
    require(total > 0 and row['events'] == total, 'CM event count')
    correct = sum(matrix[i][i] for i in range(11))
    f1 = [2 * matrix[i][i] / d if d else 0.0 for i in range(11)
          for d in [sum(matrix[i]) + sum(r[i] for r in matrix)]]
    actual = {'accuracy': correct / total, 'macro_f1_11_classes': sum(f1) / 11}
    require(all(finite(row[k]) and abs(row[k] - v) <= 2e-12 for k, v in actual.items()), 'CM metric disagreement')
    return actual


def stopping(rows, delta=.002, min_epochs=30, patience=10):
    best, anchor, stale, best_epoch, first_stop = -1.0, -1.0, 0, None, None
    for n, row in enumerate(rows, 1):
        require(row['epoch'] == n and row['complete'] is True, 'noncontiguous complete prefix')
        matrix_metrics(row['development'])
        value = row['development']['macro_f1_11_classes']
        if value > best:
            best, best_epoch = value, n
        if value > anchor + delta:
            anchor, stale = value, 0
        else:
            stale += 1
        if first_stop is None and n >= min_epochs and stale >= patience:
            first_stop = n
    return {'best': best, 'best_epoch': best_epoch, 'plateau_anchor': anchor,
            'stale_epochs': stale}, first_stop


def reconstruct_journal(events, episodes, seed, batch_size, micro_size, *,
                        parent_epoch=0, parent_updates=0, order_state=None, phase=False):
    """Reconstruct deterministic orders and actual logged work, including partial epochs."""
    ids = [r['id'] for r in episodes]
    counts = {r['id']: len(r['y']) for r in episodes}
    require(len(ids) == len(counts) and ids, 'training identities')
    rng = random.Random(seed)
    if order_state is not None:
        rng.setstate(order_state)
    completed, epochs, boundaries, steps = [], {}, {}, math.ceil(len(ids) / batch_size)
    active, batches, pending, started, b, updates = None, [], None, False, 0, 0
    witness = not phase
    times = (0.0, 0.0)
    completions = {}
    for index, event in enumerate(events):
        kind = event['kind']
        if kind == 'resume_start_committed':
            require(phase and not witness and not updates and active is None, 'duplicated/late resume witness')
            witness = True
        elif kind == 'epoch_started':
            require(witness and active is None and pending is None, 'overlapping or pre-witness epoch')
            active = parent_epoch + len(completed) + 1
            require(event['epoch'] == active, 'epoch skipped/repeated')
            order = list(ids)
            rng.shuffle(order)
            require(event['episode_order'] == order, 'sample shuffle differs')
            batches = [order[i:i+batch_size] for i in range(0, len(order), batch_size)]
            epochs[active] = {'order': order, 'journal_index': index, 'order_rng': rng.getstate()}
            b = 0
        elif kind == 'update_started' and event.get('phase') == 'main':
            require(active is not None and pending is None and b < steps, 'update outside epoch')
            pending = event['episode_ids']
            require(pending == batches[b], 'batch order differs')
            started = False
        elif kind == 'optimizer_started' and event.get('phase') == 'main':
            require(witness and pending is not None and not started, 'duplicate or unwitnessed optimizer start')
            if phase:
                require(event['logical_next_update'] == parent_updates + updates + 1, 'next logical update')
            started = True
        elif kind == 'optimizer_completed' and event.get('phase') == 'main':
            require(pending is not None and started, 'completion without matching optimizer start')
            updates += 1
            logical = parent_updates + updates
            require(event['number'] == logical and (not phase or event['new_number'] == updates), 'update counter differs')
            require(event['events'] == sum(counts[i] for i in pending), 'update event coverage')
            require(event['micro_forward_calls'] == math.ceil(len(pending) / micro_size), 'microbatch coverage')
            require(finite(event['loss']) and finite(event['gradient_norm']) and event['gradient_norm'] >= 0,
                    'nonfinite logged loss/gradient')
            completions[logical] = {'new': updates, 'epoch': active, 'batch': b, 'journal_index': index}
            b += 1
            pending, started = None, False
        elif kind == 'epoch_completed':
            require(active == event['epoch'] and pending is None and b == steps, 'incomplete epoch committed')
            require(event['complete'] is True and event['events'] == sum(counts.values()), 'epoch population differs')
            wall_key, cpu_key = ('phase_process_wall_seconds', 'phase_process_cpu_seconds') if phase else ('process_wall_seconds', 'process_cpu_seconds')
            now = event[wall_key], event[cpu_key]
            require(all(finite(v) for v in now) and now[0] >= times[0] and now[1] >= times[1], 'epoch clocks invalid')
            times = now
            completed.append(event)
            boundaries[active] = rng.getstate()
            active = None
    require(events and events[-1]['kind'] == 'finished', 'journal lacks terminal event')
    return {'completed': completed, 'started_epochs': epochs, 'boundary_rng': boundaries,
            'steps_per_epoch': steps, 'logged_new_updates': updates, 'logical_updates': parent_updates + updates,
            'completions': completions, 'final_order_rng': rng.getstate(),
            'unclosed_optimizer_call': bool(pending and started),
            'unclosed_forward_backward': bool(pending and not started),
            'possibly_unlogged_optimizer_updates': [0, 1] if pending and started else [0, 0]}


def verify_commit(commit, row, checkpoint, checkpoint_path, best_item, best_path, previous, rows, steps):
    require(commit['schema'] == 'hcsn-c2-complete-epoch-commit-v1' and commit['epoch'] == row, 'commit epoch differs')
    require(commit['checkpoint'] == checkpoint and commit['checkpoint_path'] == str(checkpoint_path), 'commit checkpoint differs')
    require(commit['best_checkpoint'] == best_item and commit['best_path'] == str(best_path), 'strict best commit differs')
    require(commit['previous_commit'] == previous, 'broken previous-commit chain')
    require(commit['logical_main_updates'] == row['epoch'] * steps, 'commit logical updates')
    state, first_stop = stopping(rows)
    require(commit['stopping'] == state, 'commit stopping differs')
    require(first_stop is None or first_stop == row['epoch'], 'training continued after historical plateau')
    return state


def expected_capture(episodes, order, logical, grid_states):
    by_id = {r['id']: r for r in episodes}
    effective, micro = order[:32], order[:8]
    padded = max(len(by_id[i]['y']) for i in effective)
    positions, indices, dt = [], [], []
    for p in range(padded):
        valid = [i for i, name in enumerate(micro) if p < len(by_id[name]['y'])]
        if valid:
            positions.append(p)
            indices.append(valid)
            dt.append([by_id[micro[i]]['dt'][p] for i in valid])
    return dict(effective_batch_episode_ids=effective, microbatch_episode_ids=micro, microbatch_range=[0, len(micro)],
                padded_events=padded, expected_positions=positions, expected_rows=len(positions),
                expected_batch_indices_by_position=indices, expected_dt_by_position=dt,
                expected_valid_sample_states=sum(map(len, indices)),
                expected_padded_sample_states=padded * len(micro) - sum(map(len, indices)),
                logical_completed_updates_before_step=logical, probability_state_count=grid_states)


def choose_common_lr(entries, roster):
    require(len(entries) == len(roster) and {r['name'] for r in entries} == set(roster), 'missing/duplicate candidate')
    if any(r.get('quality_reproducibility') != 'passed' for r in entries):
        return {'status': 'withheld_missing_or_failed_candidate', 'all_seed_means': None}
    rows = {}
    for lr in (.001, .003):
        group = [r for r in entries if r['learning_rate'] == lr]
        require(sorted(r['seed'] for r in group) == [101, 211, 307], 'missing seed opportunity')
        values = [r['fresh_development']['macro_f1_11_classes'] for r in group]
        mean = sum(values) / 3
        rows[str(lr)] = {'seed_values': values, 'mean': mean,
                        'sample_standard_deviation': math.sqrt(sum((v-mean)**2 for v in values)/2)}
    selected = max((.001, .003), key=lambda lr: rows[str(lr)]['mean'])
    return {'status': 'descriptive_same_D_tuning_only', 'all_seed_means': rows, 'common_lr': selected,
            'uncertainty_scope': 'initialization variability; same D used for selection, not held-out uncertainty'}
