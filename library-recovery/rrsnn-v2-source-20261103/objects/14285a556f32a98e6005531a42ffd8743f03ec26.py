"""Execute the predeclared matrix and a per-seed equal-CPU RNN control."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parent
AFFINITIES=list(sorted(os.sched_getaffinity(0)))
LOCK=threading.Lock()
FREE_CORES=[]

def worker(job):
    with LOCK: cpu=FREE_CORES.pop()
    variant,seed,sampled=job
    run=variant+('_sampled' if sampled else '')
    command=[sys.executable,'-m','rrsnn_v2.train','--variant',variant,'--seed',str(seed),'--epochs','32']
    if sampled: command.append('--sampled')
    try:
        execute(command,run,seed,cpu)
        if variant=='rr_density' and sampled:
            training=json.loads((ROOT/'results'/run/f'seed_{seed}'/'training.json').read_text())
            execute([sys.executable,'-m','rrsnn_v2.train','--variant','ctrnn_matched','--seed',str(seed),
                     '--epochs','10000','--cpu-budget',str(training['train_cpu_seconds']),'--suffix','_cpu'],
                    'ctrnn_matched_cpu',seed,cpu)
    finally:
        with LOCK: FREE_CORES.append(cpu)

def execute(command,run,seed,cpu):
    destination=ROOT/'results'/run/f'seed_{seed}'
    destination.mkdir(parents=True,exist_ok=True)
    final=destination/'training.json'
    if final.exists():
        print(json.dumps({'existing_complete':run,'seed':seed}),flush=True);return
    env=os.environ.copy();env.update(OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    with (destination/'run.log').open('w') as log:
        # taskset applies before Python initializes runtime libraries.
        child=subprocess.run(['taskset','-c',str(cpu)]+command,stdout=log,stderr=subprocess.STDOUT,
                             env=env,cwd=str(ROOT.parent))
    if child.returncode:
        raise RuntimeError(f'{run} seed{seed} failed; see {destination}/run.log')
    training=json.loads(final.read_text())
    print(json.dumps({'completed':run,'seed':seed,'best_val':training['best_validation_nll'],
                      'cpu_s':round(training['train_cpu_seconds'],2),'epochs':training['plan']['epochs']}),flush=True)

def main(workers=6):
    plan=json.loads((ROOT/'experiment_plan.json').read_text())
    for filename,expected in plan['frozen_sources'].items():
        actual=hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()
        if actual!=expected: raise RuntimeError(f'Frozen source mismatch: {filename}')
    jobs=[(v,s,sampled) for v,sampled in plan['training_families'] for s in plan['seeds']]
    FREE_CORES.extend(AFFINITIES[:workers])
    print(json.dumps({'jobs':len(jobs),'plus_equal_cpu_controls':5,'workers':workers,
                      'training_cpu_affinities':AFFINITIES[:workers],'reserved_cpu_affinities':AFFINITIES[workers:]}),flush=True)
    errors=[];begin=time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(worker,job) for job in jobs]
        for future in as_completed(futures):
            try: future.result()
            except Exception as error: errors.append(str(error));print(json.dumps({'error':str(error)}),flush=True)
    result={'elapsed_seconds':time.perf_counter()-begin,'errors':errors,'all_completed':not errors}
    (ROOT/'results/matrix_status.json').write_text(json.dumps(result,indent=2)+'\n')
    if errors: raise RuntimeError(errors)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=6)
    main(parser.parse_args().workers)
