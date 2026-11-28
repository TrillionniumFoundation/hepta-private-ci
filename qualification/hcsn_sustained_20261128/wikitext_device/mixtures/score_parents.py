"""Materialize normalized observed-word log-probabilities of original validation-selected checkpoints."""
from hashlib import sha256
from pathlib import Path
import argparse
import json
import sys
import time
import numpy as np
import torch
from torch.nn import functional as F

SPLITS=('valid','test')
EXPECTED={'train':'d5163de236cc4b80fa5c2f2aa3b829899ae21d97700c96d1a459ac457e36574e',
          'valid':'9b16c5b84685239c7af3673eb31ba6df93354547d5999780ec08a6b1f4d458b6',
          'test':'66a09df53e4ff74fcf7984bc98b0db3bba8623c475a46aad72b39ac065464651'}
def verified(root,s):
    v=np.load(root/(s+'.npy'))
    assert sha256(v.tobytes()).hexdigest()==EXPECTED[s]
    return v


def probability(head,h,t):
    rootlog=F.log_softmax(head.root(h),dim=1)
    israre=t>=head.direct
    group=torch.div(torch.clamp(t-head.direct,min=0),head.width,rounding_mode='floor')
    rt=torch.where(israre,group+head.direct,t)
    result=rootlog[torch.arange(len(t),device=t.device),rt]
    sel=torch.nonzero(israre,as_tuple=True)[0]
    if len(sel):
        g=group[sel]
        rank=head.rank(F.gelu(h[sel]+head.condition(g)))+head.prior(g)
        legal=g[:,None]*head.width+head.direct+head.bins[None,:]<head.vocab
        ranklog=F.log_softmax(rank.masked_fill(~legal,-torch.inf),1)
        result[sel]+=ranklog[torch.arange(len(sel),device=t.device),(t[sel]-head.direct)%head.width]
    return result


def count(root,out):
    tr=verified(root,'train').astype(np.int64);vocab=33278
    assert tr[0]==8
    left=tr[:-1];right=tr[1:];pairs,n=np.unique(left*vocab+right,return_counts=True)
    ctx=np.bincount(left,minlength=vocab)
    distinct=np.bincount(pairs//vocab,minlength=vocab)
    cont=np.bincount(pairs%vocab,minlength=vocab)+.1;cont/=cont.sum()
    vals={}
    for s in SPLITS:
        a=verified(root,s).astype(np.int64)
        i,j=a[:-1],a[1:]
        pair=i*vocab+j
        pos=np.minimum(np.searchsorted(pairs,pair),len(pairs)-1)
        seen=n[pos]*(pairs[pos]==pair)
        prob=(np.maximum(seen-.75,0)+.75*distinct[i]*cont[j])/np.maximum(ctx[i],1)
        prob=np.where(ctx[i]>0,prob,cont[j])
        vals[s]=np.log(prob)
        vals[s+'_bucket']=np.select([i==8,ctx[i]<10,ctx[i]<100],[0,1,2],default=3).astype(np.uint8)
    f=out/'bigram.npz';np.savez_compressed(f,**vals)
    print('bigram',float(-vals['test'].mean()),sha256(f.read_bytes()).hexdigest(),flush=True)


def run(root,out,seed,kind,device):
    sys.path.insert(0,str(root/'src'))
    from model import LanguageModel
    checkpoint=root/'results'/f'{kind}-{seed}-best.pt'
    report=json.loads((root/'results'/f'{kind}-{seed}.json').read_text())
    modelhash=sha256(checkpoint.read_bytes()).hexdigest();assert modelhash==report['model_sha256']
    net=LanguageModel(33278,kind)
    net.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True));net.to(device).eval()
    for W in ((128,2048) if seed==887 and kind in ('hx','sdpa') else (128,)):
        start=time.perf_counter();output={}
        for s in SPLITS:
            a=torch.from_numpy(verified(root,s)).long().to(device);n=len(a)-1
            pad=(-n)%W
            x=F.pad(a[:-1],(0,pad)).reshape(-1,W);y=F.pad(a[1:],(0,pad),value=-1).reshape(-1,W)
            lps=[]
            with torch.inference_mode():
                for j in range(0,len(x),max(1,4096//W)):
                    xx=x[j:j+max(1,4096//W)];yy=y[j:j+len(xx)].flatten()
                    if W==128:h=net.encode(xx)
                    else:
                        from stream_wiki import State
                        h=State(net,kind,len(xx),W).append(xx)
                    ok=yy>=0;lps.append(probability(net.head,h.flatten(0,1)[ok],yy[ok]).cpu().numpy())
            output[s]=np.concatenate(lps)
            assert len(output[s])==n and np.isfinite(output[s]).all()
            if W==128:
                if s=='test':expected=report['test']['nll']
                else:expected=next(r for r in report['epochs'] if r['epoch']==report['selected_epoch'])['valid']['nll']
                assert abs(-float(output[s].mean(dtype=np.float64))-expected)<2e-6
        name=f'{kind}-{seed}-{W}';dest=out/(name+'.npz');np.savez_compressed(dest,**output)
        receipt=dict(weight_sha256=modelhash,array_sha256=sha256(dest.read_bytes()).hexdigest(),seed=seed,kind=kind,
                     window=W,seconds=time.perf_counter()-start,device=str(device),torch=str(torch.__version__),
                     valid=len(output['valid']),test=len(output['test']))
        (out/(name+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
        print(name,receipt['seconds'],flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('out',type=Path)
    ap.add_argument('--seed',type=int);ap.add_argument('--arm',choices=('hx','sdpa','smooth'));ap.add_argument('--device',default='cpu')
    z=ap.parse_args();z.out.mkdir(exist_ok=True,parents=True);torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if z.seed is None:count(z.root,z.out)
    elif z.arm:run(z.root,z.out,z.seed,z.arm,z.device)
    else:
        for kind in ('hx','sdpa','smooth'):run(z.root,z.out,z.seed,kind,z.device)
