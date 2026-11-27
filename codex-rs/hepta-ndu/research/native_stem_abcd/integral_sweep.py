"""R3 pre-sweep source/plan freeze and failure-inclusive fresh-process execution."""
import argparse
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

from integral_trial import panels, sources
from run import digest, write_json


def specs():
    out=[]
    for seed in (11,23,47):
        for optimizer in ('adam','trf'):
            out.append(dict(family='integral',optimizer=optimizer,seed=seed,cpu_seconds=2,intervals=64))
    base=[('raw','adam'),('raw','trf'),('mixture','adam'),('mixture','trf'),('integral','adam'),('integral','trf')]
    for i,seed in enumerate((11,23,47)):
        for family,opt in base[i:]+base[:i]:
            out.append(dict(family=family,optimizer=opt,seed=seed,cpu_seconds=8,intervals=64))
        for family in ('raw','mixture','integral'):
            out.append(dict(family=family,optimizer='lbfgs',seed=seed,cpu_seconds=8,intervals=64))
        out.append(dict(family='transformer',optimizer='adam',seed=seed,cpu_seconds=8,intervals=64))
    for seed in (11,23,47):
        for family in ('raw','mixture','integral'):
            out.append(dict(family=family,optimizer='none',seed=seed,cpu_seconds=1,intervals=64))
    for grid in (16,128):
        out.append(dict(family='integral',optimizer='trf',seed=11,cpu_seconds=8,intervals=grid))
    for opt in ('adam','trf'):
        out.append(dict(family='scalar',optimizer=opt,seed=0,cpu_seconds=8,intervals=64))
    out.append(dict(family='direct',optimizer='none',seed=0,cpu_seconds=1,intervals=64))
    return out


def name_for(s):
    return f"{s['family']}-{s['optimizer']}-s{s['seed']}-b{s['cpu_seconds']}-g{s['intervals']}"


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parent
    plan=dict(schema='hepta.native-stem.integral.sweep.r3',source_sha256=sources(),runs=specs(),panels=panels(),
              parent_source='50550e6b6625f18d809649c595d595a873ad97e0',
              primary='integral TRF versus integral Adam: new_composed RMSE at 8 CPU cap, 64 intervals, all seeds',
              controls='single-parameter calibration Adam/TRF; raw/mixture B/C, all three LBFGS, Transformer, untrained families; 16/128 grid seed11 diagnostic',
              training='unchanged full finite 12 terminals x12 states x3 depths; no held-out loss in fit',
              terminal_seeds=[2026101431,2026101432,2026101433],
              prior_not_learning='zero-risk accuracy and range bounds hold without training',
              preliminary='64 source/math tests and 1-second C smoke before freeze; no R3 held-out efficacy scored',
              grid_witness='constant-field=1 analytic approximation test, not learned result',
              primary_requires_all_seeds=True,external_preregistration=False,production_authorized=False)
    h=write_json(args.out/'PLAN.json',plan);t=time.perf_counter();census=[]
    for s in plan['runs']:
        name=name_for(s);before=resource.getrusage(resource.RUSAGE_CHILDREN);now=time.perf_counter()
        cmd=[sys.executable,str(root/'integral_trial.py')]
        for k,v in s.items():cmd += ['--'+k.replace('_','-'),str(v)]
        cmd += ['--out',str(args.out/name)]
        row=dict(name=name,**s)
        with open(args.out/(name+'.log'),'xb') as log:
            try:
                r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=180,
                                 env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1'))
                row.update(returncode=r.returncode,status='completed' if r.returncode==0 else 'failed')
            except subprocess.TimeoutExpired:row.update(returncode=None,status='timeout')
            except OSError as e:row.update(returncode=None,status='launch_failed',error=str(e))
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(child_wall=time.perf_counter()-now,child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
        if row['status']=='completed':
            try:
                data=(args.out/name/'REPORT.json').read_bytes();report=json.loads(data)
                if report['plan_sha256']!=digest((args.out/name/'PLAN.json').read_bytes()):raise ValueError('plan drift')
                if sources()!=plan['source_sha256']:raise ValueError('source drift')
                row['report_sha256']=digest(data);row['composed_rmse']=report['metrics']['new_composed']['rmse']
            except (OSError,ValueError,KeyError) as e:row.update(status='evidence_failed',error=str(e))
        census.append(row);write_json(args.out/(name+'.completion.json'),row)
        print(json.dumps(row,sort_keys=True),flush=True)
    summary=dict(plan_sha256=h,census=census,completed=sum(r['status']=='completed' for r in census),
                 failed=sum(r['status']!='completed' for r in census),wall=time.perf_counter()-t,
                 child_cpu=sum(r['child_cpu'] for r in census),production_authorized=False)
    write_json(args.out/'COMPLETE.json',summary)
    if summary['failed']:raise SystemExit('failed runs retained')


if __name__=='__main__':main()
