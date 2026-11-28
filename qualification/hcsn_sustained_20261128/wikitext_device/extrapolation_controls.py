"""Post-primary diagnostic separating position reuse from access to distant attention keys."""
from hashlib import sha256
import json,sys
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from evaluate_wiki import load
from stream_wiki import State

ROOT=Path(__file__).resolve().parent


def measure(model,kind,ix,position,window,inspect=False):
    n,T=ix.shape;pos=torch.arange(T,device=ix.device);m=model.pos
    if position=='periodic':posval=m[pos%128]
    elif position=='clamp':posval=m[pos.clamp_max(127)]
    elif position=='zero_tail':
        posval=torch.where((pos<128)[:,None],m[pos.clamp_max(127)],0.)
    else:raise ValueError(position)
    h=model.emb(ix)+posval
    helper=State(model,kind,n,T)
    attention=[]
    if kind=='sdpa' and window is not None:
        delta=pos[:,None]-pos[None,:];allow=(delta>=0)&(delta<window)
    for bl in model.blocks:
        if kind=='hx':
            h,_=helper.hx(bl,h,torch.zeros_like(h[:,0]))
            continue
        q,k,v=bl.qkv(bl.pre(h)).chunk(3,-1)
        def heads(z):return z.unflatten(-1,(4,z.size(-1)//4)).transpose(1,2)
        q,k,v=map(heads,(q,k,v))
        if inspect:
            selects=torch.arange(255,T,128,device=ix.device)
            dots=(q[:,:,selects]@k.transpose(-2,-1))*q.size(-1)**-.5
            future=pos[None,:]>selects[:,None]
            weight=dots.masked_fill(future,-torch.inf).softmax(-1)
            distant=(selects[:,None]-pos[None,:])>=128
            attention.append((weight*distant).sum(-1).cpu().numpy())
        if window is None:z=F.scaled_dot_product_attention(q,k,v,is_causal=True)
        else:z=F.scaled_dot_product_attention(q,k,v,attn_mask=allow)
        h=h+bl.out(z.transpose(1,2).flatten(-2));h=h+bl.ff(h)
    return model.norm(h),attention


def main(root):
    torch.set_num_threads(1)
    a,m,prior=load(root);N=len(a)-1;rows=[];raw={}
    with torch.inference_mode():
        for W in (512,2048):
            n=(N+W-1)//W;sz=max(1,8192//W)
            x=F.pad(a[:-1],(0,W*n-N)).view(n,W);y=F.pad(a[1:],(0,W*n-N),value=-1).view(n,W)
            for k,net in m.items():
                for pos in ('periodic','clamp','zero_tail'):
                    for cap in ((None,128) if k=='sdpa' else (None,)):
                        losses=[];over=[[],[]];nt=[0,0,0];sums=[0.,0.,0.]
                        for st in range(0,n,sz):
                            ix=x[st:st+sz];targets=y[st:st+len(ix)]
                            diagnose=k=='sdpa' and pos=='periodic' and cap is None
                            h,att=measure(net,k,ix,pos,cap,inspect=diagnose)
                            flat=targets.flatten();valid=flat>=0
                            loss=net.head(h.flatten(0,1)[valid],flat[valid]).cpu().numpy()
                            losses.append(loss)
                            tkn=np.broadcast_to(np.arange(W),(len(ix),W)).reshape(-1)[valid.cpu().numpy()]
                            for j,b in enumerate([tkn<128,(tkn>=128)&(tkn<256),tkn>=256]):
                                nt[j]+=int(b.sum());sums[j]+=loss[b].sum(dtype=np.float64)
                            if diagnose:
                                observed=targets[:,255::128].cpu().numpy()>=0
                                for j,block in enumerate(att):
                                    over[j].append(block.transpose(0,2,1)[observed])
                        v=np.concatenate(losses)
                        assert len(v)==N
                        key=f'{k}_{pos}_{cap}_{W}'
                        raw[key]=np.pad(v.astype(np.float64),(0,(-N)%128)).reshape(-1,128).sum(1)
                        row=dict(kind=k,position=pos,local_attention_window=cap,window=W,nll=float(v.mean(dtype=np.float64)),
                                 target_nll_by_withinwindow_position=[s/t if t else None for s,t in zip(sums,nt)])
                        if over[0]:
                            row['distant_attention_fraction_by_layer_head']=[np.concatenate(z).mean(axis=0,dtype=np.float64).tolist() for z in over]
                            row['queries_per_head']=int(sum(len(z) for z in over[0]))
                        rows.append(row);print(key,row['nll'],flush=True)
    path=ROOT/'control_block_sums.npz';np.savez_compressed(path,**raw)
    (ROOT/'control_scores.json').write_text(json.dumps(dict(scope='post-primary; no fitting or method selection',rows=rows,
        raw_sha256=sha256(path.read_bytes()).hexdigest()),indent=2)+'\n')
if __name__=='__main__':main(Path(sys.argv[1]))
