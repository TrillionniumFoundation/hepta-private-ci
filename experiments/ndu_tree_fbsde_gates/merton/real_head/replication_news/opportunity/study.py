"""Train-only opportunity fitting and physically conditional Head execution."""
from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent/'sequential'))
from material_news import encode, loads, packet, sha, write
from trial_news import design, probabilities
from online import Trainer, setup, timed
from belief import BATCHES, STEPS, Planner

PROTOCOL_SHA = 'b62e3ab6cf681667ee9f4d920d5ca0293fc03a4460decc602a6e152f09413e3d'
FILES = ('protocol.json', 'belief.py', 'study.py', 'review.py', 'test_opportunity.py', 'README.md')
PARENT_FILES = ('material_news.py', 'trial_news.py', 'audit_news.py', 'sequential/online.py')


def config():
    raw = (HERE/'protocol.json').read_bytes()
    if sha(raw) != PROTOCOL_SHA:
        raise ValueError('opportunity protocol drift')
    return loads(raw)


def source_hashes():
    return {n: sha((HERE/n).read_bytes()) for n in FILES} | {
        '../'+n: sha((HERE.parent/n).read_bytes()) for n in PARENT_FILES}


def training_only(material, destination):
    a, receipt = packet(material/'worker.npz')
    with destination.open('xb') as f:
        np.savez(f, x=a['x_train'], y=a['y_train'], ids=a['train_ids'])
    return receipt


def read_training(path):
    with np.load(path, allow_pickle=False) as z:
        if set(z.files) != {'x', 'y', 'ids'}:
            raise ValueError('only original training inputs admitted to prior fitting')
        x, y, ids = (z[k].copy() for k in ('x', 'y', 'ids'))
    if x.shape != (64, 384) or not np.isfinite(x).all() or y.shape != (64,):
        raise ValueError('bad prior-training input shape')
    if y.dtype.kind not in 'iu' or np.any((y < 0) | (y > 3)):
        raise ValueError('invalid prior-training labels')
    if ids.shape != (64,) or len(set(ids.tolist())) != 64:
        raise ValueError('invalid prior-training identities')
    return x, y, ids


def fold_indices(ids):
    order = sorted(range(64), key=lambda i: sha(str(ids[i]).encode()))
    return [order[j::4] for j in range(4)]


def fit_curve(raw, labels, train, valid):
    """Actual 48-row SGD, same optimizer but an explicitly different sample count."""
    mean = raw[train].astype(np.float64).mean(axis=0)
    scale = np.maximum(np.sqrt(np.mean((raw[train].astype(np.float64)-mean)**2, axis=0)), 1e-6)
    x, v = design(raw[train], mean, scale), design(raw[valid], mean, scale)
    y = labels[train]
    w = np.zeros((385, 4), dtype=np.float64)
    snapshots, losses, counts = {}, [], []
    for step in range(129):
        if step in STEPS:
            snapshots[str(step)] = w.copy().tolist()
            counts.append(int(np.sum(probabilities(v, w).argmax(axis=1) == labels[valid])))
        if step == 128:
            break
        p = probabilities(x, w)
        losses.append(float(-np.log(p[np.arange(48), y]).mean()+.0005*np.sum(w[:-1]**2)))
        p[np.arange(48), y] -= 1
        g = x.T@p/48
        g[:-1] += .001*w[:-1]
        w -= .1*g
        if not np.isfinite(w).all():
            raise ValueError('nonfinite prior fit')
    return {'mean': mean.tolist(), 'scale': scale.tolist(), 'counts': counts,
            'checkpoints': snapshots, 'losses': losses, 'actual_updates': 128,
            'validation_calls': 4}


