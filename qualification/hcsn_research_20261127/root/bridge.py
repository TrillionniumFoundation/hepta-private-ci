"""Compare frozen CLIP residuals on paired COCO retrieval with a sealed test split."""
import time
START = time.perf_counter()
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from qualification.hcsn_closure_20261124.boundary_fix import BoundaryControlHCSN
from qualification.hcsn_closure_20261124.baselines import SurrogateSpike, CausalTransformer, BaselineState
from qualification.hcsn_smallnet_20261124.model import ModelConfig

ROOT = Path(__file__).resolve().parent
ARMS = ('physical','smooth','gru','lif','attention','linear','identity','procrustes')
SEEDS = (27,117,207)
WIDTH = 20

def put(path, value):
    temp = path.parent / (path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=1, allow_nan=False))
    temp.replace(path)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while part := f.read(1<<20):
            h.update(part)
    return h.hexdigest()

def inputs(split):
    out = []
    for mod in ('vision','text'):
        with np.load(ROOT/'features'/f'{mod}-{split}.npz') as f:
            tok = torch.from_numpy(f['tokens'])
            glob = F.normalize(torch.from_numpy(f['global_embedding']),dim=-1)
            idx = torch.from_numpy(f['index'])
        out.append((tok,glob,idx))
    assert torch.equal(out[0][2],torch.arange(len(out[0][2])))
    assert len(out[0][2]) == len(out[1][2].unique())
    return out

def standardized(train, other):
    ans = []
    for (t,_,_), (x,g,i) in zip(train,other):
        sd, avg = torch.std_mean(t.flatten(0,1),dim=0,unbiased=False)
        ans.append((((x-avg)/sd.clamp_min(.01)).clamp(-5,5),g,i))
    return ans

class FeatureAttention(CausalTransformer):
    def initial_state(self,batch,initial_margin=None):
        # The identity readout has no parameters; the input projection owns the same dtype and device.
        empty=self.input.weight.new_zeros(batch,0,self.config.width)
        return BaselineState((empty,empty.clone()),0)

class Branch(nn.Module):
    def __init__(self,kind):
        super().__init__()
        self.kind = kind
        if kind == 'physical':
            c = ModelConfig(input_size=32,neurons=8,precision='mixed',backend='uniformized')
            self.core = BoundaryControlHCSN(c,channel='boundary_signed',control_mode='raw',boundary_mode='centered')
            self.core.readout = nn.Identity()
        elif kind == 'attention':
            self.core = FeatureAttention(WIDTH)
            self.core.input = nn.Linear(32,WIDTH)
            self.core.readout = nn.Identity()
        elif kind == 'gru':
            self.core = nn.GRU(32,WIDTH)
        elif kind == 'linear':
            self.core = nn.Linear(6*32,WIDTH)
        elif kind in ('smooth','lif'):
            width = 2*WIDTH if kind == 'smooth' else WIDTH
            self.inp = nn.Linear(32,width)
            self.rec = nn.Linear(WIDTH,width,bias=False)
        else:
            raise ValueError(kind)
        self.out = nn.Linear(WIDTH,512)
        nn.init.zeros_(self.out.weight)
        nn.init.zeros_(self.out.bias)

    def forward(self,x,g):
        x = torch.cat((x, x.new_zeros(len(x),2,32)),dim=1)
        seq = x.transpose(0,1)
        if self.kind in ('physical','attention'):
            h = self.core(seq)[-1]
        elif self.kind == 'gru':
            h = self.core(seq)[0][-1]
        elif self.kind == 'linear':
            h = self.core(x.flatten(1))
        else:
            h = x.new_zeros(len(x),WIDTH)
            spike = torch.zeros_like(h)
            membrane = torch.zeros_like(h)
            for frame in seq:
                if self.kind == 'smooth':
                    value, mix = (self.inp(frame)+self.rec(h)).chunk(2,dim=-1)
                    h = torch.lerp(h,value.tanh(),mix.sigmoid())
                else:
                    membrane = .9*membrane+self.inp(frame)+self.rec(spike)
                    spike = SurrogateSpike.apply(membrane-1)
                    membrane = membrane-spike.detach()
                    h = .8*h+spike
        return F.normalize(g+.2/math.sqrt(512)*self.out(h).tanh(),dim=-1)

class Bridge(nn.Module):
    def __init__(self,kind):
        super().__init__()
        self.layers = nn.ModuleList([Branch(kind),Branch(kind)])

    def forward(self,samples, ids=None):
        if ids is not None:
            return [m(x[k],g[k]) for (x,g,_), k,m in zip(samples,ids,self.layers)]
        return [torch.cat([m(x[lo:lo+12],g[lo:lo+12]) for lo in range(0,len(x),12)]) for (x,g,_),m in zip(samples,self.layers)]

def rank_vectors(vision, lang, owner):
    score = (vision@lang.T).numpy()
    owner = owner.numpy()
    order_text = np.argsort(-score,axis=1,kind='stable')
    order_img = np.argsort(-score.T,axis=1,kind='stable')
    img_ranks = 1+np.argmax(owner[order_text] == np.arange(len(vision))[:,None],axis=1)
    cap_ranks = 1+np.argmax(order_img == owner[:,None],axis=1)
    return img_ranks,cap_ranks,owner

