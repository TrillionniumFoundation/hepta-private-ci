"""R16 exact-head audit: raw bytes, all checkpoints, strict global classification."""
import argparse,csv,hashlib,json,math,sys,time,resource
from pathlib import Path
import numpy as np
def assert_true(flag,msg):
 if not flag:raise ValueError(msg)
def digest(b):return hashlib.sha256(b).hexdigest()
def load(path):return json.loads(path.read_text())
def dump(path,obj):
 path.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')
def audit(source,runs,out):
 started=time.process_time();out.mkdir(parents=True,exist_ok=False)
 sys.path.insert(0,str(source.resolve()))
 import run,solver,problem,certificate
 original_cert=load(runs.parent/'evidence/CERTIFICATE.json') if (runs.parent/'evidence/CERTIFICATE.json').exists() else certificate.certify()
 independent_cert=certificate.certify()
 assert_true(original_cert==independent_cert,'certificate mutated')
 plan=load(runs/'CENSUS_PLAN.json');receipt=load(runs/'COMPLETE.json')
 assert_true(receipt['plan_sha']==digest((runs/'CENSUS_PLAN.json').read_bytes()),'plan hash forged')
 assert_true(plan['source_sha']==run.sources(),'source drift')
 assert_true(len(receipt['entries'])==32 and receipt['complete']==32,'incomplete census')
 assert_true([(e['index'],e['method']) for e in receipt['entries']]==run.cases(),'wrong case order')
 s=float(certificate.S)
 dw=float(__import__('fractions').Fraction(independent_cert['weight_component_error_upper']))
 dr=float(__import__('fractions').Fraction(independent_cert['true_population_excess_upper']))
 jhat=problem.objective([s,s]);rows=[];max_checkpoint_error=0.;max_independent_error=0.;checkpoints=0
 for ent in receipt['entries']:
  assert_true(ent['status']=='completed','failed/hidden case')
  folder=runs/ent['name']
  saved=load(folder/'FIT_REPORT.json');seal=load(folder/'FIT_SEAL.json');trial_plan=load(folder/'PLAN.json')
  assert_true(digest((folder/'FIT_REPORT.json').read_bytes())==ent['report_sha'],'forged report hash')
  assert_true(digest((folder/'PLAN.json').read_bytes())==seal['plan_sha']==saved['plan_sha'],'plan mismatch')
  assert_true(trial_plan['source_sha']==plan['source_sha'] and trial_plan['protocol']==plan['protocol'],'unmatched source/protocol')
  assert_true((trial_plan['index'],trial_plan['method'])==(ent['index'],ent['method']),'case mismatch')
  assert_true(saved.get('proof_used_in_fit') is False and saved.get('global_classification_at_fit_time') is None,'oracle leaked into fitting')
  theta=np.load(folder/'WEIGHTS.npz',allow_pickle=False)['theta'].copy()
  initial=np.load(folder/'INITIAL.npz',allow_pickle=False)['theta'].copy()
  with np.load(folder/'CHECKPOINTS.npz',allow_pickle=False) as h:
   history=h['theta'].copy();history_cpu=h['cpu'].copy();history_cost=h['cost'].copy()
  assert_true(theta.shape==(2,) and initial.shape==(2,),'wrong parameter shape')
  assert_true(np.array_equal(initial,np.array(solver.INITIALS[ent['index']],dtype=np.float64)),'incorrect initial')
  assert_true(digest(theta.tobytes())==seal['weights_sha']==saved['weights_sha'],'weight mismatch')
  assert_true(digest(initial.tobytes())==seal['initial_sha']==saved['initial_sha'],'initial mismatch')
  assert_true(digest((folder/'CHECKPOINTS.npz').read_bytes())==seal['checkpoint_sha'],'checkpoint tampered')
  assert_true(history.shape[0]==len(history_cpu)==len(history_cost)==saved['number_of_checkpoints'],'checkpoint count mismatch')
  assert_true(np.array_equal(history[0],initial) and np.array_equal(history[-1],theta),'initial/final checkpoint mismatch')
  assert_true((np.diff(history_cpu)>=0).all() and history_cpu[-1]<=saved['fit_cpu']+1e-8,'monotone CPU invalid')
  values=np.array([problem.objective(c) for c in history])
  err=float(np.max(np.abs(values-history_cost)));max_checkpoint_error=max(max_checkpoint_error,err)
  assert_true(err<=1e-14,'checkpoint cost mismatch')
  cost=float(problem.objective(theta));g,H=problem.derivative(theta)
  independently=sum(problem.ce_costs(float(theta[0]*theta[1]),x,p) for x in (-1,1) for p in (0,1))/4+float((theta@theta)/4)
  independent_err=abs(independently-cost);max_independent_error=max(max_independent_error,independent_err)
  assert_true(independent_err<=1e-13,'independent branch objective mismatch')
  assert_true(abs(cost-saved['final_objective'])<=1e-14,'falsified final cost')
  assert_true(abs(float(max(abs(g)))-saved['grad_inf'])<=1e-12,'falsified final gradient')
  assert_true(abs(float(np.linalg.eigvalsh(H)[0])-saved['min_hessian_eigenvalue'])<=1e-11,'falsified curvature')
  dist=min(np.linalg.norm(theta-np.array([s,s])),np.linalg.norm(theta+np.array([s,s])))
  upper_distance=dist+math.sqrt(2)*dw
  upper_gap=max(0.,cost-jhat)+dr+2e-15
  numerical_global_quality=bool(upper_distance<=1e-6 and upper_gap<=1e-9)
  if cost<jhat-1e-10:raise ValueError('candidate violates certified global bound')
  checkpoints+=len(history)
  rows.append(dict(name=ent['name'],index=ent['index'],method=ent['method'],a=theta[0],b=theta[1],
     final_cost=cost,loss_lower_bound_violation=max(0,jhat-cost),
     gradient_inf=max(abs(g)),hessian_eigen_min=np.linalg.eigvalsh(H)[0],
     observed_parameter_distance=dist,reference_adjusted_distance_estimate=upper_distance,
     reference_adjusted_gap_estimate=upper_gap,numerical_quality=numerical_global_quality,
     fit_cpu=saved['fit_cpu'],fit_wall=saved['fit_wall'],whole_child_cpu=saved['whole_child_cpu'],
     driver_child_cpu=ent.get('child_cpu'),driver_child_wall=ent.get('child_wall'),
     missing_driver_time=ent.get('external_driver_timeout_after_case',False),
     fit_status=saved['fit_status'],num_checkpoints=len(history),updates=saved['fit_counts']['accepted_changes']))
 for idx in range(8):
  pairs=[]
  for m in solver.METHODS:
   folder=runs/run.case_name(idx,m)
   pairs.append(np.load(folder/'INITIAL.npz',allow_pickle=False)['theta'].tobytes())
  assert_true(len(set(pairs))==1,'pair-wise start differs')
 groups=[]
 for m in solver.METHODS:
  subset=[r for r in rows if r['method']==m]
  groups.append(dict(method=m,denominator=len(subset),quality_successes=sum(r['numerical_quality'] for r in subset),
     median_fit_cpu=np.median([r['fit_cpu'] for r in subset]),
     worst_gap_upper=max(r['reference_adjusted_gap_estimate'] for r in subset),
     worst_hessian_min=min(r['hessian_eigen_min'] for r in subset)))
 for name,data in (('SCORES.csv',rows),('GROUPS.csv',groups)):
  with (out/name).open('x',newline='') as f:
   wr=csv.DictWriter(f,fieldnames=list(data[0]));wr.writeheader();wr.writerows(data)
 result=dict(complete_cases=len(rows),paired_initializations=8,total_checkpoints=checkpoints,
  max_checkpoint_replay_error=max_checkpoint_error,max_independent_leaf_replay_error=max_independent_error,
  quality_successes=sum(r['numerical_quality'] for r in rows),counts={x['method']:x['quality_successes'] for x in groups},
  external_driver_timeout_events=receipt.get('driver_timeout_events',0),
  missing_driver_case_times=sum(r['missing_driver_time'] for r in rows),
  global_reference_certificate_is_exact_integer=True,fit_endpoints_not_rigorously_interval_certified=True,verified_source=plan['source_sha'],
  audit_cpu=time.process_time()-started,hardware_timing_attested=False,production_authorized=False)
 dump(out/'AUDIT.json',result)
 print(json.dumps(result,sort_keys=True),flush=True)
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--runs',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
 a=p.parse_args();audit(a.source,a.runs,a.out)
