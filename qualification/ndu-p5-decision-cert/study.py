"""Preregister -> seal action choices -> independently score coupled-FBSDE controls.

All tasks are *synthetic* fully-known stochastic laws. Two disjoint generated
windows are not longitudinal external observations; no neural capability is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
from time import process_time_ns

from decision import Option, Task, certify, cheap_and_fixed

SCHEMA='hepta.ndu.p5.costed-decision.v1'
CONFIG={'seed_a':14011,'seed_b':25817,'tasks_per_window':96,'max_calls':90,'fixed_depth':4}
FROZEN_SOURCE_SHA='e420444337d163508cd7ba8122894ffd334566b52d57073e67b94203e301eac2'


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=True).encode()


def hexdigest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def from_row(row):
    return Task(task_id=row['task_id'],x0=row['x0'],horizon=row['horizon'],
                sigma=row['sigma'],beta=row['beta'],lam=row['lam'],steps=row['steps'],
                options=tuple(Option(**o) for o in row['options']))


def plan():
    out=[]
    for w,seed in (('cohort_a',CONFIG['seed_a']),('cohort_b',CONFIG['seed_b'])):
        rng=random.Random(seed)
        for k in range(CONFIG['tasks_per_window']):
            # Frozen model coefficients and deliberate near-decision-boundary controls.
            x0=rng.uniform(-1.25,1.25)
            base=0.01+rng.uniform(0,.012)
            costs=[0.,base,2*base+rng.uniform(-.005,.005)]
            if k%7==0:
                costs[1],costs[2]=.002,.004
            if k%11==0:
                costs[1],costs[2]=.06,.12
            spec={'task_id':hashlib.sha256(f'p5-control-v1/{w}/{seed}/{k}'.encode()).hexdigest(),
                  'cohort':w,'x0':x0,'horizon':.8,'steps':4,
                  'sigma':round(rng.uniform(.15,.55),10),
                  'beta':round(rng.uniform(.15,.6),10),
                  'lam':round(rng.uniform(.05,.35),10),
                  'options':[{'action_id':f'control_{j}', 'a':a,
                              'cost':round(max(0.,costs[j]),10)}
                             for j,a in enumerate((0.,.27,.48))]}
            from_row(spec).validate()
            out.append(spec)
    if len(out)!=2*CONFIG['tasks_per_window']:
        raise ValueError('incomplete frozen task generation')
    return {'schema':SCHEMA,'kind':'plan','configuration':CONFIG,
            'cases':out,'production_accepted':False,'authority':'DENY_ALL',
            'synthetic_only':True,'true_future_time_verified':False}


def verify_plan(p):
    if type(p) is not dict or set(p)!={'schema','kind','configuration','cases',
              'production_accepted','authority','synthetic_only','true_future_time_verified'}:
        raise ValueError('unexpected plan fields')
    if p['schema']!=SCHEMA or p['kind']!='plan' or p['configuration']!=CONFIG:
        raise ValueError('incompatible profile')
    if p['production_accepted'] is not False or p['authority']!='DENY_ALL' or \
       p['synthetic_only'] is not True or p['true_future_time_verified'] is not False:
        raise ValueError('invalid authority profile')
    if type(p['cases']) is not list or len(p['cases'])!=192 or \
       len({x['task_id'] for x in p['cases']})!=192:
        raise ValueError('missing/duplicated source rows')
    if [x['cohort'] for x in p['cases']].count('cohort_a')!=96 or \
       [x['cohort'] for x in p['cases']].count('cohort_b')!=96:
        raise ValueError('source family inventory changed')
    # Hard-coded source digest was fixed BEFORE choices/labels were computed.
    if hexdigest(p)!=FROZEN_SOURCE_SHA or hexdigest(plan())!=FROZEN_SOURCE_SHA:
        raise ValueError('source data, ordering or predeclared generator changed')
    return True


def predict(p):
    verify_plan(p)
    entries=[]
    for task in p['cases']:
        current=from_row(task)
        one=certify(current,max_calls=CONFIG['max_calls'])
        cheap=cheap_and_fixed(current,fixed_steps=CONFIG['fixed_depth'])
        entries.append({'task_id':task['task_id'],'cohort':task['cohort'],
                        'nominal_early':one,'controls':cheap})
    return {'schema':SCHEMA,'kind':'sealed_predictions','source_sha256':hexdigest(p),
            'entries':entries,'reference_oracle_read_before_seal':False,
            'natural_reasoning_gain_claimed':False,'production_accepted':False,'authority':'DENY_ALL'}


def create(path,obj):
    with Path(path).open('xb') as f:f.write(canonical(obj)+b'\n')


def cli():
    a=argparse.ArgumentParser(description=__doc__)
    s=a.add_subparsers(dest='command',required=True)
    x=s.add_parser('plan');x.add_argument('--output',required=True)
    x=s.add_parser('predict')
    x.add_argument('--source',required=True);x.add_argument('--source-sha256',required=True)
    x.add_argument('--output',required=True)
    args=a.parse_args()
    if args.command=='plan':result=plan()
    else:
        if hashlib.sha256(Path(args.source).read_bytes()).hexdigest()!=args.source_sha256:
            raise ValueError('original preregistered file-byte digest differs')
        result=predict(read(args.source))
    create(args.output,result)
    print(json.dumps({'file':args.output,'sha256':hashlib.sha256(Path(args.output).read_bytes()).hexdigest(),
                      'production_accepted':False},sort_keys=True))

if __name__=='__main__':cli()
