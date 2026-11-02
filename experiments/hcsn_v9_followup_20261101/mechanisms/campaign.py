"""Frozen finite renewal service-risk study; not persistent AV or neural HX training."""
import argparse
from dataclasses import asdict, replace
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from experiments.hcsn_mechanism_content_v2 import mechanism as old
from experiments.hcsn_mechanism_content_v2.renewal import Physics, propagation_dataset, renewal_counts
from experiments.hcsn_v8_execution_20261101.mechanisms.count_interventions import transform_counts
from experiments.hcsn_v8_execution_20261101.mechanisms.recurrent_counts import load_core

ROOT = Path(__file__).resolve().parents[3]
V8 = ROOT / 'experiments/hcsn_v8_execution_20261101/mechanisms/results/development001'
MODES = ('original', 'mean_two_point', 'single_transition')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def sources():
    paths = [Path(__file__), ROOT / 'experiments/hcsn_mechanism_content_v2/mechanism.py',
             ROOT / 'experiments/hcsn_mechanism_content_v2/renewal.py',
             ROOT / 'experiments/hcsn_v8_execution_20261101/mechanisms/count_interventions.py',
             ROOT / 'experiments/hcsn_v8_execution_20261101/mechanisms/recurrent_counts.py']
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def prepare(dest):
    dest.mkdir(parents=True, exist_ok=False)
    checkpoints = {str(p.relative_to(ROOT)): sha(p) for p in sorted(V8.glob('fit_*/models.pt'))}
    checkpoints.update({str(p.relative_to(ROOT)): sha(p) for p in sorted(V8.glob('fit_*/FIT.json'))})
    plan = {'created_unix': time.time(), 'source_sha256': sources(), 'historical_assets': checkpoints,
            'fit_seeds': [91103, 91107, 91113], 'world_namespace': [20261101, 93819],
            'conditions': ['matched', 'hidden_refractory_mismatch'], 'worlds_per_condition': 12,
            'train_size': 512, 'validation_size': 128, 'drift_grid': np.linspace(.5, 1.5, 21).tolist(),
            'modes': MODES, 'service_calibration_seed': 918341, 'service_trials_per_tick': 256,
            'service_success_rule': '0.9 - 0.7 * arrival_tick/20',
            'service_randomness': 'one public-law private uniform per world and arrival; common across arms',
            'risk_intervention': 'forecast success set to one only; actual failures, fees and worlds unchanged',
            'analytic_fit': 'per shape and seed, drift multiplier minimizes sampled-count NLL on new train only',
            'nll_floor': 1e-12, 'ordinary': 'unchanged v8 five fits; both GRU/SSM retained; old validation selection',
            'primary': 'D-B net reward at same risk forecast; paired world-cluster descriptive interval',
            'scope': 'new finite synthetic service task; historical ordinary fits; not AV admission or neural analytic retraining',
            'config': asdict(old.Config()), 'real_AV_confirmation': False, 'architecture_acceptance': False}
    write(dest / 'PLAN.json', plan)


def plan(dest):
    value = json.loads((dest / 'PLAN.json').read_text())
    if sources() != value['source_sha256']:
        raise ValueError('Sources changed after freeze')
    for path, expected in value['historical_assets'].items():
        if sha(ROOT / path) != expected:
            raise ValueError('Historical model or selection changed')
    return value


class FittedAnalytic:
    def __init__(self, mode, scale):
        self.mode, self.scale = mode, scale
        self.calls = self.work = self.cdf_terms = 0

    def counts(self, x, horizon, physics, remaining=0):
        p, work = renewal_counts(x, horizon, replace(physics, nu=physics.nu*self.scale), remaining)
        self.calls += 1
        self.cdf_terms += work['cdf_terms']
        return transform_counts(p, self.mode)


