"""All heads frozen before loading new test labels; no tuning or calibration."""
import hashlib,json,time,resource
from pathlib import Path
import numpy as np
import torch
P=Path(__file__).resolve().parent
H=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(x,msg):
 if not x:raise ValueError(msg)
def write(name,x):
 with (P/name).open('x') as f:json.dump(x,f,indent=2)
expected='b73cb06a5e441d07e0c38f0bb02350ee798f6e4cd30c70b51abc2163157faf1c'
require(H(P/'protocol.json')==expected,'protocol drift')
require(H(P/'rows.json')=='2017a6ba9d4d986c72490ab62c0b7ad57da382a47aa9fa3b2ed44cac3b85b308','selected manifest drift')
require(H(P/'preparation-receipt.json')=='e6317885c59fa590a8558e6491fa978831b3060ebcc6ff0b28f47fbe5ebfbe7b','frozen preparation drift')
require(not (P/'results.json').exists() and not (P/'fitted-heads.npz').exists(),'never overwrite results')
plan=json.loads((P/'protocol.json').read_text());ex=json.loads((P/'extraction.json').read_text());prep=json.loads((P/'preparation-receipt.json').read_text())
require(ex['protocol_sha256']==expected and H(P/'features.npz')==ex['features_sha256'],'feature receipt drift')
require(ex['preparation_receipt_sha256']==H(P/'preparation-receipt.json'),'preparation drift')
require(H(P/'train-labels-local-only.json')=='79e95e395a464fd2c26db400916d83f88c904883b93509c7bfac4c5d5375b34b','training labels drift')
data=np.load(P/'features.npz',allow_pickle=False)
for key,z in data.items():
 require(hashlib.sha256(z.tobytes()).hexdigest()==ex['splits'][key]['tensor_sha256'],'tensor drift')
 require(z.shape==({'train':2560,'test':1600}[key],640) and np.isfinite(z).all(),'shape/finite')
# Test labels are in a separate file, not opened until all heads are fitted.
ytrain=np.array(json.loads((P/'train-labels-local-only.json').read_text()),dtype=np.int64)
xtrain=data['train'].astype(np.float64);torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True);torch.manual_seed(20261023)
heads={};training={};start=time.monotonic()
for n in plan['training_budgets']:
 t=time.monotonic();x=xtrain[:n];y=ytrain[:n];xt=torch.from_numpy(x);yt=torch.from_numpy(y)
 cent=np.stack([x[y==k].mean(0) for k in range(4)]);cent/=np.linalg.norm(cent,axis=1,keepdims=True)
 w=torch.zeros((640,4),dtype=torch.float64,requires_grad=True);b=torch.zeros(4,dtype=torch.float64,requires_grad=True);opt=torch.optim.Adam([w,b],lr=.1)
 curve=[]
 for step in range(200):
  opt.zero_grad();ce=torch.nn.functional.cross_entropy(xt@w+b,yt);loss=ce+.001/2*w.square().sum();loss.backward();opt.step()
  if step in [0,49,99,149,199]:curve.append({'step':step+1,'preupdate_objective':float(loss.detach())})
 opt.zero_grad();ce=torch.nn.functional.cross_entropy(xt@w+b,yt);loss=ce+.001/2*w.square().sum();loss.backward()
 heads[f'centroid_{n}']=cent;heads[f'weight_{n}']=w.detach().numpy().copy();heads[f'bias_{n}']=b.detach().numpy().copy()
 training[n]={'n':n,'seconds':time.monotonic()-t,'final_ce':float(ce.detach()),'final_objective':float(loss.detach()),'gradient_l2':float(torch.sqrt(w.grad.square().sum()+b.grad.square().sum())),'curve':curve}
np.savez_compressed(P/'fitted-heads.npz',**heads)
write('fit-receipt.json',{'protocol_sha256':expected,'heads_sha256':H(P/'fitted-heads.npz'),'driver_sha256':H(__file__),'training':training,'test_scoring_started':False})
# No further fitting below this line.
require(H(P/'test-labels-local-only.json')=='89c40310fae5896855719d412f8b5e4d5309499706a08ffa8bd492550b34949e','test labels drift')
y=np.array(json.loads((P/'test-labels-local-only.json').read_text()));x=data['test'].astype(np.float64)
correct={};metrics={}
for n in plan['training_budgets']:
 l=x@heads[f'weight_{n}']+heads[f'bias_{n}'];c=x@heads[f'centroid_{n}'].T
 lc=l.argmax(1)==y;cc=c.argmax(1)==y;correct[n]=(lc,cc)
 metrics[n]={'logistic_accuracy':float(lc.mean()),'centroid_accuracy':float(cc.mean()),'delta':float(lc.mean()-cc.mean())}
deltas={n:l.astype(float)-c.astype(float) for n,(l,c) in correct.items()}
contrasts={'endpoint_delta_2560':deltas[2560],'budget_gain_2560_minus_320':deltas[2560]-deltas[320]}
rng=np.random.default_rng(2026102401);boot={k:[] for k in contrasts}
for _ in range(10000):
 ix=rng.integers(0,len(y),size=len(y))
 for k,d in contrasts.items():boot[k].append(float(d[ix].mean()))
primary={k:{'estimate':float(d.mean()),'bootstrap97_5':np.quantile(boot[k],[.0125,.9875]).tolist()} for k,d in contrasts.items()}
write('results.json',{'status':'new disjoint historical same-source pilot, not qualification','protocol_sha256':expected,'metrics':metrics,'primary':primary,'budget_related_benefit_demonstrated':all(r['bootstrap97_5'][0]>0 for r in primary.values()),'training':training,'seconds':time.monotonic()-start,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'no_post_test_refit':True})
print(json.dumps({'metrics':metrics,'primary':primary},indent=2))