def fit_prior(training, output):
    config()
    c, w = time.process_time_ns(), time.perf_counter_ns()
    raw, labels, ids = read_training(training)
    rows = []
    for f, valid in enumerate(fold_indices(ids)):
        train = [i for i in range(64) if i not in valid]
        result, timing = timed(lambda: fit_curve(raw, labels, train, valid))
        rows.append({'fold': f, 'train_ids': ids[train].tolist(), 'valid_ids': ids[valid].tolist(),
                     **result, 'timing': timing})
    report = {'schema': 'hepta.merton.opportunity-prior.v1', 'posture': 'RESEARCH_ONLY_DENY_ALL',
              'protocol_sha256': PROTOCOL_SHA, 'training_sha256': sha(training.read_bytes()),
              'source_sha256': source_hashes(), 'rows': rows,
              'curves': [r['counts'] for r in rows], 'actual_updates': 512,
              'validation_calls': 16, 'calibration_or_holdout_used': False,
              'cpu_ns': time.process_time_ns()-c, 'wall_ns': time.perf_counter_ns()-w}
    write(output, report)
    print(encode({'prior_updates': 512, 'curves': report['curves']}).decode())
    return report


def matched_slope(history, scenario):
    """Cheap same-observation comparator, explicitly not an optimal oracle."""
    from fractions import Fraction as Q
    if not history:
        return {'action': 'continue' if scenario['budget'] >= 8 else 'stop',
                'to_step': 8 if scenario['budget'] >= 8 else None,
                'selected_steps': 0, 'reason': 'bounded_pilot_or_budget'}
    j = len(history)
    rates = [Q(1, 4)]+[Q(k, n) for k, n in zip(history, BATCHES)]
    best = max(range(j+1), key=lambda i: (rates[i], -i))
    result = {'action': 'stop', 'to_step': None, 'selected_steps': STEPS[best], 'reason': 'slope_or_budget'}
    if j == 3 or STEPS[j+1] > scenario['budget']:
        return result
    fee = Q(scenario['step_fee'])*(STEPS[j+1]-STEPS[j])+Q(scenario['calibration_fee'])
    gain = max(Q(0), rates[-1]-rates[-2])*(STEPS[j+1]-STEPS[j])/(STEPS[j]-STEPS[j-1])
    gain = min(1-rates[best], gain)
    if scenario['horizon']*gain > fee:
        result.update(action='continue', to_step=STEPS[j+1], reason='positive_local_slope')
    return result


def lifecycle(a, x, prior, arm, scenario, emit):
    cfg = config()
    if arm not in cfg['arms'] or scenario not in cfg['scenarios']:
        raise ValueError('unregistered lifecycle')
    c0, w0 = time.process_time_ns(), time.perf_counter_ns()
    trainer = Trainer(x['train'], a['y_train'], scenario['budget'])
    history, checkpoints, events, phases = [], {0: trainer.weights.copy()}, [], []
    planner = Planner(prior['curves'], scenario, arm[7:]) if arm.startswith('belief_') else None
    order = np.argsort(a['cal_hashes'], kind='stable')
    consumed_ids = []

    def log(e):
        events.append(e)
        emit(e)

    log({'kind': 'start'})
    while True:
        if arm in ('no_update', 'fixed8', 'fixed32'):
            target = 0 if arm == 'no_update' else int(arm[5:])
            take = target > trainer.updates and target <= scenario['budget']
            command = {'action': 'continue' if take else 'stop', 'to_step': target if take else None,
                       'selected_steps': trainer.updates, 'reason': 'fixed_schedule'}
        else:
            fn = (lambda: planner.decision(history)) if planner else (lambda: matched_slope(history, scenario))
            command, clock = timed(fn)
            phases.append({'kind': 'decision', **clock})
        log({'kind': 'decision', 'history': list(history), **command})
        if command['action'] == 'stop':
            selected = command['selected_steps']
            break
        target, before = command['to_step'], trainer.updates
        log({'kind': 'train_start', 'from_step': before, 'to_step': target})
        _, clock = timed(lambda: trainer.advance(target))
        phases.append({'kind': 'fit', **clock})
        checkpoints[target] = trainer.weights.copy()
        log({'kind': 'train_done', 'actual_steps': target,
             'weights_sha256': sha(encode(trainer.weights.tolist()))})
        if arm.startswith('fixed'):
            continue
        j = len(history)
        start, size = sum(BATCHES[:j]), BATCHES[j]
        indices = order[start:start+size]
        ids = a['cal_ids'][indices].tolist()
        count, clock = timed(lambda: int(np.sum(probabilities(x['cal'][indices], trainer.weights).argmax(axis=1)
                                               == a['y_cal'][indices])))
        phases.append({'kind': 'calibration', **clock})
        history.append(count)
        consumed_ids.extend(ids)
        log({'kind': 'observation', 'step': target, 'count': count, 'size': size, 'ids': ids})
    if selected not in checkpoints:
        raise ValueError('cannot select unexecuted checkpoint')
    weights = checkpoints[selected]
    predicted, clock = timed(lambda: probabilities(x['holdout'], weights))
    phases.append({'kind': 'prediction', **clock})
    log({'kind': 'success', 'actual_steps': trainer.updates, 'selected_steps': selected})
    return {'arm': arm, 'scenario': scenario['name'], 'history': history, 'selected_steps': selected,
            'actual_steps': trainer.updates, 'calibration_calls': len(history), 'calibration_ids': consumed_ids,
            'weights': weights.tolist(), 'checkpoints': {str(k): v.tolist() for k, v in checkpoints.items()},
            'losses': trainer.losses, 'probabilities': predicted.tolist(), 'holdout_ids': a['holdout_ids'].tolist(),
            'events': events, 'phases': phases, 'cpu_ns': time.process_time_ns()-c0,
            'wall_ns': time.perf_counter_ns()-w0}


