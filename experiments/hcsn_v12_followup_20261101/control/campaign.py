"""Frozen two-pool feedback-control development; light remains default fallback."""
import argparse
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import sys
import time
import numpy as np
import scipy
import torch
from experiments.hcsn_v10_followup_20261101.control import campaign as prior
from . import feedback_rollout as feedback

ROOT, V9 = prior.ROOT, prior.V9


def prepare(dest):
    dest.mkdir(parents=True, exist_ok=False)
    sources = prior.v9.sources()
    for path in (Path(__file__), Path(feedback.__file__), Path(prior.__file__),
                 Path(prior.mpc.__file__), Path(prior.v9.__file__)):
        sources[str(path.relative_to(ROOT))] = prior.v9.sha(path)
    assets = {str(p.relative_to(ROOT)): prior.v9.sha(p) for p in
              [V9/'SERVICE_FIT.json', V9/'ANALYTIC_FITS.json']}
    for path in sorted(prior.v9.V8.glob('fit_*/*')):
        if path.name in ('models.pt', 'FIT.json'):
            assets[str(path.relative_to(ROOT))] = prior.v9.sha(path)
    p = {'created_unix': time.time(), 'source_sha256': sources, 'assets_sha256': assets,
         'world_namespace': [20261101, 120839], 'policy_namespace': [20261101, 121990],
         'conditions': ['matched', 'hidden_refractory_mismatch'], 'worlds_per_condition': 6,
         'selection_pool_size': 512, 'validation_pool_size': 512,
         'ordinary_fits': [81101, 81103, 81107, 81109, 81113], 'ordinary_families': ['gru', 'ssm'],
         'analytic_fit_seed': '91103', 'config': asdict(prior.v9.old.Config()),
         'controllers': ['lightweight', 'feedback_rollout'], 'delta_campaign_model_only': .05,
         'maximum_validation_tests': 12*11*20, 'alpha_per_test': .05/(12*11*20),
         'gate': 'single-sided Hoeffding LCB=mean_units/100-K*sqrt(2*log(1/alpha)/512)>0',
         'K': 'remaining_mandatory_outputs/4 + remaining_READ_budget*0.04',
         'selection': 'root actions baseline-light first then STOP/WAIT/READ; ties prefer light then listed order',
         'feedback_tail': 'after root action execute light with branch-specific actual simulated service/observation/budget',
         'validation': 'only fixed selected non-light root vs fixed light root; fresh independent pool; no reselection or early stop',
         'service_model': 'frozen empirical q; actual execution uses original true declared service law',
         'primary': 'actual feedback-light world-paired reward; same-control D-B secondary',
         'reward': 'correct_count/4-READ_count/25; simulated reward_units=25*correct-4*READ',
         'strong_model_prior': 'shared estimated renewal sampler, not a learned ordinary controller or actual-world oracle',
         'limits': ['historical fits and unequal training priors', 'model-only confidence not true-task guarantee',
                    'finite worlds and fixed physical calibration', 'no AV admission or full economics'],
         'runtime': {'python': sys.version, 'numpy': np.__version__, 'scipy': scipy.__version__,
                     'torch': torch.__version__, 'threads': 1}}
    pool_seeds = [int(np.random.SeedSequence(p['policy_namespace']+[ci, wi, t, pool]).generate_state(1)[0])
                  for ci in range(2) for wi in range(6) for t in range(20) for pool in (0, 1)]
    if len(set(pool_seeds)) != len(pool_seeds):
        raise ValueError('Model pool seed namespace collision')
    p['distinct_pool_namespace_seeds'] = len(pool_seeds)
    prior.v9.write(dest/'PLAN.json', p)


def read_plan(dest):
    p = json.loads((dest/'PLAN.json').read_text())
    for section in ('source_sha256', 'assets_sha256'):
        for path, expected in p[section].items():
            if prior.v9.sha(ROOT/path) != expected:
                raise ValueError('Frozen input changed: '+path)
    return p


