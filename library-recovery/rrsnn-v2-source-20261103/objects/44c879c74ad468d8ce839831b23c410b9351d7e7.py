"""Run the predeclared training matrix with bounded CPU concurrency."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parent

def main():
    plan=json.loads((ROOT/'data/experiment_plan.json').read_text())
    names=plan['baseline_variants']+plan['ablation_variants']
    # Interleave model families within seeds; this order is frozen, not selected
    # from test outcomes. Every model has the same optimizer update budget.
    jobs=[(name,seed) for seed in plan['seeds'] for name in names]
    logs=ROOT/'results/logs';logs.mkdir(parents=True,exist_ok=True)
    lock={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
          ['train_compare.py','resource_env.py','models/sequence_models.py','models/budget_ctrnn.py','data/experiment_plan.json']}
    (ROOT/'results/source_freeze.json').write_text(json.dumps(lock,indent=2)+'\n')
    started=time.perf_counter()
    def run(job):
        name,seed=job
        path=logs/f'{name}_{seed}.log'
        env=os.environ.copy();env.update({'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
          'OPENBLAS_NUM_THREADS':'1','PYTHONHASHSEED':str(seed)})
        with path.open('w') as log:
            r=subprocess.run([sys.executable,'-m','rrsnn_experiments.train_compare',
                              '--variant',name,'--seed',str(seed)],cwd=WORKSPACE,
                             env=env,stdout=log,stderr=subprocess.STDOUT)
        return {'variant':name,'seed':seed,'returncode':r.returncode,
                'last_lines':path.read_text().splitlines()[-6:]}
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending={pool.submit(run,job):job for job in jobs}
        for future in as_completed(pending):
            result=future.result();results.append(result)
            print(json.dumps({'completed':len(results),'total':len(jobs),**result}),flush=True)
            (ROOT/'results/matrix_status.json').write_text(json.dumps({
                'planned':len(jobs),'completed':len(results),'results':results},indent=2)+'\n')
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in lock.items())
    report={'planned':len(jobs),'completed':len(results),
            'failures':[r for r in results if r['returncode']!=0],
            'source_unchanged_during_matrix':unchanged,
            'wall_seconds':time.perf_counter()-started,'results':results}
    (ROOT/'results/matrix_status.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'done':True,'failures':len(report['failures']),
                      'source_unchanged':unchanged,'wall_seconds':report['wall_seconds']}),flush=True)
    return 0 if not report['failures'] and unchanged else 1

if __name__=='__main__':
    raise SystemExit(main())
