"""R14 fresh-process matched controls with create-only evidence and paid timings."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ.setdefault(name,'1')
import argparse
import hashlib
import json
import resource
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from solver import fit, initial,SEEDS,METHODS,CAP
from certificate import certificate

HERE=Path(__file__).resolve().parent
SOURCE_FILES=('problem.py','intervals.py','certificate.py','solver.py','scout.py','stress.py','sweep.py')

def sha(data):return hashlib.sha256(data).hexdigest()
def sources():return {name:sha((HERE/name).read_bytes()) for name in SOURCE_FILES}
def write_json(path,obj):
    data=(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with path.open('xb') as stream:stream.write(data)
    return sha(data)
def store_array(path,arr):
    with path.open('xb') as stream:np.save(stream,arr,allow_pickle=False)

def cases():
    return [dict(seed=seed,method=m) for seed in SEEDS for m in METHODS[(seed//11)%3:]+METHODS[:(seed//11)%3]]
def case_name(case):return f"s{case['seed']}-{case['method']}"

def execute(out,seed,method):
    out.mkdir(parents=True,exist_ok=False)
    begin=time.perf_counter(),time.process_time()
    plan=dict(schema='hepta.ndu.r14.two-stage.full-law',seed=seed,method=method,source=sources(),
              parent='395496e26a425fc60aa7e2872476b575031bdcae',
              gate='rational-certified theta-distance <=1e-6',cap_cpu_seconds=CAP,
              support_size=5,preference_count=2,branch_count=4,oracle_training_labels=False)
    ph=write_json(out/'PLAN.json',plan)
    write_json(out/'STARTED.json',dict(plan_sha256=ph))
    ref=certificate();distance=__import__('fractions').Fraction(ref['distance_to_unique_global_optimum_upper'])
    store_array(out/'INITIAL.npy',initial(seed))
    result=fit(seed,method,distance)
    store_array(out/'WEIGHTS.npy',np.asarray(result['selected']))
    report=dict(plan_sha256=ph,initial_sha256=sha(initial(seed).tobytes()),
                selected_sha256=sha(np.asarray(result['selected']).tobytes()),result=result,
                overall_cpu=time.process_time()-begin[1],overall_wall=time.perf_counter()-begin[0],
                process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                parameter_count=2,source=sources(),full_flops=None,energy_joules=None,
                native_device=False,production_authorized=False)
    if report['source']!=plan['source']:raise ValueError('source drift')
    write_json(out/'REPORT.json',report)
    print(json.dumps(dict(name=case_name(plan),success=result['success'],
                          quality_cpu=result['first_quality_cpu'],fit_cpu=result['cpu'])),flush=True)

def sweep(out):
    out.mkdir(parents=True,exist_ok=False)
    ref=certificate()
    write_json(out/'CERTIFICATE.json',ref)
    ph=write_json(out/'PLAN.json',dict(cases=cases(),source=sources(),cap=CAP,
            quality_radius='1/1000000',full_law_size=40,
            candidate_error_bound=ref['distance_to_unique_global_optimum_upper']))
    done=[];start=time.perf_counter()
    for spec in cases():
        name=case_name(spec)
        now=time.perf_counter();before=resource.getrusage(resource.RUSAGE_CHILDREN)
        cmd=[sys.executable,str(HERE/'sweep.py'),'trial','--out',str(out/name),
             '--seed',str(spec['seed']),'--method',spec['method']]
        with (out/(name+'.log')).open('xb') as log:
            try:
                r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=90,
                   env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1'))
                status='completed' if r.returncode==0 else 'failed'
                ret=r.returncode
            except (subprocess.TimeoutExpired,OSError) as exc:
                status='failed';ret=None
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        rec=dict(case=spec,name=name,status=status,returncode=ret,
                 child_wall=time.perf_counter()-now,
                 child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
        if status=='completed':rec['report_sha256']=sha((out/name/'REPORT.json').read_bytes())
        done.append(rec)
        write_json(out/(name+'.completion.json'),rec)
        print(json.dumps(rec,sort_keys=True),flush=True)
    fails=sum(row['status']!='completed' for row in done)
    write_json(out/'COMPLETE.json',dict(plan_sha256=ph,completed=len(done)-fails,failed=fails,
               census=done,whole_wall=time.perf_counter()-start,whole_child_cpu=sum(r['child_cpu'] for r in done)))
    if fails:raise SystemExit('failed runs preserved')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('trial','sweep'))
    p.add_argument('--out',type=Path,required=True);p.add_argument('--seed',type=int,default=11)
    p.add_argument('--method',choices=METHODS,default='adam');arg=p.parse_args()
    if arg.mode=='sweep':sweep(arg.out)
    else:execute(arg.out,arg.seed,arg.method)