def fit(dest):
    p = plan(dest)
    rng = np.random.default_rng(p['service_calibration_seed'])
    success = [.9 - .7*t/20 for t in range(21)]
    raw = rng.random((21, p['service_trials_per_tick']))
    events = raw < np.array(success)[:, None]
    write(dest / 'SERVICE_FIT.json', {'success_count': events.sum(1).tolist(), 'trials': 256,
                                    'forecast': events.mean(1).tolist(), 'law': success})
    np.savez_compressed(dest / 'service_samples.npz', uniform=raw, success=events)
    report = {}
    for seed in p['fit_seeds']:
        tx, ty, truth, _ = propagation_dataset(seed, p['train_size'])
        vx, vy, vtruth, _ = propagation_dataset(seed+31933, p['validation_size'])
        np.savez_compressed(dest / f'samples_{seed}.npz', train_x=tx, train_y=ty, truth=truth,
                            validation_x=vx, validation_y=vy, validation_truth=vtruth)
        report[str(seed)] = {}
        for mode in p['modes']:
            def nll(data, labels, scale):
                core = FittedAnalytic(mode, scale)
                return float(np.mean([-np.log(max(core.counts(float(row[0]), float(row[1]),
                    Physics(*map(float, row[2:6])), float(row[6]))[int(y)], p['nll_floor']))
                    for row, y in zip(data, labels)]))
            candidates = [{'drift_scale': s, 'train_nll': nll(tx, ty, s)} for s in p['drift_grid']]
            winner = min(candidates, key=lambda row: (row['train_nll'], row['drift_scale']))
            report[str(seed)][mode] = {'selected_scale': winner['drift_scale'], 'candidates': candidates,
                                      'validation_nll': nll(vx, vy, winner['drift_scale'])}
        print(json.dumps({'fit_seed': seed, 'complete': True}), flush=True)
    write(dest / 'ANALYTIC_FITS.json', report)


def choose(core, controller, obs, tick, budget, physics, matrix, config, seed, forecast, risk):
    action, detail = old.choose_action(core, controller, obs, tick, budget, physics, matrix, config, seed)
    if not risk or 'reason' in detail:
        return action, detail
    if controller == 'lightweight':
        error = detail['forecast_error'] * forecast[tick+1]
        future = [d for d in config.deadlines if d > tick]
        action = 'READ' if error > config.light_threshold and future[0]-tick <= 2 else 'WAIT'
        return action, {**detail, 'risk_adjusted_error': error}
    values = [{**v, 'success_forecast': forecast[v['arrival_tick']],
               'net_value': forecast[v['arrival_tick']]*(v['net_value']+config.read_cost)-config.read_cost}
              for v in detail['candidate_values']]
    best = max(values, key=lambda v: (v['net_value'], -v['arrival_tick']))
    action = 'STOP' if best['net_value'] <= 0 else ('READ' if best['arrival_tick'] == tick+1 else 'WAIT')
    return action, {'candidate_values': values, 'selected_arrival': best['arrival_tick']}


def rollout(core, controller, episode, config, forecast, risk=True, forced=None):
    physics = Physics(**episode['calibration']['estimated'])
    matrix, path = old.transition_matrix(config.classes), episode['path']
    obs = old.Observation(0., episode['initial_x'], 0., [1/config.classes]*config.classes, False)
    budget, pending, stopped, reads = config.budget, None, False, 0
    trace, predictions, access = [], [], []
    started = time.process_time()
    core.calls = core.work = core.cdf_terms = 0
    for tick in range(config.ticks+1):
        if pending == tick:
            success = episode['service_uniform'][tick] < .9 - .7*tick/20
            if success:
                obs = old.Observation(tick*config.dt, path['x'][tick], path['refractory_remaining'][tick],
                                      np.eye(config.classes)[path['content'][tick]].tolist(), True)
            access.append({'arrival_tick': tick, 'success': success, 'fee_charged': config.read_cost,
                           'observed_state_after': asdict(obs)})
            pending = None
        if tick in config.deadlines:
            probs, event = old.predict(core, obs, tick*config.dt, physics, matrix)
            truth = path['content'][tick]
            predictions.append({'tick': tick, 'probabilities': probs.tolist(), 'truth_for_scoring_only': truth,
                                'correct': int(probs.argmax() == truth), 'observed_state': asdict(obs), **event})
        if tick == config.ticks or stopped:
            continue
        seed = int(np.random.SeedSequence([episode['seed'], tick, 4337]).generate_state(1)[0])
        if forced is None:
            action, detail = choose(core, controller, obs, tick, budget, physics, matrix, config, seed, forecast, risk)
        else:
            action, detail = forced.get(tick, 'STOP'), {'fixed_schedule': True}
        if action == 'READ' and (budget <= 0 or pending is not None):
            raise ValueError('Invalid READ schedule')
        if action == 'READ':
            budget -= 1
            reads += 1
            pending = tick+1
        if action == 'STOP':
            stopped = True
        trace.append({'tick': tick, 'action': action, 'detail': detail, 'observation': asdict(obs)})
    accuracy = float(np.mean([v['correct'] for v in predictions]))
    return {'summary': {'accuracy': accuracy, 'reads': reads, 'read_fees': reads*config.read_cost,
                        'net_reward': accuracy-reads*config.read_cost,
                        'cpu_seconds_nested': time.process_time()-started},
            'trace': trace, 'predictions': predictions, 'access': access}


