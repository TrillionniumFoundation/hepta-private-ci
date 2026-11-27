"""R18 fixed 64-case new-process training with frozen outputs before audit."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(key,'1')
import argparse,csv,hashlib,json,platform,resource,subprocess,sys,time
from pathlib import Path
import numpy as np
from solver import fit,METHODS,CAP
from problem import INITIALS,leaf,direct,objective
ROOT=Path(__file__).resolve().parent
CORE=('certificate.py','problem.py','solver.py','run.py')
PROTOCOL_COMMIT='4b982a80c3e246debbb2ae80c68f075fd531449a'

def sha(b):return hashlib.sha256(b).hexdigest()
def sources():return {k:sha((ROOT/k).read_bytes()) for k in CORE}
def dump(path,obj):
    data=(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n').encode('utf8')
    with path.open('xb') as file:file.write(data)
    return sha(data)
def save(path,**arrays):
    with path.open('xb') as f:np.savez_compressed(f,**arrays)
def specs():
    allcases=[]
    for idx,start in enumerate(INITIALS):
        for variant in ('asymmetric','zero_shift'):
            methods=list(METHODS)
            methods=methods[(idx+(variant=='zero_shift'))%4:]+methods[:(idx+(variant=='zero_shift'))%4]
            for method in methods:
                allcases.append(dict(seed=idx,initial=list(start),variant=variant,method=method))
    return allcases

def name(s):return f"s{s['seed']}-{s['variant']}-{s['method']}"

def branch_array(theta,shift):
    a,b=theta
    arr=np.array([[x,p0,e1,e2,*[leaf(a,b,x,p0,e1,e2,shift)[k]
                      for k in ('h1','h2','p1','p2','stage','terminal')]]
                  for x in (-1,1) for p0 in (0,1) for e1 in (-1,1) for e2 in (-1,1)],dtype='<f8')
    return arr

def trial(folder,spec,expected):
    folder.mkdir(parents=True,exist_ok=False)
    begin_cpu,begin_wall=time.process_time(),time.perf_counter()
    if sources()!=expected:raise RuntimeError('source drift before fit')
    initial=np.asarray(spec['initial'],dtype='<f8')
    seal_plan=dict(schema='hepta.ndu.asymmetric-2d.r18',spec=spec,source_sha=expected,
                   protocol_commit=PROTOCOL_COMMIT,cap_cpu=CAP,reference_used_in_fit=False)
    plan_hash=dump(folder/'PLAN.json',seal_plan)
    save(folder/'INITIAL.npz',theta=initial)
    shift=1. if spec['variant']=='asymmetric' else 0.
    trained=fit(initial,spec['method'],shift)
    weights=np.asarray(trained['theta'],dtype='<f8')
    hist=trained['history']
    history=np.array([q[0] for q in hist],dtype='<f8')
    times=np.array([q[1] for q in hist],dtype='<f8')
    costs=np.array([q[2] for q in hist],dtype='<f8')
    save(folder/'WEIGHTS.npz',theta=weights)
    save(folder/'CHECKPOINTS.npz',theta=history,cpu=times,cost=costs)
    seal=dict(plan=plan_hash,initial=sha(initial.tobytes()),weights=sha(weights.tobytes()),
              checkpoints=sha((folder/'CHECKPOINTS.npz').read_bytes()),fit_cpu=trained['cpu'],
              fit_wall=trained['wall'],status=trained['status'])
    dump(folder/'FIT_SEAL.json',seal)
    # Quality and reference calculations are *deliberately absent* in training.
    values=branch_array(weights,shift)
    save(folder/'LEAVES.npz',values=values)
    J,g,H=objective(weights,shift)
    report=dict(spec=spec,plan_sha=plan_hash,source_sha=expected,
                initial_sha=seal['initial'],weights_sha=seal['weights'],
                leaves_sha=sha((folder/'LEAVES.npz').read_bytes()),
                final_cost=float(J),raw_terminal_direct=float(direct(weights,shift)),
                final_gradient=g.tolist(),final_hessian=H.tolist(),
                fit_cpu=trained['cpu'],fit_wall=trained['wall'],fit_peak_rss=trained['fit_peak_rss'],
                fit_status=trained['status'],counters=trained['counters'],
                checkpoint_count=len(hist),
                whole_process_cpu=time.process_time()-begin_cpu,
                whole_process_wall=time.perf_counter()-begin_wall,
                process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                full_flops=None,energy_joules=None,gpu_peak_bytes=None,
                reference_in_fitting=False,qualification=None,
                platform=platform.platform(),python=sys.version)
    if sources()!=expected:raise RuntimeError('source drift after fit')
    dump(folder/'REPORT.json',report)
    print(json.dumps(dict(name=name(spec),fit_cpu=trained['cpu'],fit_status=trained['status'],
                          final_cost=float(J),checkpoints=len(hist))),flush=True)

def sweep(out):
    out.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();expected=sources()
    plan_hash=dump(out/'PLAN.json',dict(specs=specs(),source_sha=expected,
                                      protocol_commit=PROTOCOL_COMMIT,cap_cpu=CAP))
    rows=[]
    for s in specs():
        nm=name(s);begin=time.perf_counter();prior=resource.getrusage(resource.RUSAGE_CHILDREN)
        args=[sys.executable,str(Path(__file__).resolve()),'trial','--out',str(out/nm),
              '--seed',str(s['seed']),'--method',s['method'],'--variant',s['variant']]
        item=dict(name=nm,spec=s)
        with (out/(nm+'.log')).open('xb') as log:
            try:
                p=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=30)
                item.update(status='completed' if p.returncode==0 else 'failed',returncode=p.returncode)
            except subprocess.TimeoutExpired:
                item.update(status='timeout',returncode=None)
            except OSError as exc:
                item.update(status='launch_failed',error=str(exc),returncode=None)
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        item.update(child_wall=time.perf_counter()-begin,
                    child_cpu=after.ru_utime+after.ru_stime-prior.ru_utime-prior.ru_stime)
        if item['status']=='completed':item['report_sha']=sha((out/nm/'REPORT.json').read_bytes())
        rows.append(item);dump(out/(nm+'.completion.json'),item)
        print(json.dumps(dict(name=nm,status=item['status'],child_cpu=item['child_cpu'])),flush=True)
    fail=sum(i['status']!='completed' for i in rows)
    dump(out/'COMPLETE.json',dict(plan_sha=plan_hash,entries=rows,completed=len(rows)-fail,
         failed=fail,whole_child_cpu=sum(i['child_cpu'] for i in rows),wall=time.perf_counter()-start))
    if fail:raise SystemExit('execution failures saved')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('trial','sweep'))
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--seed',default=0,type=int);p.add_argument('--method',default='adam',choices=METHODS)
    p.add_argument('--variant',default='asymmetric',choices=('asymmetric','zero_shift'))
    a=p.parse_args()
    if a.mode=='sweep':sweep(a.out)
    else:trial(a.out,dict(seed=a.seed,initial=list(INITIALS[a.seed]),method=a.method,variant=a.variant),sources())