def run(material, prior_path, output):
    cfg = config()
    a, receipt = packet(material/'worker.npz')
    prior = loads(prior_path.read_bytes())
    if (prior['source_sha256'] != source_hashes() or prior['protocol_sha256'] != PROTOCOL_SHA
            or prior['calibration_or_holdout_used'] is not False or prior['actual_updates'] != 512):
        raise ValueError('incompatible prior')
    # Binding to the exact current training packet, not arbitrary externally supplied rates.
    temporary = output.parent/(output.name+'-training.npz')
    training_only(material, temporary)
    if sha(temporary.read_bytes()) != prior['training_sha256']:
        raise ValueError('prior learned from different training inputs')
    output.mkdir(parents=True, exist_ok=False)
    (mean, scale, x), prep = timed(lambda: setup(a))
    rows = []
    with (output/'journal.jsonl').open('xb') as journal:
        for repeat in range(cfg['repeats']):
            arms = cfg['arms'][repeat:]+cfg['arms'][:repeat]
            for scenario in cfg['scenarios']:
                for arm in arms:
                    def emit(e):
                        journal.write(encode({'repeat': repeat, 'scenario': scenario['name'], 'arm': arm, **e})+b'\n')
                        journal.flush()
                        os.fsync(journal.fileno())
                    try:
                        row = lifecycle(a, x, prior, arm, scenario, emit)
                    except Exception as error:
                        emit({'kind': 'failure', 'error': type(error).__name__})
                        raise
                    row['repeat'] = repeat
                    rows.append(row)
                    write(output/f"{repeat}-{scenario['name']}-{arm}.json", row)
    seal = {'schema': 'hepta.merton.opportunity-seal.v1', 'posture': 'RESEARCH_ONLY_DENY_ALL',
            'protocol_sha256': PROTOCOL_SHA, 'source_sha256': source_hashes(),
            'prior_sha256': sha(prior_path.read_bytes()), 'worker_sha256': receipt['worker_sha256'],
            'journal_sha256': sha((output/'journal.jsonl').read_bytes()),
            'mean': mean.tolist(), 'scale': scale.tolist(), 'preparation': prep,
            'runtime': {'python': platform.python_version(), 'numpy': np.__version__},
            'fresh_encoder_calls': 0, 'heldout_labels_loaded': False, 'rows': rows}
    write(output/'sealed.json', seal)
    print(encode({'lifecycles': len(rows), 'online_updates': sum(r['actual_steps'] for r in rows)}).decode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('train-input', 'fit-prior', 'run'))
    for name in ('material', 'training', 'prior', 'output'):
        parser.add_argument('--'+name, type=Path)
    args = parser.parse_args()
    if args.phase == 'train-input':
        training_only(args.material, args.output)
    elif args.phase == 'fit-prior':
        fit_prior(args.training, args.output)
    else:
        run(args.material, args.prior, args.output)
