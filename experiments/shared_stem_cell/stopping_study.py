"""Real handwritten-image sequential reading with frozen stopping policies.

Four 2x8 image strips arrive in fixed spatial order, not real video timestamps.
Reuse the existing GRU Reader, train on one fold, fit critics on another, tune
cheap controls on a third, and score sealed actual executions on holdout last.
"""
import argparse
from importlib.resources import files
from pathlib import Path
import time

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell.controls import fit_recurrent_reader
from experiments.shared_stem_cell import stopping as s

SEEDS = (17, 29, 43)
CHARGES = (0.0, 0.02, 0.08)
STRIP_ORDER = (1, 2, 0, 3)


def cohort(pixels):
    """Only raw pixels determine folds. No labels, model scores or fitted features."""
    ids = [e.sha(row.to(torch.uint8).numpy().tobytes()) for row in pixels]
    def fold(identity):
        value = int(identity[:8], 16) % 12
        return 'holdout' if value < 2 else 'critic_fit' if value < 4 else 'tuning' if value == 4 else 'train'
    return ids, [fold(i) for i in ids]


def observations(pixels):
    if (pixels.ndim != 2 or pixels.shape[1] != 64 or pixels.dtype != torch.float32
            or pixels.device.type != 'cpu' or not bool(torch.isfinite(pixels).all())
            or bool(((pixels < 0) | (pixels > 16)).any())):
        raise e.InputError('actual 8x8 bounded digit pixels required')
    # 16 newly read pixels + four explicit spatial-location coordinates.
    strips = (pixels/16).reshape(-1, 4, 16)
    return torch.cat([strips[:, list(STRIP_ORDER)],
                      torch.eye(4)[list(STRIP_ORDER)].expand(len(pixels), -1, -1)], -1).contiguous()


