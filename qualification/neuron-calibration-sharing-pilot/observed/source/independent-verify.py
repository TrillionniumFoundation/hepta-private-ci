import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import json,hashlib,math
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent.parent/'cell-head-calibration-sharing-research';S=P.parent/'cell-head-budget-research'
J=lambda n:json.loads((P/n).read_text());H=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=J('protocol.json');split=J('split-freeze.json');hf=J('head-freeze.json');tf=J('temperature-freeze.json');res=J('results.json')
assert H(P/'protocol.json')==split['protocol_sha256']==res['protocol_sha256']==J('freeze.json')['protocol_sha256']
assert H(P/'split-freeze.json')==hf['split_sha256'];assert H(P/'heads.npz')==hf['heads_sha256'];assert H(P/'run.py')==hf['driver_sha256'];assert H(P/'head-freeze.json')==tf['head_freeze_sha256'];assert H(P/'temperature-freeze.json')==res['temperature_freeze_sha256']
assert H(S/'train-labels-local-only.json')==plan['source_train_labels_sha256'];assert H(S/'rows.json')==plan['source_rows_sha256']
y=np.array(json.loads((S/'train-labels-local-only.json').read_text()));rows=json.loads((S/'rows.json').read_text())['train']
with np.load(S/'features.npz',allow_pickle=False) as z:x=z['train'].copy()
assert hashlib.sha256(x.tobytes()).hexdigest()==plan['source_train_tensor_sha256']
assert len(set(r['component_key'] for r in rows))==2560
order=sorted(range(2560),key=lambda i:(hashlib.sha256(('hepta-calibration-sharing-v1|'+rows[i]['component_key']).encode()).hexdigest(),rows[i]['row_index_zero_based']))
for key,ix in zip(['fit_pool','calibration','internal_eval'],[order[:1280],order[1280:1920],order[1920:]]):assert split[key]==ix
for s in plan['seeds']:assert split['training_subsets'][str(s)]==np.random.Generator(np.random.PCG64(s)).permutation(order[:1280])[:640].tolist()
ci=split['calibration'];ei=split['internal_eval'];yc=y[ci];ye=y[ei]
with np.load(P/'heads.npz',allow_pickle=False) as h:
 assert len(h.files)==40
 cl=np.stack([x[ci].astype('float64')@h[str(s)+'_w']+h[str(s)+'_b'] for s in plan['seeds']]);el=np.stack([x[ei].astype('float64')@h[str(s)+'_w']+h[str(s)+'_b'] for s in plan['seeds']])
with np.load(P/'calibration-and-eval-local-only.npz',allow_pickle=False) as z:
 assert np.array_equal(cl,z['calibration_logits']) and np.array_equal(el,z['eval_logits'])
def soft(a):
 e=np.exp(a-a.max(-1,keepdims=True));return e/e.sum(-1,keepdims=True)
def loss(a,y):
 m=a.max(-1);return m+np.log(np.exp(a-m[...,None]).sum(-1))-np.take_along_axis(a,np.broadcast_to(y,a.shape[:-1])[...,None],axis=-1)[...,0]
def derivative(a,y,b):return np.mean((soft(a*b)*a).sum(-1)-np.take_along_axis(a,np.broadcast_to(y,a.shape[:-1])[...,None],axis=-1)[...,0])
# Independent convex inverse-temperature derivative bisection, no eval fit.
optimal=[]
for a,entry in [(cl,tf['shared'])]+list(zip(cl,tf['individual'])):
 lo,hi=math.exp(-5),math.exp(5)
 for _ in range(100):
  mid=(lo+hi)/2
  if derivative(a,yc,mid)>0:hi=mid
  else:lo=mid
 beta=(lo+hi)/2
 candidates=[0.,math.exp(-5),math.exp(5),1.,beta]
 b=min(candidates,key=lambda b:float(loss(a*b,yc).mean()))
 recorded_beta=0 if entry['T'] is None else 1/entry['T']
 assert abs(float(loss(a*b,yc).mean())-entry['calibration_nll'])<1e-12
 assert abs(b-recorded_beta)<1e-6
 optimal.append({'beta':b,'gradient':float(derivative(a,yc,b))})
prior=(np.bincount(yc,minlength=4)+1)/644
assert np.array_equal(prior,tf['prior'])
computed={};allloss={}
for arm,temps in [('raw',[1]*20),('shared_temperature',[tf['shared']['T']]*20),('individual_temperature',[v['T'] for v in tf['individual']])]:
 logits=np.stack([a/(t if t else 1) if t is not None else np.zeros_like(a) for a,t in zip(el,temps)])
 pp=soft(logits);ll=loss(logits,ye);allloss[arm]=ll;computed[arm]={}
 for i in range(20):
  p=pp[i];conf=p.max(1);correct=p.argmax(1)==ye;acc=conf>=.7;n=int(acc.sum());k=int((acc&~correct).sum());r=res['perhead'][arm][i]
  assert r['accepted']==n and r['wrong_accepted']==k
  ph=k/n;z=1.959963984540054;den=1+z*z/n;ctr=(ph+z*z/(2*n))/den;rad=z/den*math.sqrt(ph*(1-ph)/n+z*z/(4*n*n))
  assert np.allclose(r['conditional_error_wilson95'],[ctr-rad,ctr+rad],rtol=0,atol=1e-15)
  ece=sum(np.mean(mask)*abs(float(conf[mask].mean()-correct[mask].mean())) for j in range(10) if (mask:=((conf>=j/10)&(conf<(j+1)/10 if j<9 else conf<=1))).any())
  assert abs(r['ece10']-ece)<1e-14
  assert abs(r['nll']-ll[i].mean())<1e-14
  assert abs(r['brier']-((p-np.eye(4)[ye])**2).sum(1).mean())<1e-14
 for metric in ['nll','ece10','brier','coverage','wrong_accepted_over_all']:
  computed[arm][metric]=float(np.mean([v[metric] for v in res['perhead'][arm]]));assert abs(computed[arm][metric]-res['summary'][arm][metric])<1e-14
 assert np.array_equal(pp.argmax(2),el.argmax(2))
d=(allloss['shared_temperature']-allloss['individual_temperature']).mean(axis=0)
assert np.allclose(d,J('primary-source-contrast.json')['values'],rtol=0,atol=1e-14)
rng=np.random.Generator(np.random.PCG64(plan['bootstrap']['seed']));boot=np.array([np.mean(d[rng.integers(len(d),size=len(d))]) for _ in range(10000)]);ci95=np.quantile(boot,[.025,.975]);assert np.allclose(ci95,res['primary']['conditional_source_bootstrap95'],rtol=0,atol=1e-14)
assert abs(d.mean()-res['primary']['shared_minus_individual_nll'])<1e-14
assert res['constant_prior_metrics']['accepted']==0 and res['constant_prior_metrics']['conditional_error'] is None
assert abs(-np.log(prior[ye]).mean()-res['constant_prior_metrics']['nll'])<1e-14
out={'status':'PASS_INDEPENDENT_NO_RETRAIN_RECOMPUTATION','primary':float(d.mean()),'bootstrap95':ci95.tolist(),'summary':computed,'calibration_optima_derivative_check':optimal,'read_old_holdout':False,'new_fit':False,'limitations':['local hash chain and source execution order, not external preregistration','historically exposed source pool; no fresh heldout claim','conditional resampling only; shared training/calibration uncertainty omitted']}
(Path(__file__).parent/'verification.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
