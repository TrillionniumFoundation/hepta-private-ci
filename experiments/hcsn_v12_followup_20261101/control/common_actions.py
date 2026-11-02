"""Execute the analytic feedback policy's actions on every ordinary core."""
import argparse
import gzip
import json
from pathlib import Path
import time
import torch
from . import campaign


def run(dest):
    p = campaign.read_plan(dest)
    if not (dest/'COMPLETE.json').is_file():
        raise ValueError('Main campaign incomplete')
    campaign.prior.v9.write(dest/'COMMON_ACTIONS_FREEZE.json', {
        'source_sha256': campaign.prior.v9.sha(__file__),
        'main_runs_sha256': campaign.prior.v9.sha(dest/'runs.jsonl.gz'),
        'worlds_sha256': campaign.prior.v9.sha(dest/'worlds.jsonl.gz'),
        'created_unix': time.time(), 'selection': 'all analytic feedback schedules; all ordinary fits/families'})
    with gzip.open(dest/'worlds.jsonl.gz', 'rt') as stream:
        worlds = {(v['condition'], v['index']): v for v in map(json.loads, stream)}
    with gzip.open(dest/'runs.jsonl.gz', 'rt') as stream:
        ds = [v for v in map(json.loads, stream) if v['family'] == 'analytic' and v['controller'] == 'feedback_rollout']
    q = json.loads((campaign.V9/'SERVICE_FIT.json').read_text())['forecast']
    models = {}
    for seed in p['ordinary_fits']:
        ckpt = torch.load(campaign.prior.v9.V8/f'fit_{seed}'/'models.pt', weights_only=False, map_location='cpu')
        for family in p['ordinary_families']:
            models[(str(seed), family)] = campaign.prior.v9.load_core(ckpt, family)
    count = 0
    with gzip.open(dest/'common_actions.jsonl.gz', 'xt') as stream:
        for d in ds:
            w = worlds[(d['condition'], d['index'])]
            cfg = campaign.prior.v9.old.Config(**{**p['config'], 'condition': d['condition']})
            schedule = {v['tick']: v['action'] for v in d['trace']}
            for (fs, family), core in models.items():
                r = campaign.execute(core, 'lightweight', w['episode'], cfg, q, w['policy_seeds'],
                                     p['selection_pool_size'], p['alpha_per_test'], schedule)
                if r['access'] != d['access'] or r['summary']['read_fees'] != d['summary']['read_fees']:
                    raise ArithmeticError('Common actions changed service/observation/fee successors')
                if [(v['tick'], v['action']) for v in r['trace']] != [(v['tick'], v['action']) for v in d['trace']]:
                    raise ArithmeticError('Common actions changed action sequence')
                stream.write(json.dumps({'condition': d['condition'], 'index': d['index'],
                                         'fit_seed': fs, 'family': family, **r})+'\n')
                count += 1
    campaign.prior.v9.write(dest/'COMMON_ACTIONS_COMPLETE.json', {'ordinary_runs': count,
        'all_service_observation_and_fee_successors_equal': True,
        'raw_sha256': campaign.prior.v9.sha(dest/'common_actions.jsonl.gz')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    run(parser.parse_args().output)
