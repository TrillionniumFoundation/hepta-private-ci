"""Replay risk-omitted original-model executions on frozen risk-aware D actions."""
import argparse
import gzip
import json
from pathlib import Path
import time
from . import campaign as study


def run(dest):
    plan = study.plan(dest)
    if not (dest/'COMPLETE.json').is_file():
        raise ValueError('Main run incomplete')
    study.write(dest/'FIXED_RISK_FREEZE.json', {'source_sha256': study.sha(__file__),
        'campaign_sha256': study.sha(study.__file__), 'runs_sha256': study.sha(dest/'runs.jsonl.gz'),
        'worlds_sha256': study.sha(dest/'worlds.jsonl.gz'), 'created_unix': time.time(),
        'engineering_replay_only': True})
    with gzip.open(dest/'worlds.jsonl.gz', 'rt') as stream:
        worlds = {(v['condition'], v['index']): v['episode'] for v in map(json.loads, stream)}
    with gzip.open(dest/'runs.jsonl.gz', 'rt') as stream:
        originals = [v for v in map(json.loads, stream) if v['family'] == 'analytic' and
                     v['mode'] == 'original' and v['controller'] == 'task_value' and v['risk'] and not v['fixed']]
    fits = json.loads((dest/'ANALYTIC_FITS.json').read_text())
    forecast = json.loads((dest/'SERVICE_FIT.json').read_text())['forecast']
    with gzip.open(dest/'fixed_risk_replay.jsonl.gz', 'xt') as stream:
        for old in originals:
            cfg = study.old.Config(**{**plan['config'], 'condition': old['condition']})
            scale = fits[old['fit_seed']]['original']['selected_scale']
            schedule = {v['tick']: v['action'] for v in old['trace']}
            new = study.rollout(study.FittedAnalytic('original', scale), 'task_value',
                worlds[(old['condition'], old['index'])], cfg, forecast, False, schedule)
            checks = {'predictions_equal': old['predictions'] == new['predictions'],
                      'access_equal': old['access'] == new['access'],
                      'actions_equal': [(v['tick'], v['action']) for v in old['trace']] ==
                                       [(v['tick'], v['action']) for v in new['trace']],
                      'net_reward_equal': old['summary']['net_reward'] == new['summary']['net_reward']}
            stream.write(json.dumps({'condition': old['condition'], 'index': old['index'],
                                     'fit_seed': old['fit_seed'], 'checks': checks, **new})+'\n')
            if not all(checks.values()):
                raise ArithmeticError('Fixed risk intervention changed execution')
    study.write(dest/'FIXED_RISK_COMPLETE.json', {'replayed_runs': len(originals), 'all_exact': True,
                                                'raw_sha256': study.sha(dest/'fixed_risk_replay.jsonl.gz')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
