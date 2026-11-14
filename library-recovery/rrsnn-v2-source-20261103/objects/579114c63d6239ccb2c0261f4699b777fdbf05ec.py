"""Same-checkpoint analytic-vs-quadrature implementation control.

Only F/H are replaced by numerical density quadrature. Conditional surviving
mean, Lambert-W threshold and the observation-grid proxy remain analytic or
unchanged. This is not a full PDE replacement or exact-runtime equivalence test.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

for _name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:
    os.environ[_name]='1'

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from rrsnn_experiments.train_compare import Policy,load_arrays,load_scenarios,evaluate_closed_loop


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(result):
    return {k:v for k,v in result.items() if k not in ['terminal_latents','traces']}


@torch.no_grad()
def output_comparison(a,b,arrays,limit):
    n=min(limit,len(arrays['x']))
    length=int(arrays['lengths'][:n].max())
    x=arrays['x'][:n,:length];dt=arrays['dt'][:n,:length]
    start=time.perf_counter();ar=a(x,dt);ta=time.perf_counter()-start
    start=time.perf_counter();br=b(x,dt);tb=time.perf_counter()-start
    valid=arrays['valid'][:n,:length];decision=arrays['decision'][:n,:length]
    ap=torch.softmax(ar['logits'].masked_fill(~valid,-1e9),dim=-1)
    bp=torch.softmax(br['logits'].masked_fill(~valid,-1e9),dim=-1)
    logits_error=(ar['logits']-br['logits']).abs()
    latent_error=(ar['latent']-br['latent']).abs()
    return {'validation_episodes':n,'maximum_observed_steps':length,
            'max_abs_logit_difference':float(logits_error.max()),
            'mean_abs_logit_difference':float(logits_error.mean()),
            'max_abs_latent_difference':float(latent_error.max()),
            'max_abs_legal_probability_difference':float((ap-bp).abs().max()),
            'decision_count':int(decision.sum()),
            'legal_argmax_disagreements':int(((ap.argmax(-1)!=bp.argmax(-1))&decision).sum()),
            'analytic_single_forward_seconds':ta,'quadrature_single_forward_seconds':tb,
            'timing_scope':'single validation forward including cold numeric-node initialization; not a latency benchmark'}


def fixed_boundary_comparison(seed,arrays,limit):
    checkpoint=ROOT/'results'/'fp_multi_fixed'/f'seed_{seed}'/'model.pt'
    if not checkpoint.exists() or not checkpoint.with_name('result.json').exists():
        return {'status':'checkpoint not yet complete'}
    saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
    fixed=Policy('fp_multi_fixed',mode='expected');fixed.load_state_dict(saved['state_dict']);fixed.eval()
    rr_fixed=Policy('rr_full',mode='expected');rr_fixed.load_state_dict(saved['state_dict']);rr_fixed.eval()
    rr_fixed.encoder.ablations=frozenset({'fixed_boundary'})
    check=output_comparison(fixed,rr_fixed,arrays,limit)
    assert check['max_abs_logit_difference']==0.0
    return {'checkpoint_sha256':sha(checkpoint),
            'reference':'reuse trained fp_multi_fixed checkpoint; no independent training evidence',
            'validation':check}


def control_seed(seed,limit):
    checkpoint=ROOT/'results'/'rr_full'/f'seed_{seed}'/'model.pt'
    saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
    analytic=Policy('rr_full',mode='expected')
    analytic.load_state_dict(saved['state_dict']);analytic.eval()
    numeric=copy.deepcopy(analytic)
    numeric.encoder.ablations=frozenset({'numerical_kernel'})
    numeric.eval()
    assert all(torch.equal(v,numeric.state_dict()[k]) for k,v in analytic.state_dict().items())
    arrays=load_arrays('validation')
    result={'seed':seed,'checkpoint_sha256':sha(checkpoint),'weights_identical':True,
         'training_runs_added':0,'implementation_change':'CDF F and discounted-hit H only -> numerical density quadrature',
         'unchanged':['conditional surviving mean remains analytic','Lambert-W threshold remains analytic',
                      'moment closure, reset, observation grid, weights, costs and features remain unchanged'],
         'validation':output_comparison(analytic,numeric,arrays,limit),'closed_loop':{}}
    for name in ['confirm_test','confirm_future']:
        scenarios=load_scenarios(name)[:limit]
        ae=evaluate_closed_loop(analytic,scenarios,seed+900_000,'expected')
        ne=evaluate_closed_loop(numeric,scenarios,seed+900_000,'expected')
        au=np.asarray(ae['episode_utility']);nu=np.asarray(ne['episode_utility'])
        result['closed_loop'][name]={
           'case_selection':f'first {len(scenarios)} scenarios in the frozen {name} split',
           'scenario_file_sha256':sha(ROOT/'data'/f'{name}_scenarios.json'),
           'analytic':compact(ae),'quadrature':compact(ne),
           'paired_utility_difference_mean':float(np.mean(nu-au)),
           'paired_utility_difference_max_abs':float(np.max(np.abs(nu-au))),
           'episodes_with_changed_utility':int(np.sum(np.abs(nu-au)>1e-9)),
           'ledger_conserved_both':bool(ae['ledger_conservation'] and ne['ledger_conservation']),
           'budget_violations_total':ae['budget_violations']+ne['budget_violations']}
    result['fixed_boundary_equivalence']=fixed_boundary_comparison(seed,arrays,limit)
    result['source_sha256']={str(p.relative_to(ROOT)):sha(p) for p in [
        ROOT/'models'/'sequence_models.py',ROOT/'models'/'budget_ctrnn.py',ROOT/'train_compare.py',ROOT/'resource_env.py']}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds',nargs='+',type=int,default=[101,211,307,401,503])
    parser.add_argument('--limit',type=int,default=64)
    parser.add_argument('--rerun',action='store_true')
    args=parser.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    affinity=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,{affinity[-1]})
    destination=OUT/'implementation_control_results.json'
    previous=json.loads(destination.read_text()) if destination.exists() and not args.rerun else {}
    records={int(r['seed']):r for r in previous.get('results',[])} if previous.get('limit_per_split')==args.limit else {}
    missing=[]
    for seed in args.seeds:
        checkpoint=ROOT/'results'/'rr_full'/f'seed_{seed}'/'model.pt'
        receipt=checkpoint.with_name('result.json')
        if not checkpoint.exists() or not receipt.exists():
            missing.append(seed);continue
        if seed in records and records[seed]['checkpoint_sha256']==sha(checkpoint):
            if records[seed]['fixed_boundary_equivalence'].get('status')=='checkpoint not yet complete':
                records[seed]['fixed_boundary_equivalence']=fixed_boundary_comparison(seed,load_arrays('validation'),args.limit)
            continue
        print(json.dumps({'starting_seed':seed,'limit':args.limit}),flush=True)
        record=control_seed(seed,args.limit)
        records[seed]=record
        partial={'schema':'rrsnn.same-weights-implementation-control.v1','results':list(records.values()),
                 'requested_seeds':args.seeds,'missing_seeds':missing,'complete':False,'limit_per_split':args.limit}
        temporary=destination.with_suffix('.tmp')
        temporary.write_text(json.dumps(partial,indent=2)+'\n');temporary.replace(destination)
        print(json.dumps({'finished_seed':seed,'validation_max_logit_error':record['validation']['max_abs_logit_difference'],
                          'closed_loop_changed_utility':{k:v['episodes_with_changed_utility'] for k,v in record['closed_loop'].items()}}),flush=True)
    aggregate={'schema':'rrsnn.same-weights-implementation-control.v1',
           'results':[records[k] for k in sorted(records)],'requested_seeds':args.seeds,'missing_seeds':missing,
           'complete':all(seed in records for seed in args.seeds),'limit_per_split':args.limit,
           'script_sha256':sha(Path(__file__).resolve()),
           'scope':'only F/H implementation is replaced; conditional mean remains analytic, no full-PDE or exact-runtime claim'}
    temporary=destination.with_suffix('.tmp');temporary.write_text(json.dumps(aggregate,indent=2)+'\n');temporary.replace(destination)
    print(json.dumps({'completed_seeds':sorted(records),'missing_seeds':missing,'output':str(destination)}),flush=True)


if __name__=='__main__':
    main()
