"""Summarize the registered primary experiment and the two pre-held-out supplements."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean


def read(p):
    return json.loads(p.read_bytes())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def summarize(evidence):
    families = defaultdict(list)
    controls = {}
    query_identity = None
    for number, root in zip((27, 9, 15), evidence, strict=True):
        path = root / 'selection_seal.json'
        seal = read(path)
        if len(seal['files']) != number:
            raise ValueError('incomplete selection roster')
        for name, checksum in sorted(seal['files'].items()):
            fp, cp = root / 'fit' / name, root / 'confirm' / name
            f, c = read(fp), read(cp)
            if sha(fp) != checksum or c.get('fit_hash', c.get('fit_sha256')) != checksum or c.get('selection_seal', c.get('seal_sha256')) != sha(path):
                raise ValueError(name)
            ids = list(zip(c['query_id'], c.get('actor',c.get('group'))))
            if query_identity is None:
                query_identity = ids
            if query_identity != ids or len(ids) != 48:
                raise ValueError('inconsistent query pairing')
            if 'controls' in c:
                if controls and controls != c['controls']:
                    raise ValueError('shared control mismatch')
                controls = c['controls']
            if not controls:
                raise ValueError('primary results must come first')
            a, k, base = c['chosen'], c['keep'], controls['immediate_stop']
            deltas = {g:v-k['per_actor'][g] for g,v in a['per_actor'].items()}
            vs_stop = min(v-base['per_actor'][g] for g,v in a['per_actor'].items())
            passed = a['utility']>=.60 and a['r1']>=.70 and min(deltas.values())>=-.05-1e-12
            if abs(min(deltas.values())-c['worst_actor_delta'])>1e-12 or passed!=c['success']:
                raise ValueError('threshold calculation differed')
            costs = {}
            for phase, obj in [('fit',fp), ('confirm',cp)]:
                cost = read(obj.with_suffix('.cost.json'))
                if cost['returncode'] or cost.get('output_sha',cost.get('output_sha256')) != sha(obj):
                    raise ValueError('invalid cost receipt')
                costs[phase] = cost['wall_seconds']
            rep = f['fit']
            row = dict(seed=c['seed'],utility=a['utility'],r1=a['r1'],worst=min(deltas.values()),
                       actor_deltas=deltas,worst_vs_stop=vs_stop,reads=a['reads'],waits=a['wait_steps'],
                       edit=bool(rep['changed']),errors=rep['errors'],pass_all=passed,**costs,
                       operations=rep['cost'],attempts=len(rep['attempts']))
            families[(c['mode'],c['method'])].append(row)
    groups = []
    for (mode,method),arms in families.items():
        if len(arms)!=3:
            raise ValueError('missing seeds')
        groups.append(dict(mode=mode,method=method,arms=arms,utility=fmean(a['utility'] for a in arms),
                           r1=fmean(a['r1'] for a in arms),worst=min(a['worst'] for a in arms),
                           worst_vs_stop=min(a['worst_vs_stop'] for a in arms),
                           passed=sum(a['pass_all'] for a in arms), changed=sum(a['edit'] for a in arms),
                           cold_fit_confirm=fmean(a['fit']+a['confirm'] for a in arms),
                           fit=fmean(a['fit'] for a in arms),confirm=fmean(a['confirm'] for a in arms),
                           reads=fmean(a['reads'] for a in arms),waits=fmean(a['waits'] for a in arms)))
    return dict(families=groups,controls=controls,distinct_episodes=len(query_identity),
                unique_actors=len({x[1] for x in query_identity}))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('evidence',type=Path,nargs=3,help='primary, task-surface and economy controls')
    print(json.dumps(summarize(p.parse_args().evidence),indent=2,allow_nan=False))
