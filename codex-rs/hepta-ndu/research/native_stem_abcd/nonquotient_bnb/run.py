"""R19 complete, fresh-process 64-case matched fit records, no oracle during training."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(key,'1')
import argparse,hashlib,json,platform,resource,subprocess,sys,time
from pathlib import Path
import numpy as np
from fitters import fit,CAP,INITIALS,METHODS
from model import full,leaves,independent_direct
ROOT=Path(__file__).resolve().parent
PARENT=ROOT.parent/'asymmetric_2d'
CORE=('model.py','fitters.py','run.py','global_bound.py')
PROTOCOL_COMMIT='dfc8a50c329c75266ab3251f6040326f4e68ba62'

def sha(b):return hashlib.sha256(b).hexdigest()
def sources():
    r={k:sha((ROOT/k).read_bytes()) for k in CORE}
    for k in ('problem.py','certificate.py'):
        r['parent/'+k]=sha((PARENT/k).read_bytes())
    return r

def dump(path,obj):
    b=(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    with path.open('xb') as f:f.write(b)
    return sha(b)

def save(path,**kw):
    with path.open('xb') as f:np.savez_compressed(f,**kw)

def specs():
    out=[]
    for seed,initial in enumerate(INITIALS):
        for arm in ('nonquotient','control'):
            methods=list(METHODS)
            rotation=(seed+int(arm=='control'))%len(methods)
            for method in methods[rotation:]+methods[:rotation]:
                out.append(dict(seed=seed,initial=list(initial),arm=arm,method=method))
    return out

def name(s):return f"s{s['seed']}-{s['arm']}-{s['method']}"

def trial(out,s,expected):
    out.mkdir(parents=True,exist_ok=False)
    begin=time.process_time();start_wall=time.perf_counter()
    if sources()!=expected:raise ValueError('source drift before fit')
    initial=np.array(s['initial'],dtype='<f8')
    eta=1/25 if s['arm']=='nonquotient' else 0.
    h=dump(out/'PLAN.json',dict(schema='hepta.ndu.nonquotient.r19',spec=s,
           source_sha=expected,protocol_commit=PROTOCOL_COMMIT,
           fit_cap_cpu=CAP,reference_used_in_fit=False))
    save(out/'INITIAL.npz',theta=initial)
    fitout=fit(initial,s['method'],eta)
    theta=np.asarray(fitout['theta'],dtype='<f8')
    hist=fitout['history']
    save(out/'WEIGHTS.npz',theta=theta)
    save(out/'CHECKPOINTS.npz',theta=np.array([h[0] for h in hist]),
         cpu=np.array([h[1] for h in hist]),cost=np.array([h[2] for h in hist]))
    seal=dict(plan=h,initial=sha(initial.tobytes()),weights=sha(theta.tobytes()),
              checkpoints=sha((out/'CHECKPOINTS.npz').read_bytes()),
              fit_cpu=fitout['fit_cpu'],fit_wall=fitout['fit_wall'],
              status=fitout['status'])
    dump(out/'FIT_SEAL.json',seal)
    save(out/'LEAVES.npz',values=leaves(theta,eta))
    v,g,H=full(theta,eta)
    report=dict(spec=s,plan_sha=h,source_sha=expected,initial_sha=seal['initial'],
         weights_sha=seal['weights'],leaves_sha=sha((out/'LEAVES.npz').read_bytes()),
         final_cost=v,independent_full_tree_cost=independent_direct(theta,eta),
         gradient=g.tolist(),hessian=H.tolist(),
         fit_cpu=fitout['fit_cpu'],fit_wall=fitout['fit_wall'],
         fit_status=fitout['status'],counts=fitout['counts'],
         fit_peak_rss=fitout['fit_peak_rss'],
         checkpoints=len(hist),whole_child_cpu=time.process_time()-begin,
         whole_child_wall=time.perf_counter()-start_wall,
         process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
         fitted_with_global_reference=False,quality_assigned_before_fit=False,
         global_qualification=None,flops=None,energy_joules=None,gpu_peak_bytes=None,
         platform=platform.platform())
    if sources()!=expected:raise ValueError('source drift after fit')
    dump(out/'REPORT.json',report)
    print(json.dumps(dict(name=name(s),fit_cpu=report['fit_cpu'],
          cost=report['final_cost'],checks=report['checkpoints'])),flush=True)

def sweep(out):
    out.mkdir(parents=True,exist_ok=False)
    before=time.perf_counter();expected=sources()
    ph=dump(out/'PLAN.json',dict(specs=specs(),source_sha=expected,
          protocol_commit=PROTOCOL_COMMIT,fit_cap_cpu=CAP))
    rows=[]
    for s in specs():
        nm=name(s);start=time.perf_counter();prior=resource.getrusage(resource.RUSAGE_CHILDREN)
        cmd=[sys.executable,str(Path(__file__).resolve()),'trial',
             '--out',str(out/nm),'--seed',str(s['seed']),
             '--arm',s['arm'],'--method',s['method']]
        row=dict(name=nm,spec=s)
        with (out/(nm+'.log')).open('xb') as log:
            try:
                p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=30)
                row.update(status='completed' if p.returncode==0 else 'failed',returncode=p.returncode)
            except subprocess.TimeoutExpired:
                row.update(status='timeout',returncode=None)
            except OSError as e:row.update(status='launch_failed',returncode=None,error=str(e))
        nxt=resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(child_cpu=nxt.ru_utime+nxt.ru_stime-prior.ru_utime-prior.ru_stime,
                   child_wall=time.perf_counter()-start)
        if row['status']=='completed':row['report_sha']=sha((out/nm/'REPORT.json').read_bytes())
        rows.append(row);dump(out/(nm+'.completion.json'),row)
        print(json.dumps(dict(case=nm,status=row['status'],child_cpu=row['child_cpu'])),flush=True)
    failures=sum(r['status']!='completed' for r in rows)
    dump(out/'COMPLETE.json',dict(plan_sha=ph,entries=rows,
         completed=len(rows)-failures,failed=failures,
         child_cpu=sum(r['child_cpu'] for r in rows),
         wall=time.perf_counter()-before))
    if failures:raise SystemExit('completed with failures preserved')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('trial','sweep'))
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seed',type=int,default=0);p.add_argument('--arm',choices=('nonquotient','control'),default='nonquotient')
    p.add_argument('--method',choices=METHODS,default='adam')
    args=p.parse_args()
    if args.mode=='sweep':sweep(args.out)
    else:trial(args.out,dict(seed=args.seed,initial=list(INITIALS[args.seed]),arm=args.arm,method=args.method),sources())
