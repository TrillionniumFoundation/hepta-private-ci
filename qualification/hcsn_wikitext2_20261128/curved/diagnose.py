"""Train-activation L2 optimum and full independent held text replay of its substitution."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from curvemodel import CurveLM,evaluate
from train import Windows
from replay import raw_log_prob

class Moments:
    def __init__(self):
        self.gram=torch.zeros(4,4,dtype=torch.float64)
        self.xy=torch.zeros(4,dtype=torch.float64)
        self.yy=0.;self.count=0;self.low=1.;self.high=-1.
    def add(self,u,t,y):
        u=u.flatten().double();t=t.flatten().double();y=y.flatten().double()
        X=torch.stack([torch.ones_like(u),u,t,u*t],1)
        self.gram+=X.T@X;self.xy+=X.T@y;self.yy+=float(y@y);self.count+=len(y)
        self.low=min(self.low,t.min().item());self.high=max(self.high,t.max().item())
    def solve(self):return torch.linalg.solve(self.gram,self.xy)
    def rmse(self,b):
        return float(torch.clamp((self.yy-2*b@self.xy+b@self.gram@b)/self.count,min=0).sqrt())
def stats(model,data,selection):
    rows=[Moments(),Moments()]
    for lo in range(0,len(selection),12):
        ids=selection[lo:lo+12];x=model.emb(data.x[ids])+model.pos
        ok=data.y[ids]>=0
        for b,stats in zip(model.blocks,rows):
            q,k,v=b.qkv(b.pre(x)).chunk(3,-1);p=b.histpow
            u=torch.tanh(q+torch.cumsum(k*(1-b.decay)/p,1)*p)
            t=2*torch.sigmoid(v)-1
            obs=evaluate(u,t,b.pricing);stats.add(u[ok],t[ok],obs[ok]);x=b(x)
    return rows


def score(model,test):
    sums=[]
    for lo in range(0,len(test.x),32):
        x=test.x[lo:lo+32];y=test.y[lo:lo+32];valid=y>=0
        state=model.encode(x)
        val=raw_log_prob(model.head,state[valid],y[valid])
        vec=torch.zeros_like(y,dtype=torch.float64);vec[valid]=val.double()
        sums.extend([v.tolist() for v in torch.stack((vec.sum(1),valid.sum(1)),1)])
    return np.asarray(sums)


def run(root,seed):
    directory=root/'curved';train=Windows(root/'train.npy');test=Windows(root/'test.npy')
    base=json.loads((directory/'tables.json').read_text())
    uniform=torch.tensor(np.ravel(base['uniform_projection_coefficients']),dtype=torch.float64)
    runs={};raws={}
    for kind in ('hxcurve','bilinear','smoothwall'):
        file=directory/'results'/f'{kind}-{seed}.json'
        m=CurveLM(33278,kind).eval()
        m.load_state_dict(torch.load(directory/'results'/f'{kind}-{seed}-best.pt',map_location='cpu',weights_only=True))
        rr=score(m,test);nll=rr[:,0].sum()/rr[:,1].sum()
        record=json.loads(file.read_text())
        if abs(record['test']['nll']-nll)>2e-7:raise ArithmeticError('held replay mismatch')
        raws[kind]=rr;runs[kind]=dict(nll=nll,ppl=np.exp(nll))
        if kind!='hxcurve':continue
        tr=stats(m,train,np.arange(0,len(train.x),33))
        te=stats(m,test,np.arange(0,len(test.x),1))
        layers=[]
        for a,b,layer in zip(tr,te,m.blocks):
            coef=a.solve()
            layers.append(dict(train_scalar_samples=a.count,test_scalar_samples=b.count,
                    train_t_range=[a.low,a.high],test_t_range=[b.low,b.high],
                    fitted_bilinear=coef.tolist(),gram_condition=float(torch.linalg.cond(a.gram)),
                    empirical_train_rmse=a.rmse(coef),uniform_train_rmse=a.rmse(uniform),
                    empirical_test_rmse=b.rmse(coef),uniform_test_rmse=b.rmse(uniform)))
            layer.pricing=coef.view(2,2).contiguous()
        rr=score(m,test);nll=rr[:,0].sum()/rr[:,1].sum()
        raws['replaced']=rr;runs['replaced']=dict(nll=nll,ppl=np.exp(nll),layers=layers)
    np.savez_compressed(directory/'results'/f'paired-{seed}.npz',**raws)
    (directory/'results'/f'diagnostic-{seed}.json').write_text(json.dumps(runs,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('seed',type=int);z=p.parse_args()
    torch.set_num_threads(1)
    with torch.inference_mode():run(z.root,z.seed)
