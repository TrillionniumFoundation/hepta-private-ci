"""Fresh FSDD + Arabic parents; all 6 time points and both hidden layers jointly trained."""
import argparse
from pathlib import Path
from core import *
import torch
import torch.nn.functional as F
torch.set_num_threads(1);torch.set_num_interop_threads(1)
def gate(z,L):
    q=((z+12)*(16384/24)).clamp(0,16384);k=q.long()
    return L[k]+(q-k).unsqueeze(-1)*(L[(k+1).clamp(max=16384)]-L[k])
def tfb(a):return .4*(a[...,0].tanh()+a[...,1].tanh())
def tB(z):return torch.log1p(KAPPA*z.tanh())/KAPPA
def torch_lower(x,s,l):
    dr=x@s['w1']+s['b1'];fb=0;out=[]
    for k in range(T):
        u=dr[:,k]+fb;a=gate(u,l);fb=tfb(a);out.append(torch.cat((tB(u),tB(dr[:,k]+fb)),dim=-1))
    return torch.stack(out,dim=1)
def torch_upper(h,w,b,l):
    dr=h@w+b;fb=0;out=[]
    for i in range(T):
        a=gate(dr[:,i]+fb,l);fb=tfb(a);out.append(a)
    return torch.stack(out,dim=1)
def main(dest,seed):
    tr=splits('train');dv=splits('dev');L=table();tl=torch.from_numpy(L);best=None;roster=[];total=0
    for lr in (.003,.012):
        torch.manual_seed(seed);rng=np.random.default_rng(seed+7183);state={}
        for k,shape in [('w1',(13,H)),('w2',(2*H,H)),('head',(T*H*2,10)),('b1',(H,)),('b2',(H,)),('bias',(10,))]:
            state[k]=torch.nn.Parameter(torch.randn(*shape)/np.sqrt(shape[0]) if len(shape)==2 else torch.zeros(*shape))
        optimizer=torch.optim.AdamW(state.values(),lr=lr,weight_decay=.001)
        for step in range(1,361):
            batch=[];target=[]
            for name in ('fsdd','arabic'):
                x,y,_,_=tr[name];ids=rng.integers(0,len(x),size=32);batch.append(x[ids]);target.append(y[ids])
            x=torch.from_numpy(np.concatenate(batch));y=torch.from_numpy(np.concatenate(target))
            h=torch_lower(x,state,tl);f=torch_upper(h,state['w2'],state['b2'],tl);z=f.flatten(1)@state['head']+state['bias']
            loss=F.cross_entropy(z,y);optimizer.zero_grad();loss.backward();optimizer.step();total+=len(x)
            if step in (32,100,200,360):
                s={k:v.detach().numpy().copy() for k,v in state.items()};m={k:summarize(logits(lower(dv[k][0],s,L),s,L),dv[k]) for k in ('fsdd','arabic')}
                quality=(sum(z['macro'] for z in m.values()),-sum(z['brier'] for z in m.values()))
                rec={'lr':lr,'step':step,'dev':small(m),'observed_s':use()['wall_s']};roster.append(rec)
                if best is None or quality>best:
                    best=quality;chosen=rec;weights=s
    dest.mkdir(parents=True,exist_ok=True);np.savez(dest/'parent.npz',**weights)
    dump(dest/'parent.json',dict(seed=seed,roster=roster,selection=chosen,train_forward_examples=total,train_backward_examples=total,checkpoint=sha(dest/'parent.npz'),development_only=True,**use()))
    print(seed,chosen['lr'],chosen['step'],chosen['dev'],flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--seed',type=int,required=True);a=ap.parse_args();main(a.out,a.seed)
