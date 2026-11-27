"""Train and seal literal published-operator networks and matched baselines."""
import time
START=time.perf_counter()
import argparse,copy,hashlib,json
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from cell import LiteralCell
from qualification.hcsn_closure_20261124.baselines import GRUClassifier,LIFClassifier,CausalTransformer
ROOT=Path(__file__).resolve().parent
ARMS=('literal','zero','tangent','ordinary','gru','lif','attention')
SEEDS=(7717,17717,27717)
def write(p,d):
    f=p.with_suffix('.tmp');f.write_text(json.dumps(d,indent=1,allow_nan=False));f.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(task,sp):
    f=ROOT/f'{task}_{sp}.npz'
    assert json.loads((ROOT/'source_receipt.json').read_text())[task][sp]['sha256']==sha(f)
    with np.load(f) as d:return torch.from_numpy(d['x']),d['y'],d['id'].astype(str),d['group'].astype(str)
def model(kind):
    if kind in ('gru','lif','attention'):
        return {'gru':GRUClassifier,'lif':LIFClassifier,'attention':CausalTransformer}[kind](8)
    return LiteralCell(kind)
def predict(net,x,silent=False):
    nets=[];count=0;steps=0
    with torch.no_grad():
        for each in x.split(24,dim=1):
            if isinstance(net,LiteralCell):
                y,c=net(each,silence_boundary=silent,diagnostics=True);count+=int(c.sum());steps+=c.numel()
            else:
                y=net(each)
            nets.extend(y[-1].softmax(-1)[:,1].tolist())
    return np.asarray(nets),count,steps
def metrics(y,p,t=.5):
    pos=y.astype(bool);sg=p>=t
    # Pairwise concordance with half ties for these small reporting cohorts.
    diff=p[pos,None]-p[~pos]
    return {'brier':float(np.mean((p-y)**2)),'ba':float(.5*(sg[pos].mean()+(~sg[~pos]).mean())),'auc':float((np.mean(diff>0)+.5*np.mean(diff==0))),'p_range':[float(p.min()),float(p.max())]}
def threshold(y,p):
    cand=np.unique(np.r_[0.,.5,np.nextafter(np.max(p),2.),p])
    pos=y.astype(bool);d=p[:,None]>=cand[None,:]
    ba=(d[pos].mean(0)+(~d[~pos]).mean(0))*.5
    best=np.flatnonzero(ba==max(ba))
    return float(cand[best[np.argmin(abs(cand[best]-.5))]])
def fit(a,loc):
    x,y,_,_=load(a.task,'train');v,vy,_,_=load(a.task,'val')
    net=model(a.arm);opt=torch.optim.Adam(net.parameters(),lr=.003)
    rng=torch.Generator().manual_seed(11*a.seed);ty=torch.as_tensor(y)
    best=float('inf');history=[];upd=0.
    for k in range(129):
        if k%32==0:
            net.eval();dp,_,_=predict(net,v);m=metrics(vy,dp)
            history.append(dict(step=k,**m))
            if m['brier']<best:
                best=m['brier'];sel=k;th=threshold(vy,dp);weights=copy.deepcopy(net.state_dict())
            if k==128:break
        t=time.perf_counter();net.train()
        idx=torch.randperm(len(y),generator=rng)[:12]
        opt.zero_grad(set_to_none=True);o=net(x[:,idx])[-1]
        F.cross_entropy(o,ty[idx]).backward()
        gn=torch.nn.utils.clip_grad_norm_(net.parameters(),2)
        if not torch.isfinite(gn):raise FloatingPointError('gradient')
        opt.step();upd+=time.perf_counter()-t
    torch.save(weights,loc/'selected.tmp');(loc/'selected.tmp').replace(loc/'selected.pt')
    write(loc/'fit.json',{'selected':sel,'threshold':th,'history':history,'update_seconds':upd,'cold_elapsed_seconds':time.perf_counter()-START,'state_sha256':sha(loc/'selected.pt'),'parameters':sum(v.numel() for v in net.parameters()),'torch':torch.__version__})
def test(a,loc):
    assert json.loads((a.out/'seal.json').read_bytes())['states'][loc.name]==sha(loc/'selected.pt')
    net=model(a.arm);net.load_state_dict(torch.load(loc/'selected.pt',weights_only=True));net.eval()
    f=json.loads((loc/'fit.json').read_bytes());x,y,idx,group=load(a.task,'test')
    p,c,n=predict(net,x);ps=predict(net,x,True)[0] if isinstance(net,LiteralCell) else p
    np.savez_compressed(loc/'pred.npz',p=p,silent=ps,y=y,id=idx,group=group)
    write(loc/'test.json',{'half':metrics(y,p),'calibrated':metrics(y,p,f['threshold']),'silent_half':metrics(y,ps),'immediate_absorptions':c,'total_ticks_and_cells':n,'cold_elapsed_seconds':time.perf_counter()-START,'prediction_sha256':sha(loc/'pred.npz')})
def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('fit','test'));p.add_argument('task',choices=('office','beijing','cities'));p.add_argument('arm',choices=ARMS);p.add_argument('seed',type=int);p.add_argument('--out',type=Path,default=ROOT/'study')
    a=p.parse_args();torch.manual_seed(a.seed);torch.set_num_threads(1);loc=a.out/f'{a.task}-{a.arm}-{a.seed}';loc.mkdir(parents=True,exist_ok=True)
    (fit if a.mode=='fit' else test)(a,loc)
    print(a.mode,loc.name,round(time.perf_counter()-START,3),flush=True)
if __name__=='__main__':main()
