"""Frozen development comparison of light, old one-READ and multi-READ MPC."""
import argparse
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import platform
import sys
import time
import numpy as np
import scipy
import torch
from experiments.hcsn_v9_followup_20261101.mechanisms import campaign as v9
from . import mpc

ROOT = Path(__file__).resolve().parents[3]
V9 = ROOT/'experiments/hcsn_v9_followup_20261101/mechanisms/results/development001'


def prepare(dest):
    dest.mkdir(parents=True, exist_ok=False)
    sources = v9.sources()
    for path in (Path(__file__), Path(mpc.__file__), Path(v9.__file__)):
        sources[str(path.relative_to(ROOT))] = v9.sha(path)
    assets = {str(p.relative_to(ROOT)): v9.sha(p) for p in
              [V9/'SERVICE_FIT.json', V9/'ANALYTIC_FITS.json']}
    for path in sorted(v9.V8.glob('fit_*/*')):
        if path.name in ('models.pt', 'FIT.json'):
            assets[str(path.relative_to(ROOT))] = v9.sha(path)
    p = {'created_unix': time.time(), 'source_sha256': sources, 'assets_sha256': assets,
         'world_namespace': [20261101, 100839], 'policy_namespace': [20261101, 101990],
         'conditions': ['matched', 'hidden_refractory_mismatch'], 'worlds_per_condition': 6,
         'MPC_samples': 64, 'controllers': ['lightweight', 'old_one_read', 'multi_read_mpc'],
         'ordinary_families': ['gru', 'ssm'], 'ordinary_fits': [81101, 81103, 81107, 81109, 81113],
         'ordinary_primary': 'old count-validation NLL winner per fit; all SSM retained',
         'analytic': {'v9_fit_seed': '91103', 'mode': 'original'}, 'config': asdict(v9.old.Config()),
         'primary': 'MPC-light actual accuracy minus all READ fees; then same-controller D-B',
         'MPC_scope': 'all <=budget open-loop READ schedules, exact independent service mixture, 64 sampled conditional paths; replan every real tick',
         'not_exact_DP': True, 'future_information': 'model sampled paths only; never actual unread world',
         'service_failure_posterior': 'independent of latent path; failure retains prior observation and pays fee',
         'pending_requests': 'READ charged at request, arrives before next decision/output; one in flight; no decision with unresolved pending',
         'training_scope': 'frozen historical fits; unequal model priors/training; no strict architecture admission',
         'claim': 'finite known-model planning development; no real AV, network-service, optimality or economics adoption',
         'runtime': {'python': sys.version, 'numpy': np.__version__, 'scipy': scipy.__version__,
                     'torch': torch.__version__, 'platform': platform.platform(), 'threads': 1}}
    v9.write(dest/'PLAN.json', p)


def read_plan(dest):
    p = json.loads((dest/'PLAN.json').read_text())
    for section in ('source_sha256', 'assets_sha256'):
        for path, expected in p[section].items():
            if v9.sha(ROOT/path) != expected:
                raise ValueError('Frozen input changed: '+path)
    return p


def execute(core, controller, episode, config, forecast, policy_seeds, samples, forced=None):
    physics = v9.Physics(**episode['calibration']['estimated'])
    matrix = v9.old.transition_matrix(config.classes)
    obs = v9.old.Observation(0., episode['initial_x'], 0., [1/config.classes]*config.classes, False)
    budget, pending, stopped, reads = config.budget, None, False, 0
    traces, outputs, accesses = [], [], []
    started = time.process_time()
    for tick in range(config.ticks+1):
        if pending == tick:
            success = episode['service_uniform'][tick] < .9-.7*tick/20
            if success:
                obs = v9.old.Observation(tick*config.dt, episode['path']['x'][tick],
                    episode['path']['refractory_remaining'][tick],
                    np.eye(config.classes)[episode['path']['content'][tick]].tolist(), True)
            accesses.append({'arrival_tick': tick, 'success': success, 'fee': config.read_cost,
                             'observation': asdict(obs)})
            pending = None
        if tick in config.deadlines:
            probabilities, event = v9.old.predict(core, obs, tick*config.dt, physics, matrix)
            truth = episode['path']['content'][tick]
            outputs.append({'tick': tick, 'probabilities': probabilities.tolist(),
                            'truth_for_scoring_only': truth, 'correct': int(probabilities.argmax() == truth),
                            'observation': asdict(obs), **event})
        if stopped or tick == config.ticks:
            continue
        if forced is not None:
            action, detail = forced.get(tick, 'STOP'), {'fixed_schedule': True}
        elif controller == 'multi_read_mpc':
            action, detail = mpc.choose(core, obs, tick, budget, physics, matrix, config,
                                       policy_seeds[tick], forecast, samples)
        else:
            name = 'task_value' if controller == 'old_one_read' else 'lightweight'
            action, detail = v9.choose(core, name, obs, tick, budget, physics, matrix, config,
                                      policy_seeds[tick], forecast, True)
        if action == 'READ':
            if budget <= 0 or pending is not None:
                raise ValueError('Invalid pending/budget contract')
            budget -= 1
            reads += 1
            pending = tick+1
        if action == 'STOP':
            stopped = True
        traces.append({'tick': tick, 'action': action, 'budget_after': budget,
                       'observation': asdict(obs), 'detail': detail})
    accuracy = sum(v['correct'] for v in outputs)/len(config.deadlines)
    return {'summary': {'accuracy': accuracy, 'reads': reads, 'read_fees': reads*config.read_cost,
                        'net_reward': accuracy-reads*config.read_cost,
                        'cpu_seconds_nested': time.process_time()-started},
            'trace': traces, 'outputs': outputs, 'access': accesses}


