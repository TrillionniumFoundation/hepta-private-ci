"""Training-pool diagnostic only. Never indexes the old test feature member."""
import hashlib,json,time,resource
from pathlib import Path
import numpy as np
import torch
P=Path(__file__).resolve().parent;S=P.parent/'cell-head-budget-research'
H=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def req(ok,msg):
 if not ok:raise ValueError(msg)
def save(name,x):
 with (P/name).open('x') as f:json.dump(x,f,indent=2)
req(H(P/'protocol.json')=='e82f399a8c40dfa1b4772d4d31e2e27340f3ade5f377216f26e621730d403ac7','protocol drift')
p=json.loads((P/'protocol.json').read_text())
req(H(S/'rows.json')==p['source_rows_sha256'],'row identity drift')
req(H(S/'train-labels-local-only.json')==p['source_train_labels_sha256'],'training label drift')
req(not (P/'results.json').exists() and not (P/'all-heads.npz').exists(),'never overwrite')
rows=json.loads((S/'rows.json').read_text())['train']
with np.load(S/'features.npz',allow_pickle=False) as z:
 x=z['train'].copy() # No access to the original test member.
req(hashlib.sha256(x.tobytes()).hexdigest()==p['source_train_tensor_sha256'],'training tensor drift')
req(x.shape==(2560,640) and x.dtype==np.float32 and np.isfinite(x).all(),'features')
req(np.max(np.abs(np.linalg.norm(x,axis=1)-1))<1e-5,'norms')
y=np.array(json.loads((S/'train-labels-local-only.json').read_text()),dtype=np.int64);x=x.astype(np.float64)
order=sorted(range(2560),key=lambda i:(hashlib.sha256(('hepta-stability-v1|'+rows[i]['component_key']).encode()).hexdigest(),rows[i]['row_index_zero_based']))
evalix=np.array(order[:512]);pool=np.array(order[512:]);draws={}
for seed in p['seeds']:
 draw=np.random.Generator(np.random.PCG64(seed)).permutation(pool)
 draws[seed]={n:draw[:n] for n in p['budgets']}
 for n,ix in draws[seed].items():req(len(set(y[ix]))==4,'missing training class')
splits={'protocol_sha256':H(P/'protocol.json'),'internal_eval_source_components':[rows[i]['component_key'] for i in evalix],'internal_eval_original_train_indices':evalix.tolist(),'training_pool_original_train_indices':pool.tolist(),'subsets':{str(s):{str(n):ix.tolist() for n,ix in d.items()} for s,d in draws.items()},'old1600_test_accessed':False,'no_split_level_preprocessing':'Original native L2 normalization was per row, not fitted over2560. Each centroid/weight fit below uses only its own training subset. No original trained head is reused.'}
save('split-freeze.json',splits)
torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
start=time.monotonic();heads={};fits=[]
for seed,d in draws.items():
 for n,ix in d.items():
  ts=time.monotonic();xx=x[ix];yy=y[ix];xt=torch.from_numpy(xx);yt=torch.from_numpy(yy)
  c=np.stack([xx[yy==k].mean(0) for k in range(4)]);c/=np.linalg.norm(c,axis=1,keepdims=True)
  w=torch.zeros((640,4),dtype=torch.float64,requires_grad=True);b=torch.zeros(4,dtype=torch.float64,requires_grad=True);opt=torch.optim.Adam([w,b],lr=.1)
  for _ in range(200):
   opt.zero_grad();ce=torch.nn.functional.cross_entropy(xt@w+b,yt);loss=ce+.001/2*w.square().sum();loss.backward();opt.step()
  opt.zero_grad();ce=torch.nn.functional.cross_entropy(xt@w+b,yt);loss=ce+.001/2*w.square().sum();loss.backward()
  tag=f'{seed}_{n}';heads[tag+'_c']=c;heads[tag+'_w']=w.detach().numpy().copy();heads[tag+'_b']=b.detach().numpy().copy()
  fits.append({'seed':seed,'budget':n,'ce':float(ce.detach()),'objective':float(loss.detach()),'gradient_l2':float(torch.sqrt(w.grad.square().sum()+b.grad.square().sum())),'seconds':time.monotonic()-ts})
  req(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss<1024*1024,'RSS budget exceeded');req(time.monotonic()-start<300,'time budget exceeded')
