"""R15 create-only fresh-process full factorial; all losses and certificates kept."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(key,'1')
import argparse
import hashlib
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from problem import XS,PS,EPS,population,stage_values,branch
from certificate import proof
from solver import SEEDS,METHODS,ARMS,CAP_CPU,fit,initial

HERE=Path(__file__).resolve().parent
SOURCE=('problem.py','intervals.py','certificate.py','mp_scout.py','solver.py','sweep.py',
        'test_math.py','audit.py','test_tamper.py','PROTOCOL.md')

def sha(data):return hashlib.sha256(data).hexdigest()

def source_hashes():return {name:sha((HERE/name).read_bytes()) for name in SOURCE}

def dump(path,info):
    data=(json.dumps(info,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with path.open('xb') as f:f.write(data)
    return sha(data)

def save(path, **kwargs):
    with path.open('xb') as f:np.savez_compressed(f,**kwargs)

def cases():
    out=[]
    for j,arm in enumerate(ARMS):
        for i,seed in enumerate(SEEDS):
            shift=(i+j)%len(METHODS)
            for method in METHODS[shift:]+METHODS[:shift]:
                out.append(dict(seed=seed,method=method,arm=arm))
    return out

def name_for(s):return f"{s['arm']}-s{s['seed']}-{s['method']}"

def oracle_arrays(theta,arm):
    osc=arm=='oscillatory'
    cost=[stage_values(theta,x,p0,oscillatory=osc) for x in XS for p0 in PS]
    branches=[float(branch(float(theta[0]),float(theta[1]),x,p0,e1,e2,oscillatory=osc)['l2'])
             for x in XS for p0 in PS for e1 in EPS for e2 in EPS]
    return np.array(cost,dtype=np.float64),np.array(branches,dtype=np.float64)

def trial(out,case):
    out.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter(),time.process_time()
    source=source_hashes()
    cert=proof()
    plan=dict(schema='hepta.ndu.r15.nonlinear-forward',case=case,parent='7f6d69934ee042f0a2d20b6d224ea8a08e0e037b',
              protocol_sha256=source['PROTOCOL.md'],source=source,
              support=5,initial_preferences=2,branch_paths=4,parameter_box=['-2','2'],
              main_certificate_distance=cert['true_global_optimum_distance_upper'],
              cap_cpu_seconds=CAP_CPU,independent_reference_used_for_fit=False)
    ph=dump(out/'PLAN.json',plan)
    dump(out/'STARTED.json',dict(plan_sha256=ph))
    initial_theta=initial(case['seed'])
    save(out/'INITIAL.npz',theta=initial_theta)
    fit_report=fit(**case,radius=__import__('fractions').Fraction(cert['true_global_optimum_distance_upper']))
    theta=np.array(fit_report['selected'])
    save(out/'WEIGHTS.npz',theta=theta)
    # Seal fit BEFORE independently reproduced root/path predictions.
    fit_sha=dump(out/'FIT.json',fit_report)
    dump(out/'FIT_SEAL.json',dict(initial_sha256=sha(initial_theta.tobytes()),
                                selected_sha256=sha(theta.tobytes()),fit_sha256=fit_sha))
    now=time.process_time()
    values,branches=oracle_arrays(theta,case['arm'])
    save(out/'PREDICTIONS.npz',roots=values,branch_costs=branches)
    pred_sha=sha((out/'PREDICTIONS.npz').read_bytes())
    dump(out/'PREDICTIONS_SEAL.json',dict(sha256=pred_sha,selected_sha256=sha(theta.tobytes())))
    independent=population(theta,oscillatory=case['arm']=='oscillatory')
    report=dict(case=case,plan_sha256=ph,source=source,
                initial_sha256=sha(initial_theta.tobytes()),
                selected_sha256=sha(theta.tobytes()),prediction_sha256=pred_sha,
                selected_has_changed=not np.array_equal(theta,initial_theta),
                fit=fit_report,final_independent_cost=float(values.mean()),
                final_direct_cost=float(independent[0]),
                final_direct_gradient=independent[1].tolist(),
                final_direct_hessian_eigenvalues=np.linalg.eigvalsh(independent[2]).tolist(),
                evaluation_cpu=time.process_time()-now,
                overall_cpu=time.process_time()-started[1],overall_wall=time.perf_counter()-started[0],
                process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                environment=dict(python=sys.version,numpy=np.__version__,platform=platform.platform()),
                energy_joules=None,full_flops=None,production_authorized=False)
    if source_hashes()!=source:raise RuntimeError('source drift')
    dump(out/'REPORT.json',report)
    print(json.dumps(dict(case=name_for(case),status=fit_report['status'],
                          cost=report['final_independent_cost'],
                          quality=fit_report['certified_gate_success'],
                          stationary=fit_report['stress_numerical_local_candidate'])),flush=True)

def sweep(out):
    out.mkdir(parents=True,exist_ok=False)
    cert=proof()
    dump(out/'CERTIFICATE.json',cert)
    pre=(HERE/'PROTOCOL.md').read_bytes()
    plan=dict(schema='hepta.ndu.r15.sweep',source=source_hashes(),cases=cases(),
              protocol_sha256=sha(pre),main_certification=cert,
              cap_cpu_seconds=CAP_CPU,independent_external_preregistration=False)
    ph=dump(out/'PLAN.json',plan)
    census=[];started=time.perf_counter()
    for s in cases():
        name=name_for(s)
        before=resource.getrusage(resource.RUSAGE_CHILDREN)
        now=time.perf_counter()
        cmd=[sys.executable,str(HERE/'sweep.py'),'trial','--out',str(out/name),
             '--seed',str(s['seed']),'--method',s['method'],'--arm',s['arm']]
        row=dict(case=s,name=name)
        with (out/(name+'.log')).open('xb') as f:
            try:
                r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=90,
                     env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1'))
                row['returncode']=r.returncode
                row['status']='completed' if r.returncode==0 else 'failed'
            except (OSError,subprocess.TimeoutExpired) as exc:
                row.update(status='failed',returncode=None,error=str(exc))
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        row['child_cpu']=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime
        row['child_wall']=time.perf_counter()-now
        if row['status']=='completed':row['report_sha256']=sha((out/name/'REPORT.json').read_bytes())
        dump(out/(name+'.completion.json'),row)
        census.append(row)
        print(json.dumps(row,sort_keys=True),flush=True)
    fails=sum(r['status']!='completed' for r in census)
    dump(out/'COMPLETE.json',dict(plan_sha256=ph,census=census,completed=len(census)-fails,
                                 failed=fails,whole_wall=time.perf_counter()-started,
                                 child_cpu=sum(r['child_cpu'] for r in census)))
    if fails:raise SystemExit('failed runs retained; no fake complete sweep')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('sweep','trial'))
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seed',type=int,default=11)
    p.add_argument('--method',choices=METHODS,default='newton')
    p.add_argument('--arm',choices=ARMS,default='certified')
    a=p.parse_args()
    if a.mode=='sweep':sweep(a.out)
    else:trial(a.out,dict(seed=a.seed,method=a.method,arm=a.arm))
