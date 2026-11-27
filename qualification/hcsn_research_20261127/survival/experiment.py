"""Empirical first-hit forecast from a literal continuous-boundary or conventional encoder."""
import time
START=time.perf_counter()
import argparse,copy,hashlib,json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from literal.cell import LiteralCell
ROOT=Path(__file__).resolve().parent
H=torch.tensor([1.,3.,6.,12.,24.])
TRAIN_IDX=[0,2,4]
SEEDS=[83,181,283]
ARMS=['physical_fht','physical_weibull','gru_fht','gru_weibull','gru_piecewise','smooth_fht','smooth_weibull','empirical','distance_fht']
def checksum(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def store(p,x):
    t=p.with_suffix('.tmp');t.write_text(json.dumps(x,indent=1,allow_nan=False));t.replace(p)
def data(task,sp):
    f=ROOT/f'{task}_{sp}.npz'
    assert checksum(f)==json.loads((ROOT/'source.json').read_bytes())[task][sp]['sha256']
    with np.load(f) as d:return tuple(torch.from_numpy(d[k]) for k in ('x','margin','y'))
def fht(x,mu):
    h=H.to(x)[None,:];x=x[:,None];mu=mu[:,None];rt=torch.sqrt(h)
    a=torch.special.log_ndtr((-x-mu*h)/rt)
    b=-2*mu*x+torch.special.log_ndtr((-x+mu*h)/rt)
    return torch.logaddexp(a,b).clamp_max(0).exp()
class Predictor(nn.Module):
    def __init__(self,kind):
        super().__init__();self.kind=kind
        if kind=='distance_fht':
            self.raw=nn.Parameter(torch.zeros(2));return
        if kind.startswith('gru'):
            self.core=nn.GRU(7,16,batch_first=True);n=16
        elif kind.startswith('smooth'):
            self.frm=nn.Linear(7,32);self.rec=nn.Linear(16,32,bias=False);n=16
        elif kind.startswith('physical'):
            self.core=LiteralCell('literal',input_dim=7);self.core.readout=nn.Identity();n=8
        self.read=nn.Linear(n+1,3 if kind.endswith('piecewise') else 2)
    def forward(self,x,gap):
        if self.kind=='distance_fht':
            return fht(.01+F.softplus(self.raw[0])*gap*3,2*self.raw[1].tanh().expand(len(x)))
        if self.kind.startswith('gru'):h=self.core(x)[0][:,-1]
        elif self.kind.startswith('physical'):h=self.core(x.transpose(0,1))[-1].float()
        else:
            h=x.new_zeros(len(x),16)
            for frame in x.unbind(1):
                v,g=(self.frm(frame)+self.rec(h)).chunk(2,-1);h=torch.lerp(h,v.tanh(),g.sigmoid())
        z=self.read(torch.cat((h,gap[:,None]),dim=1))
        if self.kind.endswith('fht'):
            return fht(.01+3*torch.sigmoid(z[:,0]),2*z[:,1].tanh())
        if self.kind.endswith('weibull'):
            scale=.05+F.softplus(z[:,0])*8
            shape=.15+2.85*z[:,1].sigmoid()
            return -torch.expm1(-((H.to(x)[None,:]/scale[:,None])**shape[:,None]))
        rates=F.softplus(z)
        o,s,l=rates.unbind(1)
        integral=torch.stack([o,o+.4*s,o+s,o+s+l/3,o+s+l],1)
        return -torch.expm1(-integral)
def pred(net,d):
    x,g,y=d
    with torch.no_grad():return torch.cat([net(x[i:i+96],g[i:i+96]) for i in range(0,len(x),96)])
def diagnostic(y,p):
    p,y=p.detach().numpy(),y.numpy()
    b=((y-p)**2).mean(0)
    return {'brier':b.tolist(),'held_horizon_brier':float(b[[1,3]].mean()),'trained_horizon_brier':float(b[TRAIN_IDX].mean()),'bias':(p-y).mean(0).tolist(),'adjacent_monotonicity_violation':float(np.maximum(p[:,:-1]-p[:,1:],0).max())}
def fit(a,loc):
    tr=data(a.task,'train');dv=data(a.task,'val');history=[];tfit=0.
    if a.arm=='empirical':
        # Only the THREE trained horizon labels are admissible, even for this empirical floor.
        p=tr[2][:,TRAIN_IDX].mean(0).clamp(1e-6,1-1e-6);h=-torch.log1p(-p);o,s,l=h.unbind()
        rate=torch.stack((o,o+.4*(s-o),s,s+(l-s)/3,l));state={'risk':-torch.expm1(-rate)}
        empirical_prediction=state['risk'][None,TRAIN_IDX].expand(len(dv[0]),-1)
        history=[{'step':0,'trained_horizon_brier':float((empirical_prediction-dv[2][:,TRAIN_IDX]).square().mean())}];sel=0;nparams=3
    else:
        net=Predictor(a.arm);opt=torch.optim.Adam(net.parameters(),lr=.003);rng=torch.Generator().manual_seed(11*a.seed)
        best=float('inf');nparams=sum(p.numel() for p in net.parameters() if p.requires_grad)
        for k in range(257):
            if k%64==0:
                net.eval();prob=pred(net,dv)
                # Log only trained-horizon Brier prior to confirmation, excluding interpolation targets.
                b=float((prob[:,TRAIN_IDX]-dv[2][:,TRAIN_IDX]).square().mean());history.append({'step':k,'trained_horizon_brier':b})
                if b<best:best=b;state=copy.deepcopy(net.state_dict());sel=k
                if k==256:break
            t=time.perf_counter();net.train();ix=torch.randperm(len(tr[0]),generator=rng)[:32]
            x,g,y=(v[ix] for v in tr);out=net(x,g)[:,TRAIN_IDX]
            loss=(out-y[:,TRAIN_IDX]).square().mean()
            opt.zero_grad(set_to_none=True);loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(net.parameters(),1)
            if not torch.isfinite(norm):raise FloatingPointError('nonfinite gradient')
            opt.step();tfit+=time.perf_counter()-t
    torch.save(state,loc/'selected.tmp');(loc/'selected.tmp').replace(loc/'selected.pt')
    store(loc/'fit.json',{'history':history,'selected':sel,'parameters':nparams,'update_seconds':tfit,'cold_seconds':time.perf_counter()-START,'state_sha256':checksum(loc/'selected.pt')})
def test(a,loc):
    assert json.loads((a.out/'seal.json').read_bytes())[loc.name]==checksum(loc/'selected.pt')
    st=torch.load(loc/'selected.pt',weights_only=True);dv=data(a.task,'test')
    if a.arm=='empirical':p=st['risk'][None].expand(len(dv[0]),-1)
    else:
        net=Predictor(a.arm);net.load_state_dict(st);net.eval();p=pred(net,dv)
    path=loc/'probabilities.npz';np.savez_compressed(path,p=p.numpy())
    store(loc/'test.json',{'metrics':diagnostic(dv[2],p),'sha256':checksum(path),'cold_seconds':time.perf_counter()-START})
def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['fit','test']);ap.add_argument('task',choices=['power','air']);ap.add_argument('arm',choices=ARMS);ap.add_argument('seed',type=int);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();torch.set_num_threads(1);torch.manual_seed(a.seed);loc=a.out/f'{a.task}-{a.arm}-{a.seed}';loc.mkdir(exist_ok=True,parents=True)
    (fit if a.mode=='fit' else test)(a,loc);print(a.mode,loc.name,flush=True)
if __name__=='__main__':main()
