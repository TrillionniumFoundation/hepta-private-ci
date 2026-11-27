"""Independent saved-byte review; no model forward or optimizer call."""

import hashlib
import io
import json
from pathlib import Path
import random
import time

import numpy as np
import torch

BASE = Path('/dev/shm/hepta-hcsn-gru-001')
OUT = Path(__file__).parent
STARTED = time.perf_counter()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tensors(values):
    h = hashlib.sha256()
    for name in sorted(values):
        value = values[name]
        h.update(name.encode())
        h.update(str((tuple(value.shape), value.dtype)).encode())
        h.update(value.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def metrics(logits, targets):
    scores = logits - logits.max(axis=1, keepdims=True)
    exponents = np.exp(scores)
    probabilities = exponents / exponents.sum(axis=1, keepdims=True)
    ce = np.mean(np.log(exponents.sum(axis=1)) - scores[np.arange(len(targets)), targets])
    predicted = logits.argmax(axis=1)
    f1 = []
    for label in range(8):
        tp = np.sum((predicted == label) & (targets == label))
        fp = np.sum((predicted == label) & (targets != label))
        fn = np.sum((predicted != label) & (targets == label))
        f1.append(float(2 * tp / (2 * tp + fp + fn)) if 2 * tp + fp + fn else 0.)
    return dict(cross_entropy=float(ce), accuracy=float(np.mean(predicted == targets)),
                macro_f1_8_classes=float(np.mean(f1)),
                brier_mean_classes=float(np.mean((probabilities - np.eye(8)[targets]) ** 2)),
                scored_positions=len(targets))


summary = json.loads((BASE / 'SUMMARY.json').read_text())
original = Path(summary['inputs']['DATA.json']['path'])
data = json.loads(original.read_text())
plan = json.loads(Path(summary['inputs']['PLAN.json']['path']).read_text())
failures, rows = [], []
before = {str(p): sha(p) for p in BASE.rglob('*') if p.is_file()}


def check(condition, message):
    if not condition:
        failures.append(message)


check(summary['source_unchanged'], 'source unchanged producer gate')
check(summary['source_before'] == summary['source_after'], 'source before/after equality')
check(sha(original) == summary['inputs']['DATA.json']['sha256'], 'input DATA digest')
check(summary['inputs_unchanged'], 'input identity producer gate')
for run in summary['runs']:
    seed = run['seed']
    root = BASE / f'seed{seed}'
    trace = [json.loads(line) for line in (root / 'training.jsonl').read_text().splitlines()]
    check(sha(root / 'training.jsonl') == run['training_trace_sha256'], f'{seed}: trace digest')
    order = list(range(len(data['train'])))
    random.Random(seed + 9000001).shuffle(order)
    schedule = [data['train'][order[i % len(order)]] for i in range(plan['updates'])]
    check(run['schedule'] == [row['id'] for row in schedule], f'{seed}: exact common schedule')
    check(len(trace) == plan['updates'] == run['actual_optimizer_updates'] == 32, f'{seed}: update denominator')
    check(trace[0]['model_sha256'] == run['initialization_sha256'], f'{seed}: initial model digest')
    events, scored = 0, 0
    for step, (record, episode) in enumerate(zip(trace, schedule)):
        states = np.asarray(record['states'])
        check(record['step'] == step and record['episode_id'] == episode['id'], f'{seed}/{step}: step identity')
        check(record['dt'] == [episode['dt']], f'{seed}/{step}: original physical time')
        check(record['valid_mask'] == [[True] * len(episode['y'])], f'{seed}/{step}: mask')
        check(states.shape == (1, len(episode['y']), 7) and np.isfinite(states).all(), f'{seed}/{step}: all hidden states')
        check(record['event_positions'] == len(episode['y']), f'{seed}/{step}: events')
        check(record['scored_positions'] == sum(y >= 0 for y in episode['y']), f'{seed}/{step}: scored queries')
        events += record['event_positions']
        scored += record['scored_positions']
    raw = (root / 'checkpoint.pt').read_bytes()
    check(hashlib.sha256(raw).hexdigest() == run['checkpoint_sha256'], f'{seed}: checkpoint digest')
    checkpoint = torch.load(io.BytesIO(raw), map_location='cpu', weights_only=True)
    check(tensors(checkpoint['model']) == run['final_model_sha256'], f'{seed}: final model digest')
    check(checkpoint['completed_optimizer_updates'] == 32, f'{seed}: checkpoint update count')
    check(not checkpoint['optimizer_step_outcome_unknown'], f'{seed}: optimizer finality')
    check({float(state['step']) for state in checkpoint['optimizer']['state'].values()} == {32.}, f'{seed}: Adam counters')
    for interface in ('frontend', 'readout'):
        prefix = interface + '.'
        selected = {name[len(prefix):]: value for name, value in checkpoint['model'].items() if name.startswith(prefix)}
        check(tensors(selected) == run['interfaces'][interface], f'{seed}: frozen {interface}')
    actual_parameters = sum(value.numel() for value in checkpoint['model'].values())
    check(actual_parameters == run['capacity']['total_parameters'] == 513, f'{seed}: parameter accounting')
    check(all(run['capacity'][name] <= run['hcsn_joint_ceilings'][name] for name in run['capacity']), f'{seed}: common ceilings')
    saved = json.loads((root / 'development.json').read_text())
    targets = np.array(saved['labels'], dtype=int)
    logits = np.array(saved['logits'], dtype=float)
    check(saved['episode_ids'] == [row['id'] for row in data['development']], f'{seed}: D ordering')
    check(saved['labels'] == [y for row in data['development'] for y in row['y'] if y >= 0], f'{seed}: D targets')
    recomputed = metrics(logits, targets)
    errors = {key: abs(value - run['development'][key]) for key, value in recomputed.items()}
    check(max(errors.values()) < 2e-14, f'{seed}: NumPy metric reconstruction')
    per_task = {}
    task_labels = np.array([row['task'] for row in data['development'] for y in row['y'] if y >= 0])
    for task in sorted(set(task_labels)):
        mask = task_labels == task
        per_task[task] = metrics(logits[mask], targets[mask])
        check(max(abs(value - run['development']['per_task'][task][key])
                  for key, value in per_task[task].items()) < 2e-14, f'{seed}: per-task metrics {task}')
    rows.append(dict(seed=seed, metrics=recomputed, maximum_metric_error=max(errors.values()),
                     per_task=per_task, traced_events=events, training_queries=scored,
                     trace_rows=len(trace), optimizer_updates=32, actual_parameter_tensors=actual_parameters))

check(all(sha(Path(path)) == digest for path, digest in before.items()), 'input output files unchanged during review')
report = dict(schema='hcsn-budget-gru-independent-byte-review-v1', passed=not failures, failures=failures,
              rows=rows, input_files_sha256=before, audit_source_sha256=sha(Path(__file__)),
              wall_seconds=time.perf_counter()-STARTED, numpy=np.__version__, torch=torch.__version__,
              methods='Independent NumPy logits metrics, schedule/state/byte counts and stored Adam states; zero model forward or optimizer calls',
              checkpoint_model_replay_performed_by_this_review=False, energy_joules=None)
with (OUT / 'RESULT.json').open('x') as stream:
    json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write('\n')
print(json.dumps({'passed':report['passed'],'failures':failures,'rows':rows}))
raise SystemExit(0 if report['passed'] else 1)
