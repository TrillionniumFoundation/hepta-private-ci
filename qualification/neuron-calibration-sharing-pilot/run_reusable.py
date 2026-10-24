"""Historical fit/calibration/internal-evaluation mechanism diagnostic."""
import hashlib,json,math,time,resource
from pathlib import Path
import numpy as np
import torch
from temperature_summary import temperature_summary
P=Path(__file__).resolve().parent;S=P.parent/'cell-head-budget-research'
H=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def req(ok,msg):
 if not ok:raise ValueError(msg)
def save(name,x):
 with (P/name).open('x') as f:json.dump(x,f,indent=2,allow_nan=False)
def loss_rows(logits,y,t=1.):
 a=np.zeros_like(logits) if t is None else logits/t
 return np.logaddexp.reduce(a,axis=-1)-np.take_along_axis(a,np.broadcast_to(y,a.shape[:-1])[...,None],axis=-1)[...,0]
def probs(logits,t=1.):
 a=np.zeros_like(logits) if t is None else logits/t;a=a-a.max(axis=-1,keepdims=True);e=np.exp(a);return e/e.sum(axis=-1,keepdims=True)
def fitT(logits,y):
 objective=lambda z:float(loss_rows(logits,y,math.exp(z)).mean())
 lo,hi=-5.,5.;phi=(math.sqrt(5)-1)/2;c=hi-phi*(hi-lo);d=lo+phi*(hi-lo);fc,fd=objective(c),objective(d)
 for _ in range(100):
  if fc<fd:hi,d,fd=d,c,fc;c=hi-phi*(hi-lo);fc=objective(c)
  else:lo,c,fc=c,d,fd;d=lo+phi*(hi-lo);fd=objective(d)
 candidates=[(objective(z),abs(z),math.exp(z),z) for z in [-5.,0.,5.,(lo+hi)/2]]
 candidates.append((math.log(4),float('inf'),float('inf'),None));best=min(candidates)
 return {'T':None if best[3] is None else best[2],'uniform':best[3] is None,'logT':best[3],'boundary':best[3] is None or abs(abs(best[3])-5)<1e-5,'calibration_nll':best[0]}
def wilson(k,n):
 if n==0:return None
 z=1.959963984540054;q=k/n;den=1+z*z/n;center=(q+z*z/(2*n))/den;rad=z*math.sqrt(q*(1-q)/n+z*z/(4*n*n))/den
 return [max(0.,center-rad),min(1.,center+rad)]
def metrics(p,y,nll):
 pred=p.argmax(1);conf=p.max(1);wrong=pred!=y;accept=conf>=.7;k=int((accept&wrong).sum());n=int(accept.sum());ece=0.;bins=[]
 for j in range(10):
  mask=(conf>=j/10)&((conf<(j+1)/10) if j<9 else conf<=1);m=int(mask.sum())
  ece+=(m/len(y))*abs(float((~wrong)[mask].mean())-float(conf[mask].mean())) if m else 0
  bins.append(m)
 return {'nll':float(nll.mean()),'brier':float(np.square(p-np.eye(4)[y]).sum(1).mean()),'ece10':ece,'ece_bin_counts':bins,'accuracy':float((~wrong).mean()),'accepted':n,'wrong_accepted':k,'coverage':n/len(y),'wrong_accepted_over_all':k/len(y),'conditional_error':k/n if n else None,'conditional_error_wilson95':wilson(k,n)}
req(H(P/'protocol.json')=='69f402d17d2f33e51a9d991a4fd2084575dfb5a6eeb630a47fbbb9963773eb0d','protocol drift');plan=json.loads((P/'protocol.json').read_text())
req(H(S/'rows.json')==plan['source_rows_sha256'],'rows drift');req(H(S/'train-labels-local-only.json')==plan['source_train_labels_sha256'],'training labels drift')
req(not (P/'results.json').exists() and not (P/'heads.npz').exists(),'never overwrite')
rows=json.loads((S/'rows.json').read_text())['train']
with np.load(S/'features.npz',allow_pickle=False) as z:x=z['train'].copy() # Never indexes original test member.
req(hashlib.sha256(x.tobytes()).hexdigest()==plan['source_train_tensor_sha256'],'tensor drift');req(x.shape==(2560,640) and x.dtype==np.float32 and np.isfinite(x).all(),'features invalid')
x=x.astype(np.float64);y=np.array(json.loads((S/'train-labels-local-only.json').read_text()),dtype=np.int64)
order=sorted(range(2560),key=lambda i:(hashlib.sha256(('hepta-calibration-sharing-v1|'+rows[i]['component_key']).encode()).hexdigest(),rows[i]['row_index_zero_based']))
fi=np.array(order[:1280]);ci=np.array(order[1280:1920]);ei=np.array(order[1920:]);draws={s:np.random.Generator(np.random.PCG64(s)).permutation(fi)[:640] for s in plan['seeds']}
req(not(set(fi)&set(ci) or set(fi)&set(ei) or set(ci)&set(ei)),'split overlap')
for ix in draws.values():req(len(set(y[ix]))==4,'missing class')
save('split-freeze.json',{'protocol_sha256':H(P/'protocol.json'),'fit_pool':fi.tolist(),'calibration':ci.tolist(),'internal_eval':ei.tolist(),'component_keys':[r['component_key'] for r in rows],'training_subsets':{str(s):ix.tolist() for s,ix in draws.items()},'old1600_test_accessed':False})
torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True);start=time.monotonic();heads={};fits=[]
for seed,ix in draws.items():
 xt=torch.from_numpy(x[ix]);yt=torch.from_numpy(y[ix]);w=torch.zeros((640,4),dtype=torch.float64,requires_grad=True);b=torch.zeros(4,dtype=torch.float64,requires_grad=True);opt=torch.optim.Adam([w,b],lr=.1)
 for _ in range(200):opt.zero_grad();ce=torch.nn.functional.cross_entropy(xt@w+b,yt);loss=ce+.001/2*w.square().sum();loss.backward();opt.step()
 opt.zero_grad();ce=torch.nn.functional.cross_entropy(xt@w+b,yt);loss=ce+.001/2*w.square().sum();loss.backward()
 heads[str(seed)+'_w']=w.detach().numpy().copy();heads[str(seed)+'_b']=b.detach().numpy().copy();fits.append({'seed':seed,'counts':np.bincount(y[ix],minlength=4).tolist(),'objective':float(loss.detach()),'gradient_l2':float(torch.sqrt(w.grad.square().sum()+b.grad.square().sum()))})
 req(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss<512*1024,'RSS exceeded');req(time.monotonic()-start<180,'time exceeded')
