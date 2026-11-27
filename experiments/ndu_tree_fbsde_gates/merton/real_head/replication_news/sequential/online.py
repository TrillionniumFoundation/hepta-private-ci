"""Actually stop SGD before the next block, with source-bound attempt journals."""
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
from material_news import encode, loads, packet, sha, write
from trial_news import design, probabilities, block_counts
from control import decision, select

PROTOCOL_SHA = 'f312ed72af7cf29224b98846b17d6ac089248f2dcb8d43cb502aab54648fd105'
FILES = ('protocol.json', 'control.py', 'online.py', 'audit_online.py', 'test_online.py', 'README.md')
PARENT_FILES = ('protocol.json', 'material_news.py', 'trial_news.py', 'audit_news.py')


def config():
    raw = (HERE/'protocol.json').read_bytes()
    if sha(raw) != PROTOCOL_SHA:
        raise ValueError('protocol drift')
    return loads(raw)


def source_hashes():
    return {name: sha((HERE/name).read_bytes()) for name in FILES} | {
        '../'+name: sha((HERE.parent/name).read_bytes()) for name in PARENT_FILES}


def profile(arm):
    if arm == 'sequential_neutral':
        return 'neutral'
    if arm == 'sequential_fixed':
        return 'fixed'
    if arm in ('full_search', 'sequential_ndu', 'reference_rule'):
        return 'ndu'
    raise ValueError('arm has no valuation profile')


def reference_rule(history, scenario, p):
    # Independent ordinary rule lives in the reviewer, not an alternative trainer.
    from audit_online import reference_decision
    return reference_decision(history, scenario, p)


class Trainer:
    """One physical zero-initialized Head per lifecycle; no cross-arm weight cache."""
    def __init__(self, x, y, budget):
        if x.shape != (64, 385) or y.shape != (64,) or not np.isfinite(x).all():
            raise ValueError('invalid training shape')
        if y.dtype.kind not in 'iu' or np.any((y < 0) | (y > 3)):
            raise ValueError('invalid training label')
        if type(budget) is not int or not 0 <= budget <= 128:
            raise ValueError('invalid endowment')
        self.x, self.y, self.budget = x, y, budget
        self.weights = np.zeros((385, 4), dtype=np.float64)
        self.updates = 0
        self.losses = []

    def step(self):
        if self.updates >= self.budget:
            raise ValueError('hard optimizer budget exhausted')
        p = probabilities(self.x, self.weights)
        self.losses.append(float(-np.log(p[np.arange(64), self.y]).mean() +
                                 .0005*np.sum(self.weights[:-1]**2)))
        p[np.arange(64), self.y] -= 1
        gradient = self.x.T @ p / 64
        gradient[:-1] += .001*self.weights[:-1]
        self.weights -= .1*gradient
        self.updates += 1
        if not np.isfinite(self.weights).all():
            raise ValueError('nonfinite update')

    def advance(self, target):
        if type(target) is not int or target not in (8, 32, 128) or not self.updates < target <= self.budget:
            raise ValueError('invalid or unaffordable advance')
        while self.updates < target:
            self.step()


def timed(fn):
    c, w = time.process_time_ns(), time.perf_counter_ns()
    value = fn()
    return value, {'cpu_ns': time.process_time_ns()-c, 'wall_ns': time.perf_counter_ns()-w}


