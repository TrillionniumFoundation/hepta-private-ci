"""Read-only R20 proof/census/replay; reject any tamper despite rehashed reports."""
import argparse,csv,hashlib,json,sys,time
from fractions import Fraction as F
from pathlib import Path
import numpy as np

def need(cond,msg):
 if not cond:raise ValueError(msg)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_text())
def store(path,obj):
 with path.open('x') as f:json.dump(obj,f,sort_keys=True,indent=2);f.write('\n')

def audit(source,runs,evidence,out):
 t0=time.perf_counter();out.mkdir(parents=True,exist_ok=False)
 sys.path.insert(0,str(source.resolve()))
 import model,run,fitters,global_interval
 plan=load(runs/'PLAN.json');done=load(runs/'COMPLETE.json')
 need(plan['source_sha']==run.sources(),'source SHA drift')
 need(done['plan_sha']==sha(runs/'PLAN.json'),'root plan SHA mismatch')
 need(plan['specs']==run.specs(),'case plan incorrect')
 need(done['completed']==80 and done['failed']==0 and len(done['entries'])==80,'incomplete eighty census')
 need([e['name'] for e in done['entries']]==[run.name(s) for s in run.specs()],'run order wrong')
 certificates={}
 for arm,extra,a,b,file in [('signed',True,F('1.54696889'),F('.44887401'),'CERT_NEW.json'),
                            ('control',False,F('1.64044199'),F('.42331392'),'CERT_CONTROL.json')]:
  orig=load(evidence/file)
  fresh=global_interval.bnb(a,b,extra,F(1,100),50000)
  for key in ('global_cost_lower','global_regret_upper','candidate_cost_rigorous_upper','nodes_split',
              'frontier_count','passes_frozen_global_threshold','strong_convex_auxiliary_used'):
   need(orig[key]==fresh[key],'changed global certificate: '+key)
  frontier=evidence/('FRONTIER_NEW.jsonl' if extra else 'FRONTIER_CONTROL.jsonl')
  need(orig['frontier_sha256']==sha(frontier),'frontier SHA mismatch')
  need(len(frontier.read_text().splitlines())==orig['frontier_count'],'frontier row census mismatch')
  certificates[arm]=orig
 scores=[];checkpoints=0;max_cp=0.;max_independent=0.;max_ad=0.;groups={}
 for ent in done['entries']:
  s=ent['spec'];name=ent['name'];folder=runs/name
  need(ent['status']=='completed','failed member')
  need(sha(folder/'REPORT.json')==ent['report_sha'],'changed report bytes')
  report=load(folder/'REPORT.json');seal=load(folder/'FIT_SEAL.json');child=load(folder/'PLAN.json')
  need(s==report['spec']==child['spec'],'identity mismatch')
  need(child['source_sha']==plan['source_sha']==report['source_sha'],'child source mismatch')
  need(child['protocol_commit']==plan['protocol_commit']==run.PROTOCOL_COMMIT,'protocol mismatch')
  need(report['fitted_with_global_reference'] is False and report['quality_assigned_before_fit'] is False,
       'global proof used in fit')
  need(child['reference_used_in_fit'] is False and report['global_qualification'] is None,'pre-fit oracle')
  need(sha(folder/'PLAN.json')==seal['plan']==report['plan_sha'],'plan seal forged')
  need(sha(folder/'CHECKPOINTS.npz')==seal['checkpoints'],'checkpoint hash wrong')
  need(sha(folder/'LEAVES.npz')==report['leaves_sha'],'branch array hash mismatch')
  with np.load(folder/'INITIAL.npz',allow_pickle=False) as f:initial=f['theta'].copy()
  with np.load(folder/'WEIGHTS.npz',allow_pickle=False) as f:theta=f['theta'].copy()
  with np.load(folder/'CHECKPOINTS.npz',allow_pickle=False) as f:
   states=f['theta'].copy();times=f['cpu'].copy();costs=f['cost'].copy()
  with np.load(folder/'LEAVES.npz',allow_pickle=False) as f:leaf=f['values'].copy()
  expected=np.asarray(s['initial'],dtype='<f8')
  need(theta.shape==(2,) and initial.shape==(2,) and np.array_equal(initial,expected),'initial tensor mismatch')
  need(hashlib.sha256(initial.tobytes()).hexdigest()==seal['initial']==report['initial_sha'],'initial tensor hash')
  need(hashlib.sha256(theta.tobytes()).hexdigest()==seal['weights']==report['weights_sha'],'weight tensor hash')
  need(len(states)==len(times)==len(costs)==report['checkpoints'] and len(states)>0,'checkpoint census mismatch')
  need(np.array_equal(states[0],initial) and np.array_equal(states[-1],theta),'endpoint checkpoint mismatch')
  need(np.all(np.diff(times)>=0) and times[-1]<=report['fit_cpu']+1e-7,'checkpoint CPU forged')
  extra=s['arm']=='signed'
  replays=np.asarray([model.full(row,extra)[0] for row in states])
  cp_err=float(np.max(abs(costs-replays)));max_cp=max(max_cp,cp_err)
  need(cp_err<=1e-13,'falsified checkpoint cost')
  row_leaves=model.leaves(theta,extra)
  need(np.array_equal(leaf,row_leaves),'incorrect stage leaves')
  cost,grad,hess=model.full(theta,extra)
  independent=model.independent_full(theta,extra)
  error=abs(cost-independent);max_independent=max(error,max_independent)
  need(error<=1e-12 and abs(cost-report['final_cost'])<=1e-13,'falsified final cost')
  need(abs(independent-report['independent_full_tree_cost'])<=1e-12,'falsified independent cost')
  np.testing.assert_allclose(grad,report['gradient'],rtol=1e-10,atol=1e-11)
  np.testing.assert_allclose(hess,report['hessian'],rtol=1e-10,atol=1e-11)
  al,bl=F.from_float(float(theta[0])),F.from_float(float(theta[1]))
  rational_cost_lo,rational_cost_hi=global_interval.cost_bounds((al,al,bl,bl),extra)
  lb=F(certificates[s['arm']]['global_cost_lower'])
  certified_gap=max(F(0),rational_cost_hi-lb)
  qualifies=certified_gap<=F(1,100)
  # Only this exact rational inequality is a certified individual upper regret.
  safe_score=float(certified_gap)
  checkpoints+=len(states)
  groups.setdefault((s['seed'],s['arm']),[]).append(hashlib.sha256(initial.tobytes()).hexdigest())
  scores.append(dict(name=name,seed=s['seed'],arm=s['arm'],method=s['method'],a=theta[0],b=theta[1],
     initial_a=initial[0],initial_b=initial[1],final_cost=cost,
     global_lower=float(lb),certified_gap_upper=safe_score,
     globally_qualified=qualifies,grad_inf=float(max(abs(grad))),
     hessian_min=float(np.linalg.eigvalsh(hess)[0]),
     fit_cpu=report['fit_cpu'],fit_wall=report['fit_wall'],whole_child_cpu=ent['child_cpu'],
     whole_child_wall=ent['child_wall'],peak_rss=report['fit_peak_rss'],
     checkpoints=len(states),updates=report['counts']['updates'],
     ad_graphs=report['counts']['ad_graphs'],status=report['fit_status']))
 for k,arr in groups.items():need(len(arr)==5 and len(set(arr))==1,'not five matched starts')
 for name,rows in [('SCORES.csv',scores)]:
  with (out/name).open('x',newline='') as f:
   wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
 summ=[]
 for arm in ('signed','control'):
  for method in fitters.METHODS:
   cohort=[s for s in scores if s['arm']==arm and s['method']==method]
   need(len(cohort)==8,'incomplete solver subgroup')
   summ.append(dict(arm=arm,method=method,qualified=sum(s['globally_qualified'] for s in cohort),total=8,
      median_fit_cpu=float(np.median([s['fit_cpu'] for s in cohort])),
      final_cost_mean=float(np.mean([s['final_cost'] for s in cohort])),
      median_certified_gap=float(np.median([s['certified_gap_upper'] for s in cohort])),
      peak_rss_max=max(s['peak_rss'] for s in cohort)))
 with (out/'GROUPS.csv').open('x',newline='') as f:
  wr=csv.DictWriter(f,fieldnames=list(summ[0]));wr.writeheader();wr.writerows(summ)
 evidence=dict(runs=len(scores),checkpoints=checkpoints,matched_five_way_starts=len(groups),
    certified_qualified=sum(s['globally_qualified'] for s in scores),
    max_checkpoint_replay_error=max_cp,max_independent_tree_error=max_independent,
    complete_certificates={k:{x:v[x] for x in ('nodes_split','global_regret_upper','global_cost_lower','frontier_sha256')}
                           for k,v in certificates.items()},
    source_sha=plan['source_sha'],wall=time.perf_counter()-t0,
    global_cost_certificates_are_exact_rational=True,unique_global_optimum_proven=False,
    production_authorized=False,timing_externally_attested=False)
 store(out/'AUDIT.json',evidence)
 print(json.dumps({k:evidence[k] for k in ('runs','checkpoints','certified_qualified','max_checkpoint_replay_error','wall')}))
 return evidence

if __name__=='__main__':
 p=argparse.ArgumentParser()
 p.add_argument('--source',type=Path,required=True)
 p.add_argument('--runs',type=Path,required=True)
 p.add_argument('--evidence',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True)
 a=p.parse_args();audit(a.source,a.runs,a.evidence,a.out)
