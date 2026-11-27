"""Physical per-Head training under shared policies versus per-request solvers."""
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
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent.parent/'sequential'))
from belief import BATCHES, Planner
from material_news import encode, loads, packet, sha, write
from online import Trainer, setup, timed
from study import config as parent_config, fit_prior, training_only
from trial_news import probabilities
from compile_policy import SharedPolicy, build, compact, sources


def config():
    return loads((HERE/'protocol.json').read_bytes())


def lifecycle(a, x, prior, asset, arm, scenario, emit):
    if arm not in config()['arms'] or scenario not in parent_config()['scenarios']:
        raise ValueError('unregistered physical experiment')
    c0, w0 = time.process_time_ns(), time.perf_counter_ns()
    trainer = Trainer(x['train'], a['y_train'], scenario['budget'])
    planner = Planner(prior['curves'], scenario, arm[6:]) if arm.startswith('solve_') else None
    lookup = asset.bind(asset.scope_digest, scenario, arm[7:]) if arm.startswith('shared_') else None
    events, phases, history, consumed = [], [], [], []
    checkpoints = {0: trainer.weights.copy()}
    order = np.argsort(a['cal_hashes'], kind='stable')

    def event(e):
        events.append(e); emit(e)

    event({'kind': 'start'})
    while True:
        if planner is not None or lookup is not None:
            fn = (lambda: compact(planner.decision(history))) if planner else (lambda: lookup.decision(history, trainer.updates))
            command, clock = timed(fn)
            phases.append({'kind': 'decision', **clock})
        else:
            target = 0 if arm == 'no_update' else int(arm[5:])
            take = trainer.updates < target <= scenario['budget']
            command = {'action': 'continue' if take else 'stop', 'to_step': target if take else None,
                       'selected_steps': trainer.updates, 'reason': 'fixed_schedule'}
        event({'kind': 'decision', 'history': list(history), 'actual_steps': trainer.updates, **command})
        if command['action'] == 'stop':
            selected = command['selected_steps']; break
        target = command['to_step']
        event({'kind': 'train_start', 'from_step': trainer.updates, 'to_step': target})
        _, clock = timed(lambda: trainer.advance(target))
        phases.append({'kind': 'fit', **clock})
        checkpoints[target] = trainer.weights.copy()
        event({'kind': 'train_done', 'actual_steps': target, 'weights_sha256': sha(encode(trainer.weights.tolist()))})
        if planner is None and lookup is None:
            continue
        n = BATCHES[len(history)]; start = sum(BATCHES[:len(history)])
        indices = order[start:start+n]
        correct, clock = timed(lambda: int(np.sum(probabilities(x['cal'][indices], trainer.weights).argmax(axis=1) == a['y_cal'][indices])))
        phases.append({'kind': 'calibration', **clock})
        ids = a['cal_ids'][indices].tolist(); consumed.extend(ids); history.append(correct)
        event({'kind': 'observation', 'step': target, 'count': correct, 'size': n, 'ids': ids})
    if selected not in checkpoints:
        raise ValueError('unexecuted checkpoint')
    probs, clock = timed(lambda: probabilities(x['holdout'], checkpoints[selected]))
    phases.append({'kind': 'prediction', **clock})
    event({'kind': 'success', 'actual_steps': trainer.updates, 'selected_steps': selected})
    return {'arm': arm, 'scenario': scenario['name'], 'history': history, 'actual_steps': trainer.updates,
            'selected_steps': selected, 'calibration_calls': len(history), 'calibration_ids': consumed,
            'weights': checkpoints[selected].tolist(), 'checkpoints': {str(k): v.tolist() for k, v in checkpoints.items()},
            'losses': trainer.losses, 'probabilities': probs.tolist(), 'holdout_ids': a['holdout_ids'].tolist(),
            'events': events, 'phases': phases, 'solver_constructions': int(planner is not None),
            'online_model_nodes': planner.solve.cache_info().currsize if planner else 0,
            'cpu_ns': time.process_time_ns()-c0, 'wall_ns': time.perf_counter_ns()-w0}


def run(material, output):
    output.mkdir(parents=True, exist_ok=False)
    a, receipt = packet(material/'worker.npz')
    t0 = time.process_time_ns(); w0 = time.perf_counter_ns()
    training_only(material, output/'train.npz')
    prior = fit_prior(output/'train.npz', output/'prior.json')
    compilation = build(output/'prior.json', receipt['worker_sha256'], output/'policy.json')
    asset, load_clock = timed(lambda: SharedPolicy(output/'policy.json', compilation['asset_sha256'],
                                receipt['worker_sha256'], sha((output/'prior.json').read_bytes())))
    (mean, scale, x), prep = timed(lambda: setup(a))
    rows = []
    with (output/'journal.jsonl').open('xb') as journal:
        for repeat in range(config()['repeats']):
            arms = config()['arms'][repeat:]+config()['arms'][:repeat]
            for scenario in parent_config()['scenarios']:
                for arm in arms:
                    def emit(e):
                        journal.write(encode({'repeat': repeat, 'scenario': scenario['name'], 'arm': arm, **e})+b'\n')
                        journal.flush(); os.fsync(journal.fileno())
                    try:
                        row = lifecycle(a, x, prior, asset, arm, scenario, emit)
                    except Exception as e:
                        emit({'kind': 'failure', 'error': type(e).__name__}); raise
                    row['repeat'] = repeat; rows.append(row)
                    write(output/f'{repeat}-{scenario["name"]}-{arm}.json', row)
    seal = {'schema': 'hepta.merton.shared-benchmark.v1', 'posture': 'RESEARCH_ONLY_DENY_ALL',
            'source_sha256': sources(), 'protocol_sha256': sha((HERE/'protocol.json').read_bytes()),
            'worker_sha256': receipt['worker_sha256'], 'prior_sha256': sha((output/'prior.json').read_bytes()),
            'compilation': compilation, 'loading': load_clock, 'preparation': prep,
            'journal_sha256': sha((output/'journal.jsonl').read_bytes()), 'mean': mean.tolist(), 'scale': scale.tolist(),
            'shared_table_owners': 1, 'prior_fits_physically_executed': 1, 'prior_updates': 512,
            'actual_online_updates': sum(r['actual_steps'] for r in rows),
            'fresh_encoder_calls': 0, 'heldout_labels_loaded': False, 'new_sources': 0,
            'command_cpu_ns': time.process_time_ns()-t0, 'command_wall_ns': time.perf_counter_ns()-w0,
            'runtime': {'python': platform.python_version(), 'numpy': np.__version__}, 'rows': rows}
    write(output/'sealed.json', seal)
    print(encode({'lifecycles': len(rows), 'online_updates': seal['actual_online_updates'],
                  'compiled_decisions': compilation['stored_decisions'], 'policy_bytes': compilation['serialized_bytes']}).decode())
    return seal


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--material', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); run(a.material, a.output)
