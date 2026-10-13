"""Sequential fresh-process experiments, immutable plan and complete failure census."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def dump(path, obj):
    data=(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with open(path,'xb') as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parent
    source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.py')}
    runs=[]
    orders={11:['A','B','C'],23:['B','C','A'],47:['C','A','B']}
    for budget in (2,8):
        for seed,order in orders.items():
            for arm in order:
                runs.append(dict(arm=arm,seed=seed,cpu_seconds=budget))
    runs += [dict(arm='B_LBFGS',seed=s,cpu_seconds=8) for s in orders]
    runs += [dict(arm='D',seed=0,cpu_seconds=1)]
    plan=dict(schema='hepta.native-stem-abcd.sweep.v1',runs=runs,source_sha256=source,
              pairing='B/C exact model class, parameters, initial bytes, full residual, terminal law and CPU cap',
              primary='B versus C: new_terminal RMSE at 8 CPU-second cap; paired per initialization',
              secondary=['long horizon','2 to 6 binary coordinates','changed dynamics','zero-risk probability'],
              optimizer_control='B_LBFGS same family and full loss, 8-second cap',
              decision_rule='no superiority declaration from internal residual; report every seed and control',
              fit_select_uses_holdout=False,pretrained=False,production_authorized=False,
              knowledge='entire finite training law known; held-out terminal laws not in that objective',
              preliminary='one .6s C development smoke and unit tests preceded this local freeze; not external preregistration')
    plan_hash=dump(args.out/'SWEEP_PLAN.json',plan)
    start=time.perf_counter()
    census=[]
    for r in runs:
        name=f"{r['arm']}-s{r['seed']}-b{r['cpu_seconds']}"
        folder=args.out/name
        command=[sys.executable,str(root/'run.py'),'--arm',r['arm'],'--seed',str(r['seed']),
                 '--cpu-seconds',str(r['cpu_seconds']),'--out',str(folder)]
        env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        t=time.perf_counter()
        with open(args.out/(name+'.log'),'xb') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=180)
        item=dict(**r,name=name,returncode=result.returncode,whole_child_wall_seconds=time.perf_counter()-t)
        if result.returncode==0:
            report=json.loads((folder/'REPORT.json').read_text())
            if report['plan_sha256'] != hashlib.sha256((folder/'PLAN.json').read_bytes()).hexdigest():
                raise AssertionError('child plan drift')
            if source != {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.py')}:
                raise AssertionError('source drift during sweep')
            item['report_sha256']=hashlib.sha256((folder/'REPORT.json').read_bytes()).hexdigest()
            item['new_terminal_rmse']=report['metrics']['new_terminal']['rmse']
        census.append(item)
        dump(args.out/(name+'.completion.json'),item)
        print(json.dumps(item,sort_keys=True),flush=True)
    rows=[]
    for item in census:
        if item['returncode']:
            continue
        report=json.loads((args.out/item['name']/'REPORT.json').read_text())
        for panel,m in report['metrics'].items():
            rows.append(dict(arm=item['arm'],seed=item['seed'],budget=item['cpu_seconds'],panel=panel,
                             rmse=m['rmse'],max_error=m['final_max_error'],regret=m['decision_regret'],
                             accuracy=m['decision_accuracy'],training_cpu=report['fit']['training_cpu_seconds'],
                             child_wall=item['whole_child_wall_seconds'],rss=report['process_peak_rss_bytes']))
    with open(args.out/'SCORES.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for budget in (2,8):
        for seed in orders:
            b=json.loads((args.out/f'B-s{seed}-b{budget}'/'REPORT.json').read_text())
            c=json.loads((args.out/f'C-s{seed}-b{budget}'/'REPORT.json').read_text())
            if b['fit']['initial_weights_sha256']!=c['fit']['initial_weights_sha256']:
                raise AssertionError('B/C initial weights differ')
            if b['parameter_count']!=c['parameter_count']:
                raise AssertionError('B/C model family changed')
    dump(args.out/'COMPLETE.json',dict(plan_sha256=plan_hash,census=census,
                                     whole_sweep_wall_seconds=time.perf_counter()-start,
                                     completed=sum(x['returncode']==0 for x in census),
                                     failed=sum(x['returncode']!=0 for x in census),
                                     exact_compute_match=False,production_authorized=False))


if __name__=='__main__':
    main()
