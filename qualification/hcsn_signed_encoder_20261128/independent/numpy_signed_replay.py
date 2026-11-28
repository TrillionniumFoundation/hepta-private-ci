"""Rebuild the complete signed/free/control study in float64 using only NumPy to evaluate models."""
import argparse
import ctypes
import json
from pathlib import Path
import numpy as np
import torch
from numpy_population_replay import SHA_DATA,sha,linear,layer_norm,interp,ndtr

def encode(x,s,arm,phi):
    batch,frames,width=x.shape
    grid=s["law.grid"];reset=s["law.reset"];xstar=grid@reset
    previous=None;group=16;error=0.;bounds=0.
    for i in range(6):
        p=f"mixer.{i}.";n=layer_norm(x,s,f"n1.{i}")
        drive=linear(n,s,p+"drive")
        if previous is not None:drive+=linear(previous,s,p+"wire")
        values=linear(n,s,p+"value").reshape(batch,frames,group,-1)
        mass=np.broadcast_to(reset,(batch,group,len(grid))).copy()
        mark=np.zeros((batch,group));ref=mark.copy();quote=np.zeros((batch,group,2))
        memory=np.zeros((batch,group,width//group));states=[];read=[];marks=[]
        w=s[p+"feedback"]
        gains=1.3*np.tanh(np.arctanh(.5)+w/3) if arm=="free" else 1.3/(1+np.exp(-w))
        for time in range(frames):
            u=np.tanh(drive[:,time]+linear(mark,s,p+"recurrent"))
            wall=np.log1p(s["law.kappa"]*u)
            alive=mass.sum(-1);first=mass@grid
            mean=np.divide(first,alive,out=np.full_like(first,xstar),where=alive>0)
            signal=np.tanh(np.stack((first/xstar,ref),-1)) if arm=="nonfinancial" else np.tanh(np.maximum(0,quote))
            force=gains[:,0]*signal[...,0]*(xstar-mean)-gains[:,1]*signal[...,1]
            actual=.03355-.15*u+(mark-wall)/.25+(0. if arm=="noforce" else force)
            bounds=max(bounds,float(np.abs(actual).max()))
            prob=interp(s["law.force_transition"],(actual+5)*409.6)
            moved=np.einsum("bgk,bgkj->bgj",mass,prob)
            mass=moved[...,:-1]+ref[...,None]*reset
            ref=moved[...,-1];mark=wall
            error=max(error,float(np.abs(mass.sum(-1)+ref-1).max()))
            prices=s["law.pmid"]+u[...,None,None]*s["law.pd"]
            quote=np.einsum("bgi,bgij->bgj",mass,prices)
            memory=memory+(values[:,time]-memory)*ref[...,None]
            states.append(memory);marks.append(mark)
            read.append(np.stack((wall,ref,mass.sum(-1),quote[...,0],quote[...,1]),-1))
        previous=np.stack(marks,1)
        y=linear(np.stack(states,1).reshape(batch,frames,width),s,p+"output")
        y+=linear(np.stack(read,1).reshape(batch,frames,-1),s,p+"read")
        x=x+y
        ff=linear(layer_norm(x,s,f"n2.{i}"),s,f"ff.{i}.0")
        x=x+linear(ff*phi(ff),s,f"ff.{i}.2")
    v=linear(layer_norm(x[:,-1],s,"out.0"),s,"out.1")
    return v/np.maximum(1e-12,np.linalg.norm(v,axis=-1,keepdims=True)),error,bounds

def main(a):
    assert sha(a.data)==SHA_DATA
    with np.load(a.data,allow_pickle=False) as f:
        split=f["split"];tr=np.flatnonzero(split==0);v=f["images"];au=f["audio"];tokens=f["tokens"]
        mean=au[tr].mean((0,1),dtype=np.float64).astype("float32")
        sd=au[tr].std((0,1),dtype=np.float64).clip(.01).astype("float32")
        select={name:np.flatnonzero(split==i) for name,i in [("development",1),("held",2)]}
    phi=ndtr
    if a.cdf_library:
        ptr=np.ctypeslib.ndpointer(dtype=np.float64,flags="C_CONTIGUOUS");lib=ctypes.CDLL(str(a.cdf_library.resolve()))
        cdf=lib.normal_cdf;cdf.argtypes=(ptr,ptr,ctypes.c_size_t);cdf.restype=None
        def phi(x):
            x=np.ascontiguousarray(x,dtype=np.float64);res=np.empty_like(x);cdf(x,res,x.size);return res
    end=json.loads((a.run/"terminal.json").read_text());seal=json.loads((a.run/"seal.json").read_text())
    assert sha(a.run/"seal.json")==end["seal_sha256"]
    rows={}
    for arm in ("signed","free","nonfinancial","noforce"):
        key=f"{arm}-{a.seed}";root=a.run/key
        for label,stage in seal[key].items():
            w=root/stage["weight"];assert sha(w)==stage["weight_sha"]
            s={k:v.numpy().astype(float) for k,v in torch.load(w,weights_only=True,map_location="cpu").items()}
            prompt,mass,drift=encode(s["word.weight"][tokens]+s["position"]+s["type_code"][1],s,arm,phi)
            for splitname,ids in select.items():
                fname=root/stage["development_scores"] if splitname=="development" else a.run/end["metrics"][key+"/"+label]["held_file"]
                expected=stage["development_sha"] if splitname=="development" else end["metrics"][key+"/"+label]["held_sha"]
                assert sha(fname)==expected
                ix=np.linspace(0,len(ids)-1,min(a.limit,len(ids)),dtype=int) if a.limit else np.arange(len(ids))
                with np.load(fname) as f:reference=f["logits"][ix].astype(float)
                err=0.;mismatch=0;worst_gap=0.
                for start in range(0,len(ix),48):
                    idx=ids[ix[start:start+48]];visual=v[idx].reshape(len(idx),12,-1).astype(float)/127.5-1
                    audio=((au[idx]-mean)/sd).astype(float)
                    av=linear(visual,s,"face")+linear(audio,s,"sound")+s["position"]+s["type_code"][0]
                    emb,e,d=encode(av,s,arm,phi);z=12*emb@prompt.T;r=reference[start:start+len(idx)]
                    err=max(err,float(abs(r-z).max()));mass=max(mass,e);drift=max(drift,d)
                    mis=z.argmax(1)!=r.argmax(1);mismatch+=int(mis.sum())
                    if mis.any():
                        take=np.arange(len(idx));gap=r.max(1)-r[take,z.argmax(1)]
                        worst_gap=max(worst_gap,float(gap[mis].max()))
                assert err<3e-4 and mass<5e-6 and drift<5 and worst_gap<=2*err
                k=key+"/"+label+"/"+splitname
                rows[k]=dict(rows=len(ix),logits=int(reference.size),max_logit_error=err,top1_differences=mismatch,
                             largest_original_winner_gap_for_disagreement=worst_gap,max_mass_error=mass,
                             max_abs_relative_drift=drift,weights_sha256=stage["weight_sha"],original_scores_sha256=expected)
                print(k,len(ix),err,mismatch,flush=True)
    value=dict(terminal_sha256=sha(a.run/"terminal.json"),data_sha256=sha(a.data),scores=rows)
    a.out.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("run","data","out"):p.add_argument(name,type=Path)
    p.add_argument("--seed",type=int,required=True);p.add_argument("--limit",type=int);p.add_argument("--cdf-library",type=Path)
    main(p.parse_args())
