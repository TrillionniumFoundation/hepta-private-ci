"""R21 frozen complete 3-width x8 starts x5 solvers =120 fresh-process fits.

No certificate or best-known optimum enters fitting. All quality classification
is applied by the separately frozen read-only audit after results are sealed.
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(key,'1')
import argparse,hashlib,json,platform,resource,subprocess,sys,time
from pathlib import Path
import numpy as np
from model import full,independent_full,leaf_table,INITIALS,METHODS
from fitters import fit,CAP
ROOT=Path(__file__).resolve().parent
CORE=('model.py','fitters.py','run.py','global_interval.py','test_math.py','PROTOCOL.md')
PROTOCOL_COMMIT='14dbf7ffdbfac43c81dfe355f644e8b11f383266'

def sha(b):return hashlib.sha256(b).hexdigest()
def sources():return {name:sha((ROOT/name).read_bytes()) for name in CORE}
def dump(p,obj):
    buf=(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with p.open('xb') as f:f.write(buf)
    return sha(buf)
def save(p,**kw):
    with p.open('xb') as f:np.savez_compressed(f,**kw)
def initial_for(width,seed):
    if width not in (2,3,4) or seed not in range(8):raise ValueError('invalid width/seed')
    return np.array((*INITIALS[seed],*(0.,)*(width-2)),dtype='<f8')
def specs():
    rows=[]
    for seed in range(8):
      for width in (2,3,4):
       methods=list(METHODS)
       rotation=(seed+width)%len(methods)
       for method in methods[rotation:]+methods[:rotation]:
        rows.append(dict(seed=seed,width=width,method=method))
    return rows
def name(r):return f'w{r["width"]}-s{r["seed"]}-{r["method"]}'
def trial(path,s,expected):
    path.mkdir(parents=True,exist_ok=False)
    whole_cpu=time.process_time();whole_wall=time.perf_counter()
    if sources()!=expected:raise ValueError('drifted executed source before fit')
    initial=initial_for(s['width'],s['seed'])
    plan=dict(schema='hepta.ndu.width4.r21',spec=s,fit_cap_cpu=CAP,
        source_sha=expected,protocol_commit=PROTOCOL_COMMIT,
        reference_used_in_fit=False,initial=list(map(float,initial)))
    ph=dump(path/'PLAN.json',plan);save(path/'INITIAL.npz',theta=initial)
    fit_result=fit(initial,s['method'])
    theta=np.asarray(fit_result['theta'],dtype='<f8').copy();history=fit_result['history']
    save(path/'WEIGHTS.npz',theta=theta)
    save(path/'CHECKPOINTS.npz',theta=np.asarray([x[0] for x in history],dtype='<f8'),
         cpu=np.asarray([x[1] for x in history],dtype='<f8'),
         cost=np.asarray([x[2] for x in history],dtype='<f8'))
    stamp=dict(plan_sha=ph,initial_sha=sha(initial.tobytes()),weights_sha=sha(theta.tobytes()),
      checkpoint_file_sha=sha((path/'CHECKPOINTS.npz').read_bytes()),
      fit_cpu=fit_result['fit_cpu'],fit_wall=fit_result['fit_wall'],status=fit_result['status'])
    dump(path/'FIT_SEAL.json',stamp)
    save(path/'LEAVES.npz',values=leaf_table(theta))
    obj,gr,H=full(theta)
    reference=independent_full(theta)
    if not np.isfinite([obj,reference,*gr,*H.ravel()]).all():raise FloatingPointError('nonfinite frozen output')
    report=dict(schema='hepta.ndu.width4.r21.result',spec=s,plan_sha=ph,
      source_sha=expected,initial_sha=stamp['initial_sha'],weights_sha=stamp['weights_sha'],
      checkpoint_file_sha=stamp['checkpoint_file_sha'],
      leaves_sha=sha((path/'LEAVES.npz').read_bytes()),
      final_cost=obj,independent_tree_cost=reference,gradient=gr.tolist(),hessian=H.tolist(),
      fit_cpu=fit_result['fit_cpu'],fit_wall=fit_result['fit_wall'],fit_status=fit_result['status'],
      fit_counts=fit_result['counts'],fit_peak_rss_bytes=fit_result['fit_peak_rss'],
      number_of_checkpoints=len(history),whole_child_cpu=time.process_time()-whole_cpu,
      whole_child_wall=time.perf_counter()-whole_wall,
      whole_child_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
      platform=platform.platform(),
      proof_used_in_fit=False,quality_assigned_before_fit=False,
      global_quality=None,global_FLOP_count=None,energy_joules=None)
    if sources()!=expected:raise ValueError('drifted source after fit')
    dump(path/'REPORT.json',report)
    print(json.dumps(dict(name=name(s),updates=fit_result['counts']['updates'],cost=obj,fit_cpu=fit_result['fit_cpu'])),flush=True)
def sweep(out):
    out.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();expected=sources()
    ph=dump(out/'CENSUS_PLAN.json',dict(schema='hepta.ndu.width4.r21.sweep',
      specs=specs(),source_sha=expected,protocol_commit=PROTOCOL_COMMIT,fit_cap_cpu=CAP))
    rows=[]
    for s in specs():
        nm=name(s);start=time.perf_counter();before=resource.getrusage(resource.RUSAGE_CHILDREN)
        cmd=[sys.executable,str(Path(__file__).resolve()),'trial','--out',str(out/nm),
           '--width',str(s['width']),'--seed',str(s['seed']),'--method',s['method']]
        row=dict(name=nm,spec=s)
        with (out/(nm+'.log')).open('xb') as log:
            try:
                p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=45)
                row.update(status='completed' if p.returncode==0 else 'failed',returncode=p.returncode)
            except subprocess.TimeoutExpired:row.update(status='timeout',returncode=None)
            except OSError as exc:row.update(status='launch_failed',returncode=None,error=str(exc))
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                   child_wall=time.perf_counter()-start)
        if row['status']=='completed':row['report_sha']=sha((out/nm/'REPORT.json').read_bytes())
        rows.append(row);dump(out/(nm+'.completion.json'),row)
        print(json.dumps(dict(name=nm,status=row['status'],child_cpu=row['child_cpu'],completed=len(rows))),flush=True)
    failures=sum(r['status']!='completed' for r in rows)
    dump(out/'COMPLETE.json',dict(plan_sha=ph,cases=rows,complete=len(rows)-failures,
      failures=failures,wall=time.perf_counter()-started,
      child_cpu=sum(r['child_cpu'] for r in rows)))
    if failures:raise SystemExit('nonzero execution failures retained')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('sweep','trial'))
    p.add_argument('--out',required=True,type=Path);p.add_argument('--width',type=int,default=2)
    p.add_argument('--seed',type=int,default=0);p.add_argument('--method',choices=METHODS,default='adam')
    args=p.parse_args()
    if args.mode=='sweep':sweep(args.out)
    else:trial(args.out,dict(width=args.width,seed=args.seed,method=args.method),sources())
