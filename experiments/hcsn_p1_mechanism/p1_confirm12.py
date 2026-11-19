"""Frozen 12-new-seed P1 factorial confirmation, run in four nonadaptive batches.

Protocol was committed before all primary runs. This is an independent
post-pilot confirmation, not a replacement of old 5-seed negative trials.
Same source, weights, optimizer schedule per seed as the upstream pilot.
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import pathlib
import time

from .p1_factorial import ARMS, TASKS, run_full

SEEDS=tuple(range(100,112))
ALPHA=0.05
FAMILY=14
PROTO='CONFIRMATION_PROTOCOL_12SEEDS_20261031.json'


def _seal(obj):
    return json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n'


def _write(path,obj):
    path=pathlib.Path(path)
    data=_seal(obj)
    path.write_text(data)
    return hashlib.sha256(data.encode()).hexdigest()


def execute_batch(group: int,out_dir: str):
    if type(group) is not int or group not in range(4):
        raise ValueError('group must be 0,1,2,3')
    os.environ['OMP_NUM_THREADS']='1'
    seeds=SEEDS[group*3:group*3+3]
    start=time.perf_counter()
    r=run_full(seeds=seeds,updates=120,batch=48,hidden=20,
               train_count=512,test_count=384)
    if len(r['records'])!=48 or r['active_param_count']!=561:
        raise ValueError('unexpected training matrix')
    result={'schema':'hcsn-p1-confirm12-batch-v1','group':group,'seeds':list(seeds),
            'frozen_protocol':PROTO,'trainer_blob':'eb81a440d0cd583b9f296788742c3c5be120e965',
            'hardware':'PyTorch CPU single-thread; not full platform cost',
            'reconstructed_hx_reference':True,
            'model_selection':False,'records':r['records'],
            'elapsed_wall_seconds':time.perf_counter()-start}
    dest=pathlib.Path(out_dir)/f'P1_CONFIRM_BATCH{group}.json'
    return dict(path=str(dest),sha256=_write(dest,result),seeds=list(seeds),jobs=48)


def _exact_two_sided_p(deltas):
    # Exact paired sign randomization under a sign-symmetric null.
    if len(deltas)!=12 or any(not math.isfinite(d) for d in deltas):
        raise ValueError('unregistered sign test')
    obs=abs(sum(deltas))
    num=0
    for signs in itertools.product((-1,1),repeat=12):
        if abs(sum(s*d for s,d in zip(signs,deltas)))>=obs-1e-12:
            num+=1
    return num/(2**12)


def combine(out_dir: str):
    out=pathlib.Path(out_dir)
    parts=[json.loads((out/f'P1_CONFIRM_BATCH{i}.json').read_text()) for i in range(4)]
    all_rows=[]
    for i,p in enumerate(parts):
        if (p['group']!=i or p['seeds']!=list(SEEDS[i*3:i*3+3])
                or p['frozen_protocol']!=PROTO or len(p['records'])!=48):
            raise ValueError('incomplete or altered batch')
        all_rows.extend(p['records'])
    keysets={(r['task'],r['arm'],r['seed']) for r in all_rows}
    expected={(task,arm,seed) for task in TASKS for arm in ARMS for seed in SEEDS}
    if len(all_rows)!=192 or keysets!=expected:
        raise ValueError('missing, unexpected or duplicate primary job')
    if not all(r['params']==561 and r['updates']==120 and r['batch']==48
               and r['hidden']==20 and r['train_count']==512 and r['test_count']==384
               for r in all_rows):
        raise ValueError('trial shape/compute mismatch')
    results=[]
    for task in TASKS:
        base={r['seed']:r for r in all_rows if r['task']==task and r['arm']=='ordinary'}
        for arm in ARMS:
            sample=sorted((r for r in all_rows if r['task']==task and r['arm']==arm),
                          key=lambda r:r['seed'])
            paired=[float(r['ood_acc']-base[r['seed']]['ood_acc']) for r in sample]
            results.append(dict(task=task,arm=arm,paired_ood_deltas=paired,
                mean_ood_delta=sum(paired)/12,
                mean_id_acc=sum(r['id_acc'] for r in sample)/12,
                mean_ood_acc=sum(r['ood_acc'] for r in sample)/12,
                mean_recorded_cpu_seconds=sum(r['cpu_seconds'] for r in sample)/12,
                signflip_two_sided_p=(1. if arm=='ordinary' else _exact_two_sided_p(paired))))
    contrasts=sorted((x for x in results if x['arm']!='ordinary'),
                     key=lambda x:x['signflip_two_sided_p'])
    if len(contrasts)!=FAMILY or 2/(2**5) <=ALPHA/FAMILY or 2/(2**12)>ALPHA/FAMILY:
        raise ValueError('invalid pre-registered Holm feasibility')
    previous=0.
    for i,x in enumerate(contrasts):
        previous=max(previous,min(1.,(FAMILY-i)*x['signflip_two_sided_p']))
        x['holm_adjusted_p']=previous
    family_full=[x for x in results if x['arm']=='all_three']
    scientific_success=all(x['holm_adjusted_p']<=ALPHA and x['mean_ood_delta']>=.02
                           for x in family_full)
    # Mandatory P1 full-platform cost/online finance table gate is NOT tested.
    artifact={'schema':'hcsn-p1-confirm12-all-v1','source_blob':'eb81a440d0cd583b9f296788742c3c5be120e965',
              'protocol':PROTO,'seeds':list(SEEDS),'n_jobs':len(all_rows),
              'alpha':ALPHA,'Holm_family':FAMILY,
              'pilot_five_seed_unrejectable_at_FWER_005':True,
              'results':results,'all_records':all_rows,
              'registered_ood_success_observed':scientific_success,
              'full_platform_compute_matched':False,
              'causal_full_HCSN_mechanism_proven':False,
              'scientific_gate_closed':False,'production_activation':False}
    dest=out/'P1_CONFIRM_12SEED_FULL_20261031.json'
    return dict(path=str(dest),sha256=_write(dest,artifact),
                results=results,record_count=len(all_rows),
                registered_ood_success_observed=scientific_success)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--group',type=int)
    p.add_argument('--combine',action='store_true')
    p.add_argument('--out-dir',required=True)
    a=p.parse_args()
    if a.combine==(a.group is not None):
        p.error('choose exactly one of --combine or --group')
    print(json.dumps(combine(a.out_dir) if a.combine else execute_batch(a.group,a.out_dir),
                     indent=2,sort_keys=True))

if __name__=='__main__':
    main()