def study(output, *, seeds=SEEDS, steps=240):
    import sklearn
    from sklearn.datasets import load_digits
    if (type(seeds) is not tuple or not seeds or len(set(seeds)) != len(seeds)
            or any(seed not in SEEDS for seed in seeds)):
        raise e.InputError('registered distinct seeds required')
    e.integer(steps, 1, 1000, 'stopping study steps')
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    try:
        data = load_digits()
        pixels = torch.tensor(data.data, dtype=torch.float32)
        ids, folds = cohort(pixels)
        rows = {name: [i for i, f in enumerate(folds) if f == name]
                for name in ('train', 'critic_fit', 'tuning', 'holdout')}
        if any(not r for r in rows.values()):
            raise e.InputError('four disjoint nonempty folds required')
        plan = {'source': 'bundled UCI digits; fixed pixel strips, not a pretrained Encoder',
            'dataset_sha256': e.sha(files('sklearn.datasets.data').joinpath('digits.csv.gz').read_bytes()),
            'cohort': list(zip(ids, folds)), 'fold_counts': {k: len(v) for k,v in rows.items()},
            'seed_grid': seeds, 'step_cost_grid': CHARGES, 'steps': steps, 'horizon': 4,
            'strip_order': STRIP_ORDER, 'features': '16 normalized pixels plus spatial one-hot; width20',
            'ridge': 0.1, 'terminal_and_backward_have_same_regression_size': True,
            'external_objective': 'correctness minus declared charge times all acquired Reader steps',
            'all_read_data_prepared_offline': True, 'writer_disjoint': False, 'future_window': False,
            'source_sha256': {name: e.sha((Path(__file__).parent/name).read_bytes()) for name in (
                'stopping_study.py', 'stopping.py', 'controls.py', 'execution.py', 'wire.py')},
            'sklearn': sklearn.__version__, 'torch': torch.__version__, 'threads': torch.get_num_threads()}
        e.write_once(output/'plan.json', plan)  # predeclare cohort and ALL resource prices
        x = observations(pixels)
        train_y = torch.tensor(data.target[rows['train']], dtype=torch.long)
        critic_y = torch.tensor(data.target[rows['critic_fit']], dtype=torch.long)
        tuning_y = torch.tensor(data.target[rows['tuning']], dtype=torch.long)
        pending = []
        for seed in seeds:
            with e.measured() as training:
                model, training_inner = fit_recurrent_reader(x[rows['train']], train_y,
                    classes=10, steps=steps, depth=4, seed=seed)
            critic_p, critic_trace_cost = s.read_trace(model, x[rows['critic_fit']])
            tuning_p, tuning_trace_cost = s.read_trace(model, x[rows['tuning']])
            policy_sets, preparation = [], []
            for charge in CHARGES:
                with e.measured() as preparation_cost:
                    rules, fitting = s.fit_rules(critic_p, critic_y, step_cost=charge)
                    fixed, confidence, tuning = s.tune_simple(tuning_p, tuning_y, step_cost=charge)
                    rules['confidence'] = confidence
                    for depth in range(1, 5):
                        rules[f'fixed_{depth}'] = s.StopRule('fixed', 4, 10, charge, limit=depth)
                policy_sets.append(rules)
                preparation.append({'step_cost': charge, 'critic_fit': fitting, 'tuning': tuning,
                    'preparation_cost': preparation_cost, 'selected_fixed': f'fixed_{fixed.limit}',
                    'rules': {k: rule.record() for k,rule in rules.items()}})
            policy_record = {'seed': seed, 'model': e.parameters(model), 'policies': preparation,
                'training': training, 'training_inner_not_additive': training_inner,
                'critic_trace': critic_trace_cost, 'tuning_trace': tuning_trace_cost}
            policy_seal = e.write_once(output/f'policies-{seed}.json', policy_record)
            runs = []
            for j, rules in enumerate(policy_sets):
                # All paths actually execute; do not time cached retrospective traces.
                keys = sorted(rules)
                offset = (SEEDS.index(seed)+j) % len(keys)
                results = {key: s.execute(model, x[rows['holdout']], rules[key])
                           for key in keys[offset:]+keys[:offset]}
                runs.append({'charge': CHARGES[j], 'results': results})
            seal = e.write_once(output/f'predictions-{seed}.json', {'runs': runs,
                'holdout_ids': [ids[i] for i in rows['holdout']], 'policy_sha256': policy_seal})
            pending.append((seed, seal, policy_seal))
        # No holdout target was accessed by training, policy fitting, selection or execution.
        targets = [int(data.target[i]) for i in rows['holdout']]
        summaries = []
        for seed, seal, policy_seal in pending:
            payload = e.decode(e.bound_file(output/f'predictions-{seed}.json', seal, 64*1024**2))
            policies = e.decode(e.bound_file(output/f'policies-{seed}.json', policy_seal))
            if payload['policy_sha256'] != policy_seal or payload['holdout_ids'] != [ids[i] for i in rows['holdout']]:
                raise e.InputError('sealed cohort or policy binding drift')
            for run, item in zip(payload['runs'], policies['policies'], strict=True):
                if set(run['results']) != set(item['rules']) or run['charge'] != item['step_cost']:
                    raise e.InputError('missing policy arm or changed charge')
                for arm, value in run['results'].items():
                    if value['rule'] != item['rules'][arm] or value['model'] != policies['model']:
                        raise e.InputError('different Reader or stopping policy')
                scores = {arm: s.score(value, targets) for arm,value in run['results'].items()}
                control = scores[item['selected_fixed']]
                summaries.append({'seed': seed, 'charge': run['charge'], 'scores': scores,
                    'calibration_selected_fixed': item['selected_fixed'],
                    'vs_selected_fixed': {a: {'accuracy_delta': v['accuracy']-control['accuracy'],
                        'utility_delta': v['net_utility']-control['net_utility'],
                        'transitions_saved': control['cell_transitions']-v['cell_transitions']} for a,v in scores.items()},
                    'prediction_sha256': seal, 'policy_sha256': policy_seal})
        report = {'runs': summaries, 'fold_counts': plan['fold_counts'],
            'whole_study_wall_ns': time.perf_counter_ns()-started, 'encoder_calls': 0,
            'pretrained_used': False, 'independent_evaluation': False, 'general_fbsde': False,
            'reasoning_gain_established': False, 'production_accepted': False,
            'cost_scope': 'one real inference per arm; preparation separately recorded; not stable latency tails',
            'seed_runs_are_not_independent_task_sets': True}
        e.write_once(output/'report.json', report)
        return report
    except Exception as error:
        e.write_once(output/'failure.json', {'error': type(error).__name__, 'message': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, choices=SEEDS)
    args = parser.parse_args()
    torch.set_num_threads(1)
    study(args.output, seeds=SEEDS if args.seed is None else (args.seed,))
