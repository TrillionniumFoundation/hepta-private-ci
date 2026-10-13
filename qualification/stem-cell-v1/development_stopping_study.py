"""Predeclared synthetic four-fold controller study; no pretrained/NDU efficacy claim.

Model training, critic fitting, policy calibration and heldout evaluation use
separate generated rows. Fixed-depth and confidence controls are selected on
calibration only, then independently EXECUTED on heldout inputs. All selection
trials are charged; unused work is not padded to pretend equal actual compute.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform

import torch

from development_ablation import (FoldIdentity, PhaseClock, RecurrentClassifier,
                                  fit_candidate, validate_folds)
from development_stopping import (TrainingTrace, collect_training_trace,
                                  fit_continuation, run_stopping)
from development_tensors import parameter_digest


SEEDS = (101, 202, 303)
COST = 0.02
HORIZON = 4


def write_once(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def tensor_sha(x):
    value = x.detach().contiguous().cpu()
    return hashlib.sha256(str((value.dtype, tuple(value.shape))).encode() + value.numpy().tobytes()).hexdigest()


def execute(model, x, config, critic):
    runs = [run_stopping(model, x[i:i+32], horizon=config['depth'], mode=config['mode'],
                         threshold=config.get('threshold', 0),
                         critic=critic if config['mode'] == 'learned' else None)
            for i in range(0, len(x), 32)]
    return {'logits': torch.cat([r['logits'] for r in runs]),
            'depths': torch.cat([r['depths'] for r in runs]),
            'cell_transitions': sum(r['cell_transitions'] for r in runs),
            'critic_rows': sum(r['critic_rows'] for r in runs),
            'cpu_ns': sum(r['cpu_ns'] for r in runs), 'wall_ns': sum(r['wall_ns'] for r in runs)}


def score(result, gold):
    correct = (result['logits'].argmax(-1) == gold).double()
    cost = result['depths'].double() * COST
    return {'accuracy': float(correct.mean()), 'mean_depth': float(result['depths'].double().mean()),
            'registered_utility': float((correct-cost).mean()),
            **{k: v for k, v in result.items() if k not in ('logits', 'depths')}}


def run_seed(seed, output):
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        clock = PhaseClock()
        data, folds = {}, {}
        for time, (name, size) in enumerate((('model_fit', 128), ('critic_fit', 96), ('calibration', 64), ('heldout', 64))):
            x = torch.randn(size, 5, 8)
            # Declared mixture, not selected after seeing test results.
            signal = torch.where(torch.arange(size) % 2 == 0, 1.5, .15)
            direction = torch.where(torch.rand(size) < .5, -1., 1.)
            x[:, :, 0] += (signal * direction)[:, None]
            y = (x[:, :, 0].sum(1) > 0).long()
            data[name] = x, y
            folds[name] = FoldIdentity('synthetic', tuple(f'{seed}-{name}-{i}' for i in range(size)), (time,)*size)
        names = tuple(folds)
        for i, first in enumerate(names):
            for second in names[i+1:]:
                validate_folds(folds[first], folds[second], len(data[first][0]), len(data[second][0]))
        configs = ([{'mode': 'fixed', 'depth': d} for d in (1, 2, 3, 4)] +
                   [{'mode': 'confidence', 'depth': 4, 'threshold': t} for t in (.5, .6, .7, .8, .9, 1.)] +
                   [{'mode': 'learned', 'depth': 4, 'threshold': t} for t in (-.05, 0., .05, .1)])
        write_once(output / f'plan-{seed}.json', {'seed': seed, 'configs': configs, 'unit_cost': COST,
                    'steps': 180, 'source_groups': {k: list(v.groups) for k,v in folds.items()},
                    'input_digests': {k: tensor_sha(v[0]) for k,v in data.items()},
                    'synthetic': True, 'calendar_future_windows': False})
        initial = RecurrentClassifier(8, 2, depth=HORIZON)
        model, training = fit_candidate(initial, *data['model_fit'], steps=180, seed=seed)
        x, y = data['critic_fit']
        traces = [collect_training_trace(model, x[i:i+32], horizon=HORIZON) for i in range(0, len(x), 32)]
        trace = TrainingTrace(torch.cat([t.states for t in traces]), torch.cat([t.logits for t in traces]),
                              parameter_digest(model), {key: sum(t.cost[key] for t in traces)
                              for key in ('cpu_ns', 'wall_ns', 'cell_transitions')})
        critic, fitting = fit_continuation(trace, y, unit_cost=COST)
        x, y = data['calibration']
        selection_clock = PhaseClock()
        candidates = []
        for index, config in enumerate(configs):
            result = execute(model, x, config, critic)
            candidates.append({'config': config, 'index': index, **score(result, y)})
        selected = {}
        for mode in ('fixed', 'confidence', 'learned'):
            admissible = [c for c in candidates if c['config']['mode'] == mode]
            selected[mode] = max(admissible, key=lambda c: (c['registered_utility'], -c['mean_depth'], -c['index']))['config']
        selection = {'selected': selected, 'candidates': candidates, **selection_clock.finish(),
                     'cell_transitions': sum(c['cell_transitions'] for c in candidates)}
        write_once(output / f'selection-{seed}.json', selection)
        identity = parameter_digest(model), critic.identity()
        # Gold is not given to any heldout executor. Freeze ALL predictions before scoring.
        x, gold = data['heldout']
        runs = {mode: execute(model, x, config, critic) for mode, config in selected.items()}
        runs['maximum_fixed'] = execute(model, x, {'mode':'fixed', 'depth':4}, critic)
        raw = {name: {**{k:v for k,v in r.items() if k not in ('logits', 'depths')},
                      'logits': r['logits'].tolist(), 'depths': r['depths'].tolist()}
               for name,r in runs.items()}
        write_once(output / f'predictions-{seed}.json', {'input_digest': tensor_sha(x), 'arms':raw})
        scores = {name: score(result, gold) for name,result in runs.items()}
        exact_clock = PhaseClock()
        exact = (x[:, :, 0].sum(1) > 0).long()
        exact_work = exact_clock.finish()
        scores['cheap_exact_rule'] = {'accuracy': float((exact == gold).double().mean()),
                                      **exact_work, 'registered_transition_units': None}
        if identity != (parameter_digest(model), critic.identity()):
            raise RuntimeError('model or policy changed during evaluation')
        report = {'seed':seed, 'model_fit':training, 'critic_fit':fitting, 'calibration':selection,
                  'heldout':scores, 'model_sha256':identity[0], 'critic_sha256':identity[1],
                  'total':clock.finish(), 'synthetic':True, 'production_authorized':False}
        write_once(output / f'report-{seed}.json', report)
        return report


def main(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    files = [Path(__file__).with_name(name) for name in ('development_stopping_study.py',
             'development_stopping.py', 'development_ablation.py', 'development_composition.py', 'development_tensors.py')]
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    write_once(output / 'source.json', {'sources':sources, 'seeds':SEEDS, 'torch':torch.__version__,
                                      'platform':platform.platform(), 'threads':1})
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        reports = [run_seed(seed, output) for seed in SEEDS]
        if sources != {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}:
            raise RuntimeError('source changed during study')
        write_once(output / 'summary.json', {'results':[{ 'seed':r['seed'], 'heldout':r['heldout'],
                    'selected':r['calibration']['selected']} for r in reports],
                    'pretrained_encoder_executed':False, 'statistical_superiority_established':False,
                    'general_ndu_fbsde_solver':False, 'production_authorized':False})
    except Exception as error:
        write_once(output / 'FAILED.json', {'type':type(error).__name__, 'message':str(error), 'sources':sources})
        raise
    finally:
        torch.set_num_threads(threads)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', required=True)
    parser.add_argument('--output', required=True)
    main(parser.parse_args().output)
