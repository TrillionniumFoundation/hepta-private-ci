"""R17 create-only 64-case source-bound census, checkpoint seals and separate evaluation."""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ.setdefault(k,'1')
import argparse,hashlib,json,resource,subprocess,sys,time
from pathlib import Path
import numpy as np
from solver import METHODS,INITIALS,CPU_CAP,fit
from problem import objective,direct,transfer
HERE=Path(__file__).resolve().parent
PARENT='3c83e6546b5650a36a9a114fa15a92a4b98eb369'
PROTOCOL='52b4160c009c10d55b059c2fddb5af71ba5c5c81'

def digest(b):return hashlib.sha256(b).hexdigest()
def write(p,o):
    data=(json.dumps(o,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    with p.open('xb') as f:f.write(data)
    return digest(data)
def npz(p,**kwargs):
    with p.open('xb') as f:np.savez_compressed(f,**kwargs)
def sources():
    return {p.name:digest(p.read_bytes()) for p in sorted(HERE.glob('*.py'))}
def specs():
    result=[]
    for i in range(8):
        methods=METHODS[i%4:]+METHODS[:i%4]
        for arch in ('nonproduct','product_only'):
            for method in methods:result.append(dict(seed=i,arch=arch,method=method))
    return result
def name(s):return f"s{s['seed']}-{s['arch']}-{s['method']}"
def kappa(s):return .25 if s['arch']=='nonproduct' else 0.

def trial(dest,s):
    t0=time.process_time();w0=time.perf_counter()
    dest.mkdir(parents=True,exist_ok=False)
    ini=np.array(INITIALS[s['seed']],dtype=np.float64)
    plan=dict(schema='hepta.ndu.nonproduct-symmetry.r17',case=s,initial=ini.tolist(),cpu_cap=CPU_CAP,
              kappa=kappa(s),source=sources(),protocol_commit=PROTOCOL,parent_commit=PARENT)
    ph=write(dest/'PLAN.json',plan)
    npz(dest/'INITIAL.npz',theta=ini)
    fitinfo=fit(ini,s['method'],kappa(s))
    final=np.asarray(fitinfo['theta'],dtype='<f8')
    npz(dest/'WEIGHTS.npz',theta=final)
    npz(dest/'CHECKPOINTS.npz',theta=fitinfo['weights'],cpu=fitinfo['checkpoint_cpu'],cost=fitinfo['checkpoint_cost'])
    sealed=dict(plan_sha=ph,initial_sha=digest(ini.tobytes()),weight_sha=digest(final.tobytes()),
                checkpoints_sha=digest((dest/'CHECKPOINTS.npz').read_bytes()),
                fit_cpu=fitinfo['fit_cpu'],fit_wall=fitinfo['fit_wall'],counts=fitinfo['counts'],status=fitinfo['status'])
    write(dest/'FIT_SEAL.json',sealed)
    # All independent diagnostics strictly post-seal; no certificate import at fit stage.
    cost,g,h=objective(final,kappa(s))
    leaf_score=direct(final,kappa(s))
    transfers=transfer(final,kappa(s))
    assert abs(cost-leaf_score)<=1e-12
    assert np.isfinite([cost,*g,*h.flatten(),*transfers.values()]).all()
    rep=dict(plan_sha=ph,case=s,initial_sha=sealed['initial_sha'],weight_sha=sealed['weight_sha'],
        fit=sealed,final=final.tolist(),cost=cost,independent_leaf_cost=leaf_score,
        gradient_inf=float(np.max(np.abs(g))),hessian_min=float(np.linalg.eigvalsh(h)[0]),
        transfers=transfers,num_checkpoints=len(fitinfo['weights']),
        cpu_process=time.process_time()-t0,wall_process=time.perf_counter()-w0,
        peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        source=plan['source'],production_authorized=False)
    if sources()!=plan['source']:raise ValueError('source drift')
    write(dest/'REPORT.json',rep)
    print(json.dumps(dict(name=name(s),cost=cost,fit_cpu=fitinfo['fit_cpu'],status=fitinfo['status'])),flush=True)

def sweep(dest):
    dest.mkdir(parents=True,exist_ok=False)
    p=dict(parent=PARENT,protocol=PROTOCOL,specs=specs(),initials=INITIALS,source=sources(),cap=CPU_CAP,
           scientific_primary='nonproduct vs product_only with common exact reference and raw failures retained')
    ph=write(dest/'SWEEP_PLAN.json',p);start=time.perf_counter()
    results=[]
    for case in specs():
        n=name(case);u=resource.getrusage(resource.RUSAGE_CHILDREN);now=time.perf_counter()
        cmd=[sys.executable,str(Path(__file__).resolve()),'trial','--out',str(dest/n),
             '--seed',str(case['seed']),'--arch',case['arch'],'--method',case['method']]
        item=dict(name=n,case=case)
        with (dest/(n+'.log')).open('xb') as log:
            try:
                run=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=35)
                item.update(status='completed' if run.returncode==0 else 'execution_failed',returncode=run.returncode)
            except subprocess.TimeoutExpired:item.update(status='driver_timeout',returncode=None)
            except OSError as exc:item.update(status='launch_error',returncode=None,error=str(exc))
        v=resource.getrusage(resource.RUSAGE_CHILDREN)
        item.update(child_cpu=v.ru_utime+v.ru_stime-u.ru_utime-u.ru_stime,child_wall=time.perf_counter()-now)
        if item['status']=='completed':item['report_sha']=digest((dest/n/'REPORT.json').read_bytes())
        results.append(item);write(dest/(n+'.done.json'),item)
        print(json.dumps(item),flush=True)
    failed=sum(x['status']!='completed' for x in results)
    write(dest/'COMPLETE.json',dict(plan_sha=ph,results=results,total=len(results),completed=len(results)-failed,
        failed=failed,child_cpu=sum(x['child_cpu'] for x in results),wall=time.perf_counter()-start))
    if failed:raise SystemExit(f'{failed} run failures retained')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('trial','sweep'))
    p.add_argument('--out',type=Path,required=True);p.add_argument('--seed',type=int,default=0)
    p.add_argument('--arch',choices=('nonproduct','product_only'),default='nonproduct')
    p.add_argument('--method',choices=METHODS,default='adam')
    v=p.parse_args()
    if v.mode=='trial':trial(v.out,dict(seed=v.seed,arch=v.arch,method=v.method))
    else:sweep(v.out)
