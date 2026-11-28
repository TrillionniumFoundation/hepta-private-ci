"""Independent NumPy serial-neuron and dense-attention replay of all 30 held decoders."""
from argparse import ArgumentParser
import json
from pathlib import Path
import numpy as np
from scipy.special import logsumexp,ndtr,expit
from data import streams,START,EOS,PAD,SENTENCES


def forward(tokens,weights,kind,gain,events=None):
    def linear(x,key):return x@weights[key+".weight"].T+weights[key+".bias"]
    def norm(x,key):
        m=x.mean(-1,keepdims=True);s=np.mean((x-m)**2,axis=-1,keepdims=True)
        return (x-m)/np.sqrt(s+1e-5)*weights[key+".weight"]+weights[key+".bias"]
    x=weights["embed.weight"][tokens]+weights["pos.weight"][:tokens.shape[1]]
    for i in (0,1):
        c=f"cells.{i}."
        if kind.startswith("sdpa"):
            b,t,d=x.shape
            q,k,v=linear(norm(x,c+"norm"),c+"qkv").reshape(b,t,3,2,d//2).transpose(2,0,3,1,4)
            score=(q@k.swapaxes(-1,-2))/np.sqrt(d//2)
            score=np.where(np.tril(np.ones((t,t),dtype=bool)),score,-np.inf)
            att=np.exp(score-logsumexp(score,axis=-1,keepdims=True))@v
            start=x+linear(att.transpose(0,2,1,3).reshape(b,t,d),c+"out")
            ff=linear(norm(start,c+"ff.0"),c+"ff.1")
            x=start+linear(ff*ndtr(ff),c+"ff.3")
        else:
            z=linear(norm(x,c+"norm"),c+"projection");mem=np.zeros_like(z[:,0]);seq=[]
            if kind=="lif":
                leak=expit(weights[c+"leak"])
                for t,h in enumerate(z.transpose(1,0,2)):
                    mem=leak*mem+h;spike=(mem>.6).astype(float)
                    if events is not None:events[i,t]=(mem.copy(),spike.copy())
                    mem=mem*(1-spike);seq.append(spike)
            else:
                table=weights[c+"table"]
                for h in z.transpose(1,0,2):
                    v=np.tanh(h)
                    xindex=(v+1)*(len(table)-1)/2
                    i0=xindex.astype(int).clip(0,len(table)-2)
                    e,l,f=(table[i0]+(xindex-i0)[:,:,None]*(table[i0+1]-table[i0])).transpose(2,0,1)
                    # Explicit serial recurrence is independent of Torch prefix products.
                    wire=np.log1p(gain*np.tanh(h+3*mem))/gain
                    margin=np.log(1.12)-np.log1p(gain*v);a=.89+.105*(1-f)
                    force=-.85*np.tanh(e)*(.15-margin)+.90*np.tanh(l)
                    mem=a*mem+(1-a)*force;seq.append(wire)
            x=np.stack(seq,axis=1)
    return linear(x,"logits")


def inspect_threshold(net,token,w,gain,target_row):
    import torch
    data={}
    forward(token.numpy(),w,"lif",gain,data)
    with torch.no_grad():
        a=net.embed(token)+net.pos(torch.arange(token.shape[1]))
        for k,core in enumerate(net.cells):
            z=core.projection(core.norm(a))
            mem=torch.zeros_like(z[:,0]);sp=[]
            for i,h in enumerate(z.unbind(1)):
                mem=core.leak.sigmoid()*mem+h
                hard=(mem>.6).float()
                ref,other=data[k,i]
                mask=(hard.numpy()[target_row]!=other[target_row])
                if mask.any():
                    u=mem.numpy()[target_row,mask];v=ref[target_row,mask]
                    near=float(max(abs(u-.6).max(),abs(v-.6).max()))
                    if near>4e-6:raise ArithmeticError(("unexpected event difference",near))
                    return dict(layer=k,token=i,near_threshold=near,native=u.tolist(),independent=v.tolist())
                mem=mem*(1-hard);sp.append(hard)
            a=torch.stack(sp,dim=1)
    return None


def main(folder):
    from hashlib import sha256
    from network import make_table
    from evaluate import load_net,evaluate
    from train import SEEDS
    import torch
    gain=make_table("financial")[1]
    x,y,(_,_,ix),actors,modes,V,_=streams()
    x=x[ix].numpy();y=y[ix].numpy();mode=modes[ix]
    official=json.loads((folder/"terminal.json").read_text())
    totals=dict(models=0,clips_by_task=0,original_token_logps=0,greedy_decisions=0,
                mismatched_greedy=0,max_nonoptimal_logit_gap=0.,max_logp_error=0.,max_nll_error=0.)
    perrow={};numeric_events=[]
    source_x,source_y,_,_,allm,V,_=streams()
    for key,row in official["rows"].items():
        path=folder/(key+"-original-test.npz")
        assert sha256(path.read_bytes()).hexdigest()==row["scores"]
        with np.load(folder/(key+".npz")) as f:w={k:v.astype(float) for k,v in f.items()}
        with np.load(path) as f:lp=f["logp"];pred=f["generated"]
        kind=key.split("-")[0];d=0.;mismatch=0;active_tokens=0;worst=0.
        study=json.loads((folder/("-".join(key.split("-")[:2])+"-seal.json")).read_text())
        net=load_net(study,folder/(key+".npz"),V)
        _,native,native_choices=evaluate(net,source_x,source_y,ix,allm)
        assert np.array_equal(native,lp)
        large_indices=set();delta_nll=[]
        for begin in range(0,len(ix),48):
            sl=slice(begin,begin+48);x0=x[sl];t=y[sl];p=pred[sl];valid=t>=0
            z=forward(x0,w,kind,gain)[:,START:]
            got=np.take_along_axis(z,t.clip(0)[:,:,None],axis=2).squeeze(2)-logsumexp(z,axis=-1)
            dif=abs(lp[sl]-got)
            d=max(d,float(dif[valid].max()))
            delta_nll.extend((lp[sl]-got)[valid].tolist())
            for local in np.flatnonzero((dif*valid).max(1)>.001):large_indices.add(begin+int(local))
            test=x0.copy();test[:,START+1:]=p[:,:-1]
            z=forward(test,w,kind,gain)[:,START:]
            # Unmasked free running can output PAD as a genuine mistake, so recover
            # the scored horizon from first EOS and the pre-registered per-modality cap.
            cap=np.where(mode[sl]==2,max(len(s.split()) for s in SENTENCES.values())+2,17)
            pos=np.arange(17)[None,:]
            eos=(p==EOS)
            stop=np.where(eos.any(1),eos.argmax(1)+1,17)
            active=pos<np.minimum(cap,stop)[:,None]
            wrong=(z.argmax(2)!=p)&active
            if wrong.any():
                selected=np.take_along_axis(z,p[:,:,None],axis=2).squeeze(-1)
                worst=max(worst,float((z.max(2)-selected)[wrong].max()))
            mismatch+=int(wrong.sum());active_tokens+=int(active.sum())
        loss=[-float(lp[mode==i].sum(dtype='float64'))/(y[mode==i]!=-100).sum() for i in range(3)]
        lv=float(np.max(abs(np.array(loss)-row["nll"])))
        totals["models"]+=1;totals["clips_by_task"]+=len(ix);totals["original_token_logps"]+=int((y!=-100).sum())
        totals["greedy_decisions"]+=active_tokens;totals["mismatched_greedy"]+=mismatch
        for k,num in [("max_nonoptimal_logit_gap",worst),("max_logp_error",d),("max_nll_error",lv)]:
            totals[k]=max(totals[k],num)
        if large_indices:
            if kind!="lif":raise ArithmeticError(("unexplained smooth score mismatch",key,d))
            # Run both independent forward laws with each original batch grouping;
            # exact native replay above binds these archived logits to these weights.
            for idx in sorted(large_indices):
                group=idx//96*96;take=source_x[ix[group:group+96]]
                # Keep native GEMM shapes; reproduce & localize the first different event.
                event=inspect_threshold(net,take,w,gain,idx-group)
                if event is None:raise AssertionError(("unexplained hard-score difference",key,idx))
                numeric_events.append(dict(checkpoint=key,held_row=idx,**event))
        perrow[key]=dict(mean_signed_float_precision_shift=float(np.mean(delta_nll)),
                         threshold_affected_sequences=len(large_indices),max_logp_error=d,greedy_mismatches=mismatch,max_nonoptimal_logit_gap=worst,greedy_decisions=active_tokens)
        print(key,round(d,8),mismatch,worst,flush=True)
    # A rare hard LIF threshold flip in the independent double-precision forward
    # would be material and must remain visible, separately from near-tied argmaxes.
    assert totals["max_nonoptimal_logit_gap"]<.001 and totals["max_nll_error"]<1e-12
    assert all(abs(r["mean_signed_float_precision_shift"])<.0001 for r in perrow.values())
    return dict(totals=totals,rows=perrow,explained_hard_threshold_rounding=numeric_events)
if __name__=="__main__":
    a=ArgumentParser();a.add_argument("directory",type=Path);s=a.parse_args()
    result=main(s.directory);(s.directory/"verified.json").write_text(json.dumps(result,indent=2)+"\n")
    print(result["totals"])
