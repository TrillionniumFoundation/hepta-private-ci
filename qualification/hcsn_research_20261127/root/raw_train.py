"""From-random dual-encoder retrieval and exact no-BP CCA readouts."""
import time
START=time.perf_counter()
import argparse,copy,json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from bridge import Branch,SurrogateSpike,WIDTH,rank_vectors,summary,put,sha
ROOT=Path(__file__).resolve().parent
ARMS=('physical','smooth','gru','lif','attention','linear','rawcca','randomphysical','randomgru')
def load(split,inputs):
    with np.load(inputs/f'{split}.npz') as z:
        rgb=torch.from_numpy(z['rgb']).float()/127.5-1
        patches=rgb.reshape(-1,4,8,4,8,3).permute(0,1,3,2,4,5).reshape(-1,16,192)
        sm=rgb.reshape(-1,8,4,8,4,3).mean((2,4)).reshape(-1,192)
        return patches,torch.from_numpy(z['token'].astype('int64')),torch.from_numpy(z['owner'].astype('int64')),sm,torch.from_numpy(z['bow']).float()

class Encoder(nn.Module):
    def __init__(self,kind,vision):
        super().__init__()
        self.vision=vision
        self.front=nn.Linear(192,32) if vision else nn.Embedding(4096,32,padding_idx=0)
        self.temporal=Branch(kind)
        self.temporal.out=nn.Identity()
        self.scale=nn.BatchNorm1d(WIDTH,affine=False)
        self.out=nn.Linear(WIDTH,64)

    def hidden(self,data):
        t=self.temporal
        x=self.front(data).reshape(-1,4,4,32).mean(dim=2)
        seq=torch.cat((x,x.new_zeros(len(x),2,32)),1).transpose(0,1)
        if t.kind in ('physical','attention'):
            return t.core(seq)[-1]
        if t.kind=='gru':
            return t.core(seq)[0][-1]
        if t.kind=='linear':
            return t.core(seq.transpose(0,1).flatten(1))
        h=x.new_zeros(len(x),WIDTH);mem=torch.zeros_like(h);sp=torch.zeros_like(h)
        for fr in seq:
            if t.kind=='smooth':
                v,m=(t.inp(fr)+t.rec(h)).chunk(2,dim=-1)
                h=torch.lerp(h,v.tanh(),m.sigmoid())
            else:
                mem=.9*mem+t.inp(fr)+t.rec(sp);sp=SurrogateSpike.apply(mem-1)
                mem=mem-sp.detach();h=.8*h+sp
        return h

    def forward(self,data):
        return F.normalize(self.out(self.scale(self.hidden(data))),dim=1)

def batch_map(m,x,limit=32):
    return torch.cat([m(x[lo:lo+limit]) for lo in range(0,len(x),limit)])

def features(net,d,hidden=False):
    return [batch_map(m.hidden if hidden else m,x) for x,m in zip(d[:2],net)]

def fitcca(va,ta,owner,shrink):
    img=va.double()
    caps=ta.double()
    texts=torch.zeros(len(img),caps.shape[1],dtype=torch.double)
    texts.index_add_(0,owner,caps)
    texts/=torch.bincount(owner,minlength=len(img)).clamp_min(1)[:,None]
    mi,mt=img.mean(0),texts.mean(0)
    si,st=img.std(0,unbiased=False).clamp_min(1e-6),texts.std(0,unbiased=False).clamp_min(1e-6)
    i,t=(img-mi)/si,(texts-mt)/st
    def whiten(x):
        w,u=torch.linalg.eigh(x.T@x/len(x))
        return (u*(w.clamp_min(0)+shrink).rsqrt()[None,:])@u.T
    wi,wt=whiten(i),whiten(t)
    l,s,r=torch.linalg.svd(wi@(i.T@t/len(i))@wt,full_matrices=False)
    rank=min(16,int((s>1e-10).sum()))
    return {'mi':mi,'mt':mt,'si':si,'st':st,'vi':wi@l[:,:rank],'vt':wt@r.T[:,:rank]}

def ccaencode(v,t,state):
    return F.normalize(((v.double()-state['mi'])/state['si'])@state['vi'],dim=1),F.normalize(((t.double()-state['mt'])/state['st'])@state['vt'],dim=1)

def network(arm):
    k=arm.removeprefix('random')
    return nn.ModuleList([Encoder(k,True),Encoder(k,False)])

