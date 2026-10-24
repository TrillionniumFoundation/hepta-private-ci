"""Once-only historical raw-confidence rejection diagnostic. Not safety certification."""
import hashlib,json,time,resource,datetime
from pathlib import Path
import numpy as np
from scipy.stats import beta,binom
P=Path(__file__).resolve().parent;S=P.parent/'cell-head-calibration-sharing-research';B=P.parent/'cell-head-budget-research'
H=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,obj):
 with (P/name).open('x') as f:json.dump(obj,f,indent=2,allow_nan=False)
def req(ok,msg):
 if not ok:raise ValueError(msg)
def upper(k,n,d):
 if n==0 or k==n:return 1.
 return float(beta.ppf(1-d,k+1,n-k))
def inverse_upper(k,n,d):
 if n==0 or k==n:return 1.
 lo,hi=0.,1.
 for _ in range(100):
  mid=(lo+hi)/2
  if binom.cdf(k,n,mid)>d:lo=mid
  else:hi=mid
 return (lo+hi)/2

def probs(a):
 a=a-a.max(-1,keepdims=True);e=np.exp(a);return e/e.sum(-1,keepdims=True)
def describe(a,w):
 n=int(a.sum());k=int((a&w).sum())
 return {'accepted':n,'wrong_accepted':k,'coverage':n/640,'wrong_over_all':k/640,'conditional_error':k/n if n else None,'descriptive_one_sided_CP95':upper(k,n,.05) if n else None}
req(H(P/'protocol.json')=='ebfc84dc150a2cde516c7ec2b37688730ed15760664d652422601edd62b3014a','protocol drift');q=json.loads((P/'protocol.json').read_text());start=time.monotonic()
req(H(S/'heads.npz')==q['heads_sha256'],'heads drift');req(H(S/'split-freeze.json')==q['split_sha256'],'split drift');req(H(B/'train-labels-local-only.json')==q['train_labels_sha256'],'labels drift')
req(not (P/'selection-freeze.json').exists(),'never repeat selection')
split=json.loads((S/'split-freeze.json').read_text());ci=np.array(split['calibration']);ei=np.array(split['internal_eval']);fi=np.array(split['fit_pool']);req(len(ci)==len(ei)==640 and not(set(ci)&set(ei) or set(ci)&set(fi) or set(ei)&set(fi)),'split violation')
with np.load(B/'features.npz',allow_pickle=False) as z:x=z['train'].copy() # Never loads old test member.
req(hashlib.sha256(x.tobytes()).hexdigest()==q['train_tensor_sha256'],'tensor drift');x=x.astype(np.float64)
# Load only calibration labels before selecting; the source file is historical, previously read.
label_source=json.loads((B/'train-labels-local-only.json').read_text());yc=np.array([label_source[i] for i in ci]);del label_source
with np.load(S/'heads.npz',allow_pickle=False) as z:heads={k:z[k].copy() for k in z.files}
cal=np.stack([probs(x[ci]@heads[str(s)+'_w']+heads[str(s)+'_b']) for s in q['seeds']]);conf=cal.max(2);wrong=cal.argmax(2)!=yc[None,:];records=[];selected=[];d=q['delta']/q['candidates'];maxerr=0.
for j,s in enumerate(q['seeds']):
 candidates=[]
 for t in q['thresholds']:
  a=conf[j]>=t;n=int(a.sum());k=int((a&wrong[j]).sum());u=upper(k,n,d);v=inverse_upper(k,n,d);maxerr=max(maxerr,abs(u-v));r={'seed':s,'threshold':t,'accepted':n,'wrong_accepted':k,'upper':u,'passes':bool(n>0 and u<=q['alpha'])};records.append(r)
  if r['passes']:candidates.append(r)
 best=min(candidates,key=lambda r:(-r['accepted'],r['threshold'])) if candidates else None
 selected.append({'seed':s,'threshold':best['threshold'] if best else None,'reject_all':best is None,'calibration_record':best})
req(maxerr<1e-10,'CP inversion mismatch')
save('selection-freeze.json',{'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'protocol_sha256':H(P/'protocol.json'),'driver_sha256':H(Path(__file__)),'candidates':records,'selected':selected,'family_candidate_count':len(records),'per_candidate_delta':d,'max_CP_independent_inversion_difference':maxerr,'eval_computed_in_this_run':False})
# All selected rules are immutable before any evaluation computation.
y_source=json.loads((B/'train-labels-local-only.json').read_text());ye=np.array([y_source[i] for i in ei]);del y_source
pp=np.stack([probs(x[ei]@heads[str(s)+'_w']+heads[str(s)+'_b']) for s in q['seeds']]);ww=pp.argmax(2)!=ye[None,:];cc=pp.max(2)
sa=np.stack([np.zeros(640,dtype=bool) if r['reject_all'] else cc[j]>=r['threshold'] for j,r in enumerate(selected)]);ba=cc>=q['comparator'];metrics={'selected':[describe(a,w) for a,w in zip(sa,ww)],'raw_0.70':[describe(a,w) for a,w in zip(ba,ww)]};summary={}
for name,rr in metrics.items():
 summary[name]={'mean_coverage':float(np.mean([r['coverage'] for r in rr])),'mean_wrong_over_all':float(np.mean([r['wrong_over_all'] for r in rr])),'defined_conditional_error_heads':sum(r['conditional_error'] is not None for r in rr),'mean_defined_conditional_error':float(np.mean([r['conditional_error'] for r in rr if r['conditional_error'] is not None])) if any(r['conditional_error'] is not None for r in rr) else None}
contrasts=np.stack([(sa.astype(float)-ba).mean(0),((sa&ww).astype(float)-(ba&ww)).mean(0)]);rng=np.random.Generator(np.random.PCG64(q['bootstrap_seed']));boots=np.array([contrasts[:,rng.integers(0,640,size=640)].mean(1) for _ in range(q['bootstrap_replicates'])]);ci95=np.quantile(boots,[.025,.975],axis=0)
save('source-contrasts.json',{'order':['coverage_selected_minus_raw_0.70','wrong_over_all_selected_minus_raw_0.70'],'values':contrasts.tolist(),'interpretation':'640 source units; each averages20 correlated heads; descriptive historical contrasts'})
save('results.json',{'scope':q['scope'],'selection_freeze_sha256':H(P/'selection-freeze.json'),'summary':summary,'per_head':metrics,'reject_all_heads':sum(r['reject_all'] for r in selected),'passing_candidates':sum(r['passes'] for r in records),'descriptive_contrasts':{'means':contrasts.mean(1).tolist(),'conditional_source_bootstrap95':ci95.T.tolist()},'old1600_test_accessed':False,'encoder_calls':0,'new_fits':0,'wall_seconds':time.monotonic()-start,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
print(json.dumps(json.loads((P/'results.json').read_text())|{'per_head':'see results file'},indent=2))