np.savez_compressed(P/'all-heads.npz',**heads)
save('fit-freeze.json',{'heads_sha256':H(P/'all-heads.npz'),'split_freeze_sha256':H(P/'split-freeze.json'),'driver_sha256':H(__file__),'fits':fits,'internal_eval_scoring_started':False,'old1600_test_accessed':False})
# No fitting below this point.
xe=x[evalix];ye=y[evalix];lc=[];cc=[];records=[];predl=[];predc=[]
for seed in p['seeds']:
 lrows=[];crows=[];plrows=[];pcrows=[]
 for n in p['budgets']:
  tag=f'{seed}_{n}';pl=(xe@heads[tag+'_w']+heads[tag+'_b']).argmax(1);pc=(xe@heads[tag+'_c'].T).argmax(1);l=pl==ye;c=pc==ye;plrows.append(pl);pcrows.append(pc)
  lrows.append(l);crows.append(c);records.append({'seed':seed,'budget':n,'logistic_accuracy':float(l.mean()),'centroid_accuracy':float(c.mean()),'delta':float(l.mean()-c.mean())})
 lc.append(lrows);cc.append(crows);predl.append(plrows);predc.append(pcrows)
predl=np.array(predl);predc=np.array(predc);np.savez_compressed(P/'predictions-local-only.npz',logistic=predl,centroid=predc)
lc=np.array(lc);cc=np.array(cc);adv=lc.astype(float)-cc.astype(float);gains=(adv[:,-1,:]-adv[:,0,:]);perrow=gains.mean(0)
rng=np.random.Generator(np.random.PCG64(2026102450));boot=[float(perrow[rng.integers(0,512,size=512)].mean()) for _ in range(10000)]
summary={}
for j,n in enumerate(p['budgets']):
 summary[n]={}
 for key,vals in [('logistic',lc[:,j].mean(1)),('centroid',cc[:,j].mean(1)),('delta',adv[:,j].mean(1))]:summary[n][key]={'mean':float(vals.mean()),'sd_descriptive_ddof1':float(vals.std(ddof=1)),'min':float(vals.min()),'max':float(vals.max())}
seedgains=gains.mean(1)
correct={'shape':[20,3,512],'seeds':p['seeds'],'budgets':p['budgets'],'logistic':lc.astype(int).tolist(),'centroid':cc.astype(int).tolist()}
save('correctness.json',correct)
save('results.json',{'profile':p['profile'],'scope':p['scope'],'protocol_sha256':H(P/'protocol.json'),'fit_freeze_sha256':H(P/'fit-freeze.json'),'correctness_sha256':H(P/'correctness.json'),'primary':{'mean_relative_gain1280_minus320':float(perrow.mean()),'conditional_source_bootstrap95':np.quantile(boot,[.025,.975]).tolist()},'seed_gains':seedgains.tolist(),'positive_zero_negative_seed_gains':[int((seedgains>0).sum()),int((seedgains==0).sum()),int((seedgains<0).sum())],'summary':summary,'records':records,'per_row':{'logistic_correct_frequency':lc.mean(0).tolist(),'centroid_correct_frequency':cc.mean(0).tolist(),'correctness_disagreement_rate':(lc!=cc).mean(0).tolist(),'predicted_class_disagreement_rate':(predl!=predc).mean(0).tolist()},'gradient_l2_min_max':[min(f['gradient_l2'] for f in fits),max(f['gradient_l2'] for f in fits)],'wall_seconds':time.monotonic()-start,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'old1600_test_accessed':False,'encoder_forwards':0,'no_postscore_refit':True})
print(json.dumps({'primary':json.loads((P/'results.json').read_text())['primary'],'seed_signs':json.loads((P/'results.json').read_text())['positive_zero_negative_seed_gains'],'summary':summary,'seconds':time.monotonic()-start},indent=2))