def fit(args,folder):
    tr=load('train',args.inputs);dv=load('val',args.inputs)
    rt={'arm':args.arm,'seed':args.seed,'history':[],'steps':args.steps,'torch':torch.__version__,'device':'cpu'}
    best=-1.;upd=0.;dt=0.
    if args.arm in ('rawcca','randomphysical','randomgru'):
        start=time.perf_counter()
        if args.arm=='rawcca':
            a,b=tr[3:5];v,t=dv[3:5];net=None
        else:
            net=network(args.arm).eval()
            with torch.no_grad():
                a,b=features(net,tr,True);v,t=features(net,dv,True)
        rt['feature_seconds']=time.perf_counter()-start
        for reg in (.001,.01,.1,1.):
            start=time.perf_counter();coef=fitcca(a,b,tr[2],reg)
            upd+=time.perf_counter()-start;start=time.perf_counter()
            vv,tt=ccaencode(v,t,coef);m=summary(rank_vectors(vv,tt,dv[2]));dt+=time.perf_counter()-start
            rt['history'].append({'shrink':reg,**m})
            if m['bidir_r1']>best:
                rt['selected']=reg;best=m['bidir_r1'];state={'coef':coef,'model':(None if net is None else net.state_dict())}
    else:
        net=network(args.arm)
        opt=torch.optim.AdamW(net.parameters(),lr=.003,weight_decay=.01)
        rt['trainable_parameters']=sum(p.numel() for p in net.parameters() if p.requires_grad)
        rng=np.random.default_rng(args.seed+31007)
        groups=[np.flatnonzero(tr[2].numpy()==i) for i in range(len(tr[0]))]
        stride=48 if args.steps==192 else 192
        for step in range(args.steps+1):
            if step%stride==0 or step==args.steps:
                start=time.perf_counter();net.eval()
                with torch.no_grad():
                    v,t=features(net,dv);m=summary(rank_vectors(v,t,dv[2]))
                dt+=time.perf_counter()-start
                rt['history'].append({'step':step,**m})
                if m['bidir_r1']>best:
                    best=m['bidir_r1'];rt['selected']=step;state=copy.deepcopy(net.state_dict())
                if step==args.steps:break
            start=time.perf_counter();net.train()
            i=rng.choice(len(groups),16,replace=False)
            t=[rng.choice(groups[k]) for k in i]
            v=net[0](tr[0][i]);lang=net[1](tr[1][t])
            sims=v@lang.T/.07;y=torch.arange(len(v))
            loss=(F.cross_entropy(sims,y)+F.cross_entropy(sims.T,y))*.5
            opt.zero_grad(set_to_none=True);loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(net.parameters(),1)
            if not torch.isfinite(norm):raise FloatingPointError('gradients')
            opt.step();upd+=time.perf_counter()-start
    torch.save(state,folder/'selected.tmp');(folder/'selected.tmp').replace(folder/'selected.pt')
    rt.update(update_seconds=upd,development_seconds=dt,cold_elapsed_seconds=time.perf_counter()-START,state_sha256=sha(folder/'selected.pt'))
    put(folder/'fit.json',rt);print(args.arm,args.seed,rt['selected'],rt['cold_elapsed_seconds'],flush=True)

def test(args,loc):
    seal=json.loads((args.out/'seal.json').read_bytes())
    assert sha(loc/'selected.pt')==seal['states'][loc.name]
    state=torch.load(loc/'selected.pt',weights_only=True);d=load('test',args.inputs)
    t=time.perf_counter()
    with torch.no_grad():
        if args.arm=='rawcca':
            v,l=ccaencode(d[3],d[4],state['coef'])
        elif args.arm.startswith('random'):
            net=network(args.arm).eval();net.load_state_dict(state['model'])
            v,l=ccaencode(*features(net,d,True),state['coef'])
        else:
            net=network(args.arm).eval();net.load_state_dict(state)
            v,l=features(net,d)
        ranks=rank_vectors(v,l,d[2])
    np.savez_compressed(loc/'ranks.npz',image=ranks[0],caption=ranks[1],owner=ranks[2])
    put(loc/'test.json',{'metrics':summary(ranks),'query_seconds':time.perf_counter()-t,'cold_elapsed_seconds':time.perf_counter()-START,'ranks_sha256':sha(loc/'ranks.npz')})

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('fit','test'));p.add_argument('arm',choices=ARMS);p.add_argument('seed',type=int)
    p.add_argument('--steps',type=int,default=192);p.add_argument('--inputs',type=Path,default=ROOT/'raw_inputs');p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();torch.set_num_threads(1);torch.manual_seed(a.seed)
    loc=a.out/f'{a.arm}-{a.seed}';loc.mkdir(exist_ok=True,parents=True)
    (fit if a.mode=='fit' else test)(a,loc)
if __name__=='__main__':main()
