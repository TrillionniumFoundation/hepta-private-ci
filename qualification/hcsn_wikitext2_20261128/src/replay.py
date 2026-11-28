"""Independent normalized-word head replay plus held-block temporal perturbations."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F
from train import Windows
from model import LanguageModel


def raw_log_prob(head,h,t):
    root=F.log_softmax(head.root(h),-1)
    g=((t-128).clamp(min=0)//128)
    rare=t>=128
    rr=torch.where(rare,128+g,t)
    s=root.gather(1,rr[:,None]).squeeze(1)
    ii=rare.nonzero().flatten()
    if ii.numel():
        idx=g[ii]
        z=head.rank(F.gelu(h[ii]+head.condition(idx)))+head.prior(idx)
        invalid=128+idx[:,None]*128+torch.arange(128)[None,:]>=head.vocab
        rlog=F.log_softmax(z.masked_fill(invalid,-torch.inf),-1)
        s[ii]+=rlog.gather(1,((t[ii]-128)%128)[:,None]).flatten()
    return -s


def run(root,kind,seed):
    d=Windows(root/'test.npy')
    name=f'{kind}-{seed}'
    r=json.loads((root/'results'/(name+'.json')).read_text())
    p=root/'results'/(name+'-best.pt')
    if hashlib.sha256(p.read_bytes()).hexdigest()!=r['model_sha256']:raise ArithmeticError('Checkpoint mismatch')
    m=LanguageModel(r['metadata']['vocab'],kind).eval()
    m.load_state_dict(torch.load(p,map_location='cpu',weights_only=True))
    rows=[]
    with torch.no_grad():
        for lo in range(0,len(d.x),32):
            ix=torch.arange(lo,min(lo+32,len(d.x)))
            xx=d.x[ix]
            # The first 96 words are either intact or borrowed from a different
            # nonoverlapping official-test block. The last 32 words, identities,
            # positions, and all scoring targets stay fixed in each pair.
            xf=xx.clone();xf[:,:96]=d.x[(ix+97)%len(d.x),:96]
            yy=d.y[ix];ok=yy>=0
            hs=m.encode(xx);hf=m.encode(xf)
            vals=torch.zeros_like(xx,dtype=torch.float64)
            vals[ok]=raw_log_prob(m.head,hs[ok],yy[ok]).double()
            interest=torch.zeros_like(ok);interest[:,112:]=ok[:,112:]
            tail=torch.zeros_like(vals)
            tail[interest]=raw_log_prob(m.head,hf[interest],yy[interest]).double()
            metric=torch.stack([vals.sum(1),ok.sum(1),vals[:,112:].sum(1),tail[:,112:].sum(1),interest.sum(1)],1)
            rows.extend(metric.tolist())
    a=np.asarray(rows);test=a[:,0].sum()/a[:,1].sum()
    if abs(test-r['test']['nll'])>2e-7:raise ArithmeticError((name,test,r['test']))
    out=dict(kind=kind,seed=seed,whole_test_nll=test,test_targets=int(a[:,1].sum()),
             clean_last16_nll=float(a[:,2].sum()/a[:,4].sum()),altered_last16_nll=float(a[:,3].sum()/a[:,4].sum()),
             suffix_targets=int(a[:,4].sum()),min_separation_to_changed_token=17,donor_block_offset=97)
    np.savez_compressed(root/'results'/(name+'-blocks.npz'),metrics=a)
    (root/'results'/(name+'-replay.json')).write_text(json.dumps(out,indent=2)+'\n')
    print(name,out,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('kind');p.add_argument('seed',type=int)
    z=p.parse_args();torch.set_num_threads(1);run(z.root,z.kind,z.seed)
