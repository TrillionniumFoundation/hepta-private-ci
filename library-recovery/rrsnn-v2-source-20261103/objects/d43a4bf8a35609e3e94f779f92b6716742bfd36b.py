"""Execute frozen-weight closed-loop and paired tests after model selection."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import threading
import numpy as np
import torch
from .evaluate import evaluate,load_policy,load_scenarios,load_oracles

ROOT=Path(__file__).resolve().parent
LOCK=threading.Lock();FREE_CPUS=[]

def write_gzip(path,payload):
    with gzip.open(path,'wt',encoding='utf-8') as handle: json.dump(payload,handle)

def one(checkpoint):
    torch.set_num_threads(1)
    model,blob=load_policy(checkpoint)
    mode='ctmc' if blob.get('sampled_training') else 'density'
    destination=Path(checkpoint).parent
    header={'run_name':blob['run_name'],'seed':blob['seed'],'variant':blob['variant'],
            'checkpoint_sha256':hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
            'evaluated_after_frozen_model_selection':True,'real_future_window':False}
    for name in ['test','shift']:
        output=destination/f'closed_{name}.json.gz'
        if output.exists(): continue
        scenarios=load_scenarios(name);oracles=load_oracles(name,scenarios)
        result=evaluate(model,scenarios,oracles,mode,900000+blob['seed'])
        write_gzip(output,{**header,'dataset':name,'evaluation':result})
        print(json.dumps({'run':blob['run_name'],'seed':blob['seed'],'dataset':name,'mode':mode,
                          'utility':result['normalized_utility_mean']}),flush=True)
    scenarios=load_scenarios('paired');oracles=load_oracles('paired',scenarios)
    repeats=4 if blob.get('sampled_training') else 1
    for repeat in range(repeats):
        output=destination/f'paired_rep{repeat}.json.gz'
        if output.exists(): continue
        result=evaluate(model,scenarios,oracles,mode,940000+blob['seed']+10007*repeat,keep_trace=True)
        write_gzip(output,{**header,'dataset':'paired','repeat':repeat,'evaluation':result})
    # Same learned controls under a distinct continuous physical law. This is
    # a transfer diagnostic, not a claim of exact equality to the finite CTMC.
    if blob['run_name'] in ('rr_density_sampled','rr_density'):
        for name in ['test','shift']:
            output=destination/f'transfer_{name}_brownian.json.gz'
            if output.exists(): continue
            scenarios=load_scenarios(name);oracles=load_oracles(name,scenarios)
            result=evaluate(model,scenarios,oracles,'brownian',960000+blob['seed'])
            write_gzip(output,{**header,'dataset':name,'evaluation':result,
                'different_physical_model':'continuous Brownian plus deterministic refractory, no reflecting grid or stochastic remap'})
        if blob['run_name']=='rr_density':
            for name in ['test','shift']:
                output=destination/f'transfer_{name}_ctmc.json.gz'
                if output.exists(): continue
                scenarios=load_scenarios(name);oracles=load_oracles(name,scenarios)
                result=evaluate(model,scenarios,oracles,'ctmc',900000+blob['seed'])
                write_gzip(output,{**header,'dataset':name,'evaluation':result})

def freeze_selection():
    plan=json.loads((ROOT/'experiment_plan.json').read_text())
    families=[v+('_sampled' if sample else '') for v,sample in plan['training_families']]+['ctrnn_matched_cpu']
    results={}
    for family in families:
        results[family]=[]
        for seed in plan['seeds']:
            path=ROOT/'results'/family/f'seed_{seed}'/'training.json'
            row=json.loads(path.read_text())
            for filename,expected in row['source_hashes'].items():
                if hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()!=expected:
                    raise RuntimeError(f'Training source drift: {filename}')
            results[family].append(row)
    candidates=plan['secondary_comparators_selected_only_by_mean_validation_nll']
    averages={name:float(np.mean([r['best_validation_nll'] for r in results[name]])) for name in candidates}
    selected=min(averages,key=averages.get)
    output={'schema':'rrsnn.v2.selection.v1','primary_candidate':plan['primary_candidate'],
            'primary_comparator':plan['primary_comparator'],'secondary_strong_baseline':selected,
            'secondary_baseline_mean_validation_nll':averages,'holdout_metrics_used_for_selection':False,
            'checkpoints':{name:{str(row['seed']):row['checkpoint_sha256'] for row in rows} for name,rows in results.items()},
            'evaluation_source_sha256':hashlib.sha256((ROOT/'evaluate.py').read_bytes()).hexdigest(),
            'sampling_source_sha256':hashlib.sha256((ROOT/'audit/sampled_policy.py').read_bytes()).hexdigest(),
            'plan_sha256':hashlib.sha256((ROOT/'experiment_plan.json').read_bytes()).hexdigest()}
    (ROOT/'results/selection.json').write_text(json.dumps(output,indent=2)+'\n')
    return [ROOT/'results'/family/f'seed_{seed}'/'model.pt' for family in families for seed in plan['seeds']]

def run_child(checkpoint):
    with LOCK: cpu=FREE_CPUS.pop()
    try:
        with (checkpoint.parent/'evaluation.log').open('w') as log:
            env=os.environ.copy();env.update(OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
            result=subprocess.run(['taskset','-c',str(cpu),sys.executable,'-m','rrsnn_v2.run_evaluations','--one',str(checkpoint)],
                                  stdout=log,stderr=subprocess.STDOUT,cwd=str(ROOT.parent),env=env)
        if result.returncode: raise RuntimeError(f'Evaluation failed {checkpoint}')
        print(json.dumps({'evaluation_completed':str(checkpoint)}),flush=True)
    finally:
        with LOCK: FREE_CPUS.append(cpu)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--one');parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args()
    if args.one: one(Path(args.one))
    else:
        paths=freeze_selection();FREE_CPUS.extend(sorted(os.sched_getaffinity(0))[:args.workers])
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(run_child,p) for p in paths]): future.result()
