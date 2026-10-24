import os
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
import json,hashlib,math,ast
from pathlib import Path
import numpy as np
from scipy.special import gammaln,logsumexp
P=Path(__file__).resolve().parent.parent/'cell-head-risk-selection-research';S=P.parent/'cell-head-calibration-sharing-research';B=P.parent/'cell-head-budget-research'
J=lambda p:json.loads(p.read_text());H=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
q=J(P/'protocol.json');f=J(P/'selection-freeze.json');r=J(P/'results.json');fr=J(P/'freeze.json');s=J(S/'split-freeze.json')
assert H(P/'protocol.json')==f['protocol_sha256']==fr['protocol_sha256'];assert H(P/'run.py')==f['driver_sha256'];assert H(P/'selection-freeze.json')==r['selection_freeze_sha256'];assert H(P/'PROPOSAL.md')==q['proposal_sha256']
assert H(S/'heads.npz')==q['heads_sha256'];assert H(S/'split-freeze.json')==q['split_sha256'];assert H(B/'train-labels-local-only.json')==q['train_labels_sha256']
assert fr['utc']<f['utc'];assert q['thresholds']==[.5,.55,.6,.65,.7,.75,.8,.85,.9,.95];assert q['candidates']==len(q['seeds'])*len(q['thresholds'])==200
assert q['alpha']==q['delta']==.05;d=.05/200;assert f['per_candidate_delta']==d
# Independent log-PMF sum inversion, not beta quantile or binom CDF.
def cp(k,n,d):
 if n==0 or k==n:return 1.
 js=np.arange(k+1);coef=gammaln(n+1)-gammaln(js+1)-gammaln(n-js+1);lo,hi=0.,1.
 for _ in range(60):
  p=(lo+hi)/2;lc=logsumexp(coef+js*np.log(p)+(n-js)*np.log1p(-p))
  if lc>math.log(d):lo=p
  else:hi=p
 return (lo+hi)/2
# Extract only pure upper function; never execute full driver.
tree=ast.parse((P/'run.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='upper')
from scipy.stats import beta
ns={'beta':beta};exec(compile(ast.Module(body=[node],type_ignores=[]),'<upper-only>','exec'),ns)
for n in [0,1,2,10,640]:
 for k in sorted(set([0,n,n//2])):
  assert abs(ns['upper'](k,n,d)-cp(k,n,d))<1e-12
  if n and k==0:assert abs(cp(k,n,d)-(1-d**(1/n)))<1e-12
assert math.ceil(math.log(d)/math.log1p(-.05))==162;assert math.ceil(math.log(d)/math.log1p(-.01))==826
assert cp(0,161,d)>.05>=cp(0,162,d);assert cp(0,825,d)>.01>=cp(0,826,d)
with np.load(B/'features.npz',allow_pickle=False) as z:x=z['train'].copy()
assert hashlib.sha256(x.tobytes()).hexdigest()==q['train_tensor_sha256']
y=np.array(J(B/'train-labels-local-only.json'))
with np.load(S/'heads.npz',allow_pickle=False) as z:h={k:z[k] for k in z.files}
def probs(ix):
 a=np.stack([x[ix].astype('float64')@h[str(seed)+'_w']+h[str(seed)+'_b'] for seed in q['seeds']]);a-=a.max(-1,keepdims=True);a=np.exp(a);return a/a.sum(-1,keepdims=True)
a=probs(s['calibration']);wrong=a.argmax(2)!=y[s['calibration']];idx=0;diffs=[]
for j,seed in enumerate(q['seeds']):
 for t in q['thresholds']:
  mask=a[j].max(1)>=t;n=int(mask.sum());k=int((mask&wrong[j]).sum());entry=f['candidates'][idx];idx+=1
  assert (entry['seed'],entry['threshold'],entry['accepted'],entry['wrong_accepted'])==(seed,t,n,k)
  u=cp(k,n,d);diffs.append(abs(u-entry['upper']));assert diffs[-1]<1e-12;assert entry['passes']==(n>0 and u<=.05)
assert idx==200 and not any(e['passes'] for e in f['candidates']);assert all(e['reject_all'] and e['threshold'] is None for e in f['selected'])
a=probs(s['internal_eval']);wrong=a.argmax(2)!=y[s['internal_eval']];mask=a.max(2)>=.7
for j,e in enumerate(r['per_head']['raw_0.70']):
 n=int(mask[j].sum());k=int((mask[j]&wrong[j]).sum());assert e['accepted']==n and e['wrong_accepted']==k;assert abs(e['descriptive_one_sided_CP95']-cp(k,n,.05))<1e-12
for e in r['per_head']['selected']:assert e['accepted']==e['wrong_accepted']==0 and e['conditional_error'] is None and e['descriptive_one_sided_CP95'] is None
c=np.stack([-mask.mean(0),-(mask&wrong).mean(0)]);assert np.array_equal(c,J(P/'source-contrasts.json')['values']);rng=np.random.Generator(np.random.PCG64(q['bootstrap_seed']));boots=np.array([c[:,rng.integers(640,size=640)].mean(1) for _ in range(10000)])
assert np.allclose(np.quantile(boots,[.025,.975],axis=0).T,r['descriptive_contrasts']['conditional_source_bootstrap95'],atol=1e-15,rtol=0)
out={'status':'PASS_HISTORICAL_DIAGNOSTIC_ONLY','candidates':idx,'passes':0,'reject_all_heads':20,'max_CP_difference':max(diffs),'min_accepted_zero_error_target_05':162,'min_accepted_zero_error_target_01':826,'raw_070_coverage':float(mask.mean()),'raw_070_wrong_over_all':float((mask&wrong).mean()),'old_holdout_read':False,'new_fits':0,'qualification':False}
(Path(__file__).parent/'verification.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