def lifecycle(a, x, arm, scenario, emit):
    cfg = config()
    if arm not in cfg['arms'] or scenario not in cfg['scenarios']:
        raise ValueError('unregistered arm or scenario')
    c0, w0 = time.process_time_ns(), time.perf_counter_ns()
    trainer = Trainer(x['train'], a['y_train'], scenario['budget'])
    history, checkpoints, phases = [], {}, []
    order = np.argsort(a['cal_hashes'], kind='stable')
    events = []

    def log(row):
        events.append(row)
        emit(row)

    def calibrate():
        counts, timing = timed(lambda: block_counts(
            probabilities(x['cal'], trainer.weights).argmax(axis=1), a['y_cal'], order))
        phases.append({'kind': 'calibration', **timing})
        row = {'step': trainer.updates, 'counts': counts}
        history.append(row)
        checkpoints[str(trainer.updates)] = trainer.weights.copy().tolist()
        log({'kind': 'observation', **row})

    def train(target):
        before = trainer.updates
        log({'kind': 'train_start', 'from_step': before, 'to_step': target})
        _, timing = timed(lambda: trainer.advance(target))
        phases.append({'kind': 'fit', **timing})
        log({'kind': 'train_done', 'from_step': before, 'to_step': target,
             'weights_sha256': sha(encode(trainer.weights.tolist()))})

    log({'kind': 'start'})
    if arm in ('no_update', 'fixed8', 'fixed32'):
        target = 0 if arm == 'no_update' else int(arm[5:])
        if target > scenario['budget']:
            target = 0
        log({'kind': 'fixed_admission', 'target': target})
        if target:
            train(target)
        selected = target
        checkpoints[str(target)] = trainer.weights.tolist()
    else:
        calibrate()
        while True:
            if arm == 'full_search':
                target = next((v for v in (8, 32, 128) if v > trainer.updates), None)
                take = target is not None and target <= scenario['budget']
                command = {'action': 'continue' if take else 'stop', 'from_step': trainer.updates,
                           'to_step': target if take else None, 'reason': 'fixed_search_schedule'}
            else:
                choose = reference_rule if arm == 'reference_rule' else decision
                command, timing = timed(lambda: choose(history, scenario, profile(arm)))
                phases.append({'kind': 'decision', **timing})
            log({'kind': 'decision', 'observed_steps': [h['step'] for h in history], **command})
            if command['action'] == 'stop':
                break
            train(command['to_step'])
            calibrate()
        selected, timing = timed(lambda: select(history, scenario, profile(arm)))
        phases.append({'kind': 'selection', **timing})
    final = np.array(checkpoints[str(selected)], dtype=np.float64)
    predicted, timing = timed(lambda: probabilities(x['holdout'], final))
    phases.append({'kind': 'prediction', **timing})
    log({'kind': 'success', 'actual_steps': trainer.updates, 'selected_steps': selected})
    return {'arm': arm, 'scenario': scenario['name'], 'actual_steps': trainer.updates,
            'selected_steps': selected, 'calibration_calls': len(history), 'history': history,
            'checkpoints': checkpoints, 'weights': final.tolist(), 'losses': trainer.losses,
            'holdout_ids': a['holdout_ids'].tolist(), 'probabilities': predicted.tolist(),
            'events': events, 'phases': phases, 'cpu_ns': time.process_time_ns()-c0,
            'wall_ns': time.perf_counter_ns()-w0}


def setup(a):
    mean = a['x_train'].astype(np.float64).mean(axis=0)
    scale = np.maximum(np.sqrt(np.mean((a['x_train'].astype(np.float64)-mean)**2, axis=0)), 1e-6)
    return mean, scale, {part: design(a['x_'+part], mean, scale) for part in ('train', 'cal', 'holdout')}


def run(material, output):
    cfg = config()
    a, receipt = packet(material/'worker.npz')
    output.mkdir(parents=True, exist_ok=False)
    write(output/'protocol.json', cfg)
    (mean, scale, x), preparation = timed(lambda: setup(a))
    records = []
    with (output/'attempts.jsonl').open('xb') as journal:
        for repeat in range(cfg['repeats']):
            arms = cfg['arms'][repeat:] + cfg['arms'][:repeat]
            for scenario in cfg['scenarios']:
                for arm in arms:
                    def emit(event):
                        journal.write(encode({'repeat': repeat, 'scenario': scenario['name'], 'arm': arm, **event})+b'\n')
                        journal.flush()
                        os.fsync(journal.fileno())
                    try:
                        row = lifecycle(a, x, arm, scenario, emit)
                    except Exception as exc:
                        emit({'kind': 'failure', 'error': type(exc).__name__})
                        raise
                    row['repeat'] = repeat
                    write(output/f"{repeat}-{scenario['name']}-{arm}.json", row)
                    records.append(row)
    seal = {'schema': 'hepta.merton.sequential-seal.v1', 'posture': 'RESEARCH_ONLY_DENY_ALL',
            'protocol_sha256': PROTOCOL_SHA, 'worker_sha256': receipt['worker_sha256'],
            'source_sha256': source_hashes(), 'journal_sha256': sha((output/'attempts.jsonl').read_bytes()),
            'mean': mean.tolist(), 'scale': scale.tolist(), 'preparation': preparation,
            'runtime': {'python': platform.python_version(), 'numpy': np.__version__, 'platform': platform.platform()},
            'fresh_encoder_calls': 0, 'heldout_labels_loaded': False, 'rows': records}
    write(output/'sealed.json', seal)
    print(encode({'rows': len(records), 'actual_updates': sum(r['actual_steps'] for r in records)}).decode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--material', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.material, args.output)