def evaluate(dest):
    p = plan(dest)
    fits = json.loads((dest / 'ANALYTIC_FITS.json').read_text())
    forecast = json.loads((dest / 'SERVICE_FIT.json').read_text())['forecast']
    models, selections = {}, {}
    for folder in sorted(V8.glob('fit_*')):
        checkpoint = torch.load(folder / 'models.pt', weights_only=False, map_location='cpu')
        models[folder.name] = {f: load_core(checkpoint, f) for f in ('gru', 'ssm')}
        selections[folder.name] = json.loads((folder / 'FIT.json').read_text())['selected_family']
    write(dest / 'EVALUATION_FREEZE.json', {'plan_sha256': sha(dest/'PLAN.json'),
          'fit_sha256': sha(dest/'ANALYTIC_FITS.json'), 'service_sha256': sha(dest/'SERVICE_FIT.json'),
          'ordinary_selections': selections, 'before_new_world_generation': True, 'created_unix': time.time()})
    with gzip.open(dest/'worlds.jsonl.gz', 'xt') as worlds, gzip.open(dest/'runs.jsonl.gz', 'xt') as runs:
        count = 0
        for ci, condition in enumerate(p['conditions']):
            config = old.Config(**{**p['config'], 'condition': condition})
            for wi in range(p['worlds_per_condition']):
                seed = int(np.random.SeedSequence(p['world_namespace']+[ci, wi]).generate_state(1)[0])
                episode = old.make_episode(seed, config)
                episode['service_uniform'] = np.random.default_rng(np.random.SeedSequence([seed, 719])).random(21).tolist()
                worlds.write(json.dumps({'condition': condition, 'index': wi, 'episode': episode})+'\n')
                def emit(core, controller, family, fit_seed, mode, risk, forced=None):
                    nonlocal count
                    result = rollout(core, controller, episode, config, forecast, risk, forced)
                    runs.write(json.dumps({'condition': condition, 'index': wi, 'family': family,
                        'fit_seed': str(fit_seed), 'mode': mode, 'controller': controller, 'risk': risk,
                        'fixed': forced is not None, **result}, allow_nan=False)+'\n')
                    count += 1
                    return result
                for fs, fit in fits.items():
                    reference = None
                    for mode in p['modes']:
                        scale = fit[mode]['selected_scale']
                        for controller in ('lightweight', 'task_value'):
                            for risk in (True, False):
                                result = emit(FittedAnalytic(mode, scale), controller, 'analytic', fs, mode, risk)
                                if mode == 'original' and controller == 'task_value' and risk:
                                    reference = {r['tick']: r['action'] for r in result['trace']}
                        emit(FittedAnalytic(mode, scale), 'task_value', 'analytic', fs, mode, True, reference)
                for fs, families in models.items():
                    for family, core in families.items():
                        for controller in ('lightweight', 'task_value'):
                            for risk in (True, False):
                                emit(core, controller, family, fs, 'original', risk)
                runs.flush()
                print(json.dumps({'condition': condition, 'world': wi, 'runs': count}), flush=True)
    write(dest/'COMPLETE.json', {'runs': count, 'worlds': 24, 'raw_sha256': sha(dest/'runs.jsonl.gz'),
                               'worlds_sha256': sha(dest/'worlds.jsonl.gz')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'fit', 'evaluate'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    {'prepare': prepare, 'fit': fit, 'evaluate': evaluate}[args.command](args.output)


if __name__ == '__main__':
    main()