def execute(core, controller, episode, config, q, seeds, size, alpha, forced=None):
    physics = prior.v9.Physics(**episode['calibration']['estimated'])
    matrix = prior.v9.old.transition_matrix(config.classes)
    obs = prior.v9.old.Observation(0., episode['initial_x'], 0., [1/config.classes]*config.classes, False)
    budget, pending, stopped, reads = config.budget, None, False, 0
    traces, outputs, access = [], [], []
    began = time.process_time()
    for tick in range(config.ticks+1):
        if pending == tick:
            success = episode['service_uniform'][tick] < .9-.7*tick/20
            if success:
                obs = prior.v9.old.Observation(tick*config.dt, episode['path']['x'][tick],
                    episode['path']['refractory_remaining'][tick],
                    np.eye(config.classes)[episode['path']['content'][tick]].tolist(), True)
            access.append({'arrival_tick': tick, 'success': success, 'fee': config.read_cost,
                           'observation': asdict(obs)})
            pending = None
        if tick in config.deadlines:
            probs, event = prior.v9.old.predict(core, obs, tick*config.dt, physics, matrix)
            truth = episode['path']['content'][tick]
            outputs.append({'tick': tick, 'probabilities': probs.tolist(), 'truth_for_scoring_only': truth,
                            'correct': int(probs.argmax() == truth), 'observation': asdict(obs), **event})
        if stopped or tick == config.ticks:
            continue
        if forced is not None:
            action, detail = forced.get(tick, 'STOP'), {'fixed_schedule': True}
        elif controller == 'lightweight':
            action, detail = prior.v9.choose(core, controller, obs, tick, budget, physics, matrix,
                                            config, seeds[tick][0], q, True)
        else:
            action, detail = feedback.choose(core, obs, tick, budget, physics, matrix, config,
                                             seeds[tick], q, size, alpha)
        if action == 'READ':
            if budget <= 0 or pending is not None:
                raise ValueError('Invalid budget/inflight request')
            budget -= 1
            reads += 1
            pending = tick+1
        if action == 'STOP':
            stopped = True
        traces.append({'tick': tick, 'action': action, 'budget_after': budget,
                       'observation': asdict(obs), 'detail': detail})
    units = 25*sum(v['correct'] for v in outputs)-4*reads
    return {'summary': {'reward_units': units, 'net_reward': units/100,
                        'reads': reads, 'read_fees': reads*config.read_cost,
                        'cpu_seconds_nested': time.process_time()-began},
            'trace': traces, 'outputs': outputs, 'access': access}


def run(dest):
    p = read_plan(dest)
    q = json.loads((V9/'SERVICE_FIT.json').read_text())['forecast']
    fits = json.loads((V9/'ANALYTIC_FITS.json').read_text())
    models, selections = {}, {}
    for seed in p['ordinary_fits']:
        folder = prior.v9.V8/f'fit_{seed}'
        checkpoint = torch.load(folder/'models.pt', weights_only=False, map_location='cpu')
        selections[str(seed)] = json.loads((folder/'FIT.json').read_text())['selected_family']
        for family in p['ordinary_families']:
            models[(str(seed), family)] = prior.v9.load_core(checkpoint, family)
    scale = fits[p['analytic_fit_seed']]['original']['selected_scale']
    models[(p['analytic_fit_seed'], 'analytic')] = prior.v9.FittedAnalytic('original', scale)
    prior.v9.write(dest/'EVALUATION_FREEZE.json', {'plan_sha256': prior.v9.sha(dest/'PLAN.json'),
        'old_ordinary_selections': selections, 'before_new_world_generation': True, 'created_unix': time.time()})
    count = fixed = 0
    with gzip.open(dest/'worlds.jsonl.gz', 'xt') as worlds, gzip.open(dest/'runs.jsonl.gz', 'xt') as runs:
        for ci, condition in enumerate(p['conditions']):
            config = prior.v9.old.Config(**{**p['config'], 'condition': condition})
            for wi in range(p['worlds_per_condition']):
                seed = int(np.random.SeedSequence(p['world_namespace']+[ci, wi]).generate_state(1)[0])
                episode = prior.v9.old.make_episode(seed, config)
                episode['service_uniform'] = np.random.default_rng(np.random.SeedSequence([seed, 120889])).random(21).tolist()
                seeds = [[int(np.random.SeedSequence(p['policy_namespace']+[ci, wi, t, pool]).generate_state(1)[0])
                          for pool in (0, 1)] for t in range(20)]
                worlds.write(json.dumps({'condition': condition, 'index': wi, 'episode': episode, 'policy_seeds': seeds})+'\n')
                for (fs, family), core in models.items():
                    for controller in p['controllers']:
                        r = execute(core, controller, episode, config, q, seeds,
                                    p['selection_pool_size'], p['alpha_per_test'])
                        if controller == 'feedback_rollout':
                            schedule = {v['tick']: v['action'] for v in r['trace']}
                            replay = execute(core, 'lightweight', episode, config, q, seeds,
                                             p['selection_pool_size'], p['alpha_per_test'], schedule)
                            if r['outputs'] != replay['outputs'] or r['access'] != replay['access'] or r['summary']['reward_units'] != replay['summary']['reward_units']:
                                raise ArithmeticError('Fixed actions changed successors')
                            r['fixed_action_replay'] = replay
                            fixed += 1
                        runs.write(json.dumps({'condition': condition, 'index': wi, 'fit_seed': fs,
                                              'family': family, 'controller': controller, **r}, allow_nan=False)+'\n')
                        count += 1
                runs.flush()
                print(json.dumps({'condition': condition, 'world': wi, 'runs': count}), flush=True)
    prior.v9.write(dest/'COMPLETE.json', {'main_runs': count, 'fixed_runs': fixed, 'worlds': 12,
        'raw_sha256': prior.v9.sha(dest/'runs.jsonl.gz'), 'worlds_sha256': prior.v9.sha(dest/'worlds.jsonl.gz')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    {'prepare': prepare, 'run': run}[args.command](args.output)