np.savez_compressed(P/'heads.npz',**heads);save('head-freeze.json',{'heads_sha256':H(P/'heads.npz'),'split_sha256':H(P/'split-freeze.json'),'driver_sha256':H(__file__),'fits':fits,'calibration_started':False})
# All head fits are complete. Calibration only below, no evaluation scores yet.
cl=np.stack([x[ci]@heads[str(s)+'_w']+heads[str(s)+'_b'] for s in plan['seeds']]);individual=[fitT(a,y[ci]) for a in cl];shared=fitT(cl,y[ci]);prior=(np.bincount(y[ci],minlength=4)+1)/(len(ci)+4)
save('temperature-freeze.json',{'head_freeze_sha256':H(P/'head-freeze.json'),'individual':individual,'shared':shared,'prior':prior.tolist(),'internal_eval_scoring_started':False,'equal_head_weight':True})
# No further fitting below this line.
el=np.stack([x[ei]@heads[str(s)+'_w']+heads[str(s)+'_b'] for s in plan['seeds']]);ye=y[ei];arms={};nll={}
for arm in ['raw','individual_temperature','shared_temperature']:
 tt=[1.]*20 if arm=='raw' else [r['T'] for r in individual] if arm=='individual_temperature' else [shared['T']]*20
 arms[arm]=np.stack([probs(a,t) for a,t in zip(el,tt)]);nll[arm]=np.stack([loss_rows(a,ye,t) for a,t in zip(el,tt)])
 if arm!='raw':
  for j,t in enumerate(tt):
   if t is not None:req(np.array_equal(arms[arm][j].argmax(1),el[j].argmax(1)),'finite temperature changedtop1')
priorp=np.broadcast_to(prior,(640,4));priornll=-np.log(prior[ye]);pm=metrics(priorp,ye,priornll)
perhead={arm:[metrics(pp,ye,nn) for pp,nn in zip(arms[arm],nll[arm])] for arm in arms}
summary={}
for arm,records in perhead.items():
 summary[arm]={k:float(np.mean([r[k] for r in records])) for k in ['nll','brier','ece10','accuracy','coverage','wrong_accepted_over_all']}
 summary[arm]['accepted_min_max']=[min(r['accepted'] for r in records),max(r['accepted'] for r in records)]
 summary[arm]['conditional_error_unweighted_mean_defined_heads']=float(np.mean([r['conditional_error'] for r in records if r['conditional_error'] is not None])) if any(r['conditional_error'] is not None for r in records) else None
 summary[arm]['conditional_error_undefined_heads']=sum(r['conditional_error'] is None for r in records)
 summary[arm]['mean_per_row_confidence_variance_across_heads']=float(arms[arm].max(2).var(0,ddof=1).mean())
d=(nll['shared_temperature']-nll['individual_temperature']).mean(0);rng=np.random.Generator(np.random.PCG64(2026102550));boot=[float(d[rng.integers(0,640,size=640)].mean()) for _ in range(10000)]
unanimous=(el.argmax(2)==el[0].argmax(1)[None,:]).all(0);groups={}
for name,mask in [('unanimous',unanimous),('nonunanimous',~unanimous)]:
 groups[name]={'n':int(mask.sum()),'nll_means':{a:float(v[:,mask].mean()) if mask.any() else None for a,v in nll.items()}}
np.savez_compressed(P/'calibration-and-eval-local-only.npz',calibration_logits=cl,eval_logits=el,**{a+'_nll':v for a,v in nll.items()})
save('primary-source-contrast.json',{'description':'640 historical internal-eval source contrasts, each averages20correlatedheads; no raw labels/text','values':d.tolist()})
save('results.json',{'scope':plan['scope'],'protocol_sha256':H(P/'protocol.json'),'temperature_freeze_sha256':H(P/'temperature-freeze.json'),'primary':{'shared_minus_individual_nll':float(d.mean()),'conditional_source_bootstrap95':np.quantile(boot,[.025,.975]).tolist()},'summary':summary,'constant_prior_metrics':pm,'perhead':perhead,'individual_temperatures':individual,'shared_temperature':shared,'raw_argmax_row_groups':groups,'finite_temperature_top1_parity':True,'uniform_temperature_head_count':sum(r['uniform'] for r in individual),'wall_seconds':time.monotonic()-start,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'encoder_calls':0,'old1600_test_accessed':False,'no_post_eval_fit':True})
print(json.dumps({'primary':json.loads((P/'results.json').read_text())['primary'],'summary':summary,'shared_temperature':shared,'temperature_summary':temperature_summary(individual),'constant_prior_metrics':pm,'seconds':time.monotonic()-start},indent=2))
