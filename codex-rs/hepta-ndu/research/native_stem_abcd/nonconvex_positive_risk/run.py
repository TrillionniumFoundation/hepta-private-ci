"""R16 complete 8x4 process census, signed weights and sealed pre-audit outcomes."""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
 os.environ.setdefault(k,'1')
import argparse,csv,hashlib,json,resource,subprocess,sys,time
from pathlib import Path
import numpy as np
from solver import fit,INITIALS,METHODS,CPU_CAP
from problem import objective,derivative,populations_agree
HERE=Path(__file__).resolve().parent

def sha(b):return hashlib.sha256(b).hexdigest()
def write(path,obj):
 b=(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
 with path.open('xb') as f:f.write(b)
 return sha(b)
def npz(path,**kw):
 with path.open('xb') as f:np.savez_compressed(f,**kw)
def sources():return {p.name:sha(p.read_bytes()) for p in HERE.glob('*.py')}
def case_name(k,m):return f's{k}-{m}'
def cases():return [(k,m) for k in range(8) for m in METHODS]

def trial(out,k,method,protocol):
 out.mkdir(parents=True,exist_ok=False)
 start=time.process_time()
 initial=np.array(INITIALS[k],dtype=np.float64)
 plan=dict(kind='hepta.ndu.nonconvex-positive-risk.r16',index=k,method=method,
           initial=[float(x) for x in initial],cpu_cap=CPU_CAP,source_sha=sources(),protocol=protocol)
 h=write(out/'PLAN.json',plan)
 npz(out/'INITIAL.npz',theta=initial)
 result=fit(initial,method)
 theta=np.asarray(result['theta'],np.float64)
 npz(out/'WEIGHTS.npz',theta=theta)
 npz(out/'CHECKPOINTS.npz',theta=np.asarray([c['theta'] for c in result['checkpoints']],dtype=np.float64),
     cpu=np.array([c['cpu'] for c in result['checkpoints']],dtype=np.float64),
     cost=np.array([c['cost'] for c in result['checkpoints']],dtype=np.float64))
 seal=dict(plan_sha=h,initial_sha=sha(initial.tobytes()),weights_sha=sha(theta.tobytes()),
           checkpoint_sha=sha((out/'CHECKPOINTS.npz').read_bytes()),fit_cpu=result['cpu'],
           fit_wall=result['wall'],fit_status=result['status'],fit_counts=result['counts'])
 write(out/'FIT_SEAL.json',seal)
 # The global certificate, optimum, and global classification are intentionally
 # NOT imported, computed or used by any fitting child.
 final=objective(theta);g,H=derivative(theta)
 if not np.isfinite([final,*g,*H.flatten()]).all():raise FloatingPointError('nonfinite final model')
 eval1,eval2=populations_agree(theta)
 write(out/'FIT_REPORT.json',dict(plan_sha=h,initial_sha=seal['initial_sha'],weights_sha=seal['weights_sha'],
            index=k,method=method,final_theta=theta.tolist(),final_objective=float(final),
            independent_branch_objective=float(eval2),grad_inf=float(np.max(np.abs(g))),
            min_hessian_eigenvalue=float(np.linalg.eigvalsh(H)[0]),
            number_of_checkpoints=len(result['checkpoints']),
            fit_cpu=result['cpu'],fit_wall=result['wall'],fit_status=result['status'],
            fit_counts=result['counts'],fit_peak_rss=result['rss_peak_bytes'],
            whole_child_cpu=time.process_time()-start,
            proof_used_in_fit=False,global_classification_at_fit_time=None))
 print(json.dumps(dict(index=k,method=method,status=result['status'],theta=theta.tolist(),cost=float(final))),flush=True)

def sweep(out,protocol):
 out.mkdir(parents=True,exist_ok=False)
 source=sources()
 plan=dict(cases=[dict(index=k,method=m) for k,m in cases()],initials=INITIALS,
           methods=METHODS,source_sha=source,cpu_cap=CPU_CAP,protocol=protocol)
 ph=write(out/'CENSUS_PLAN.json',plan)
 entries=[];cpu_start=time.process_time();wall_start=time.perf_counter()
 for k,m in cases():
  name=case_name(k,m);begin=time.perf_counter();u=resource.getrusage(resource.RUSAGE_CHILDREN)
  cmd=[sys.executable,str(Path(__file__).resolve()),'trial','--out',str(out/name),
       '--index',str(k),'--method',m,'--protocol',protocol]
  with (out/(name+'.log')).open('xb') as log:
   try:
    p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=30)
    status='completed' if p.returncode==0 else 'execution_failed'
   except subprocess.TimeoutExpired:
    status='timeout';p=None
  v=resource.getrusage(resource.RUSAGE_CHILDREN)
  item=dict(index=k,method=m,name=name,status=status,returncode=p.returncode if p else None,
            child_wall=time.perf_counter()-begin,
            child_cpu=v.ru_utime+v.ru_stime-u.ru_utime-u.ru_stime)
  if status=='completed':item['report_sha']=sha((out/name/'FIT_REPORT.json').read_bytes())
  entries.append(item);write(out/(name+'.done.json'),item)
  print(json.dumps(item),flush=True)
 write(out/'COMPLETE.json',dict(plan_sha=ph,entries=entries,complete=sum(e['status']=='completed' for e in entries),
       failed=sum(e['status']!='completed' for e in entries),wall=time.perf_counter()-wall_start,
       cpu_child=sum(e['child_cpu'] for e in entries),driver_cpu=time.process_time()-cpu_start))
 if any(e['status']!='completed' for e in entries):raise SystemExit('execution errors retained')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('trial','sweep'))
 p.add_argument('--out',required=True,type=Path);p.add_argument('--index',type=int,default=0)
 p.add_argument('--method',choices=METHODS,default='adam');p.add_argument('--protocol',required=True)
 a=p.parse_args()
 if a.mode=='trial':trial(a.out,a.index,a.method,a.protocol)
 else:sweep(a.out,a.protocol)