def summary(r):
    i,t,owner = r
    lut = {}
    for key,rank in [('image_to_text',i),('text_to_image',t)]:
        lut[key] = {f'r{k}':float(np.mean(rank<=k)) for k in (1,5,10)}
        lut[key]['mrr'] = float(np.mean(1/rank))
    lut['bidir_r1'] = .5*(lut['image_to_text']['r1']+lut['text_to_image']['r1'])
    return lut

def cost(t):
    return time.perf_counter()-t

def fit(args,loc):
    tr,dev = inputs('train'),inputs('val')
    dev,tr = standardized(tr,dev),standardized(tr,tr)
    art = {'arm':args.arm,'seed':args.seed,'torch':torch.__version__,'device':'cpu','history':[]}
    start = time.perf_counter()
    if args.arm in ('identity','procrustes'):
        v = tr[0][1]
        r = torch.eye(v.shape[1])
        if args.arm == 'procrustes':
            cent = torch.stack([tr[1][1][tr[1][2]==i].mean(dim=0) for i in range(len(v))])
            u,_,vh = torch.linalg.svd(v.T@F.normalize(cent,dim=1),full_matrices=False)
            r = u@vh
        art['update_seconds'] = cost(start)
        best = -1
        for a in ([0] if args.arm=='identity' else [0,.01,.03,.1,.25,.5,1]):
            v,g = dev[0][1],dev[1][1]
            vv = F.normalize((1-a)*v+a*(v@r),dim=1)
            m = summary(rank_vectors(vv,g,dev[1][2]))
            art['history'].append({'a':a,**m})
            if m['bidir_r1'] > best:
                best, chosen = m['bidir_r1'], a
        state = {'r':r,'alpha':chosen}
        art['selected'] = chosen
    else:
        net = Bridge(args.arm)
        opt = torch.optim.AdamW(net.parameters(),lr=.003,weight_decay=.01)
        batches = np.random.default_rng(args.seed+31007)
        groups = [np.flatnonzero(tr[1][2].numpy()==i) for i in range(len(tr[0][2]))]
        best,updates,valid = -1,0,0
        for step in range(129):
            if step%32 == 0:
                devtime=time.perf_counter()
                with torch.no_grad():
                    v,g = net(dev)
                    m = summary(rank_vectors(v,g,dev[1][2]))
                art['history'].append({'step':step,**m})
                valid+=cost(devtime)
                if m['bidir_r1'] > best:
                    best = m['bidir_r1']
                    art['selected'] = step
                    state = copy.deepcopy(net.state_dict())
                if step==128:
                    break
            fitstart = time.perf_counter()
            vi = batches.choice(len(groups),12,replace=False)
            ci = [batches.choice(groups[k]) for k in vi]
            vi,ci = torch.tensor(vi),torch.tensor(ci)
            v,g = net(tr,[vi,ci])
            sim = v@g.T/.07
            y = torch.arange(len(vi))
            loss = .5*(F.cross_entropy(sim,y)+F.cross_entropy(sim.T,y))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),1)
            opt.step()
            updates+=cost(fitstart)
        art.update(update_seconds=updates,development_seconds=valid,parameters=sum(p.numel() for p in net.parameters()),trainable_parameters=sum(p.numel() for p in net.parameters() if p.requires_grad))
    torch.save(state,loc/'selected.pt.tmp')
    (loc/'selected.pt.tmp').replace(loc/'selected.pt')
    art.update(cold_elapsed_seconds=cost(START),state_sha256=sha(loc/'selected.pt'))
    put(loc/'fit.json',art)
    print(args.arm,args.seed,art['selected'],art['cold_elapsed_seconds'],flush=True)

def confirm(args,loc):
    seal = json.loads((args.out/'seal.json').read_text())
    if seal['states'][loc.name]!=sha(loc/'selected.pt'):
        raise ValueError('selected state and seal disagree')
    state = torch.load(loc/'selected.pt',weights_only=True)
    data = standardized(inputs('train'),inputs('test'))
    begin = time.perf_counter()
    with torch.no_grad():
        if args.arm in ('identity','procrustes'):
            v,g = data[0][1],data[1][1]
            a,r = state['alpha'],state['r']
            v = F.normalize((1-a)*v+a*(v@r),dim=1)
        else:
            net = Bridge(args.arm)
            net.load_state_dict(state)
            v,g = net(data)
        ranks = rank_vectors(v,g,data[1][2])
    np.savez_compressed(loc/'ranks.npz',image=ranks[0],caption=ranks[1],owner=ranks[2])
    put(loc/'test.json',{'metrics':summary(ranks),'query_seconds':cost(begin),'cold_elapsed_seconds':cost(START),'ranks_sha256':sha(loc/'ranks.npz')})

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['fit','test'])
    p.add_argument('arm',choices=ARMS)
    p.add_argument('seed',type=int)
    p.add_argument('--out',type=Path,default=ROOT/'retrieval')
    args=p.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(args.seed)
    loc=args.out/f'{args.arm}-{args.seed}'
    loc.mkdir(parents=True,exist_ok=True)
    (fit if args.mode=='fit' else confirm)(args,loc)
if __name__=='__main__':
    main()