def run(dest):
    p = read_plan(dest)
    forecast = json.loads((V9/'SERVICE_FIT.json').read_text())['forecast']
    fits = json.loads((V9/'ANALYTIC_FITS.json').read_text())
    scale = fits[p['analytic']['v9_fit_seed']]['original']['selected_scale']
    models, selected = {}, {}
    for seed in p['ordinary_fits']:
        folder = v9.V8/f'fit_{seed}'
        checkpoint = torch.load(folder/'models.pt', weights_only=False, map_location='cpu')
        selected[str(seed)] = json.loads((folder/'FIT.json').read_text())['selected_family']
        for family in p['ordinary_families']:
            models[(str(seed), family)] = v9.load_core(checkpoint, family)
    models[('91103', 'analytic')] = v9.FittedAnalytic('original', scale)
    v9.write(dest/'EVALUATION_FREEZE.json', {'plan_sha256': v9.sha(dest/'PLAN.json'),
        'old_ordinary_selections': selected, 'created_unix': time.time(), 'before_world_generation': True})
    count, fixed_count = 0, 0
    with gzip.open(dest/'worlds.jsonl.gz', 'xt') as worlds, gzip.open(dest/'runs.jsonl.gz', 'xt') as runs:
        for ci, condition in enumerate(p['conditions']):
            config = v9.old.Config(**{**p['config'], 'condition': condition})
            for wi in range(p['worlds_per_condition']):
                seed = int(np.random.SeedSequence(p['world_namespace']+[ci, wi]).generate_state(1)[0])
                episode = v9.old.make_episode(seed, config)
                episode['service_uniform'] = np.random.default_rng(np.random.SeedSequence([seed, 889])).random(21).tolist()
                ps = [int(np.random.SeedSequence(p['policy_namespace']+[ci, wi, t]).generate_state(1)[0]) for t in range(20)]
                worlds.write(json.dumps({'condition': condition, 'index': wi, 'episode': episode,
                                         'policy_seeds': ps})+'\n')
                for (fs, family), core in models.items():
                    for controller in p['controllers']:
                        record = execute(core, controller, episode, config, forecast, ps, p['MPC_samples'])
                        if controller == 'multi_read_mpc':
                            schedule = {v['tick']: v['action'] for v in record['trace']}
                            fixed = execute(core, 'lightweight', episode, config, forecast, ps, p['MPC_samples'], schedule)
                            for key in ('outputs', 'access'):
                                if record[key] != fixed[key]:
                                    raise ArithmeticError('Fixed action successor changed')
                            if record['summary']['net_reward'] != fixed['summary']['net_reward']:
                                raise ArithmeticError('Fixed reward changed')
                            record['fixed_action_replay'] = fixed
                            fixed_count += 1
                        runs.write(json.dumps({'condition': condition, 'index': wi, 'fit_seed': fs,
                            'family': family, 'controller': controller, **record}, allow_nan=False)+'\n')
                        count += 1
                runs.flush()
                print(json.dumps({'condition': condition, 'world': wi, 'runs': count}), flush=True)
    v9.write(dest/'COMPLETE.json', {'main_runs': count, 'fixed_action_runs': fixed_count,
        'worlds': 12, 'raw_sha256': v9.sha(dest/'runs.jsonl.gz'), 'worlds_sha256': v9.sha(dest/'worlds.jsonl.gz')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    {'prepare': prepare, 'run': run}[args.command](args.output)
