"""Independent float64 forward of six financial population blocks, frontends, readout and prompt scoring."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
def ndtr(x):
    return .5*np.frompyfunc(math.erfc,1,1)(-x/math.sqrt(2)).astype(float)
import torch

SHA_DATA="18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad"
def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def linear(x,s,p):
    y=x@s[p+".weight"].T
    return y+s[p+".bias"] if p+".bias" in s else y

def layer_norm(x,s,p):
    centered=x-x.mean(axis=-1,keepdims=True)
    return centered/np.sqrt(np.mean(centered**2,axis=-1,keepdims=True)+1e-5)*s[p+".weight"]+s[p+".bias"]

def interp(table,raw_index):
    i=np.minimum(np.floor(raw_index).astype(int),len(table)-2)
    alpha=raw_index-i
    for _ in range(table.ndim-1):alpha=alpha[...,None]
    return (1-alpha)*table[i]+alpha*table[i+1]

def encode(x,s):
    b,t,d=x.shape;group=16;atoms=4
    previous_marks=None
    mass_error=0.
    for layer in range(6):
        normalized=layer_norm(x,s,f"n1.{layer}")
        p=f"mixer.{layer}."
        drive=linear(normalized,s,p+"drive")
        if previous_marks is not None:drive+=linear(previous_marks,s,p+"wire")
        value=linear(normalized,s,p+"value").reshape(b,t,group,-1)
        mass=np.broadcast_to(s["law.base.reset"],(b,group,atoms)).copy()
        refractory=np.zeros((b,group))
        mark=np.zeros((b,group))
        quote=np.zeros((b,group,2))
        memory=np.zeros((b,group,d//group))
        marks=[];features=[];contents=[]
        for ti in range(t):
            u=np.tanh(drive[:,ti]+linear(mark,s,p+"recurrent")+(np.tanh(quote)*s[p+"feedback"]).sum(-1))
            index=(u+1)*(len(s["law.mark"])-1)/2
            wall=interp(s["law.mark"],index)
            prices=interp(s["law.prices"],index)
            kernel=s["law.base.kernel"]
            shift_index=(np.clip(mark-wall,-.8,.8)+.8)*(len(kernel)-1)/1.6
            transition=interp(kernel,shift_index)
            moved=np.einsum("bgi,bgij->bgj",mass,transition)
            mass=moved[...,:atoms]+refractory[...,None]*s["law.base.reset"]
            refractory=moved[...,atoms]
            mass_error=max(mass_error,float(np.max(abs(mass.sum(-1)+refractory-1))))
            quote=np.einsum("bgj,bgjk->bgk",mass,prices)
            mark=wall
            memory=(1-refractory[...,None])*memory+refractory[...,None]*value[:,ti]
            marks.append(mark);features.append(np.stack((mark,refractory,mass.sum(-1),quote[...,0],quote[...,1]),-1));contents.append(memory)
        previous_marks=np.stack(marks,axis=1)
        x=x+linear(np.stack(contents,axis=1).reshape(b,t,d),s,p+"output")+linear(np.stack(features,axis=1).reshape(b,t,-1),s,p+"read")
        f=linear(layer_norm(x,s,f"n2.{layer}"),s,f"ff.{layer}.0")
        x=x+linear(f*ndtr(f),s,f"ff.{layer}.2")
    e=linear(layer_norm(x[:,-1],s,"out.0"),s,"out.1")
    return e/np.maximum(1e-12,np.linalg.norm(e,axis=1,keepdims=True)),mass_error

def main(run,data_path):
    assert sha(data_path)==SHA_DATA
    with np.load(data_path,allow_pickle=False) as d:
        train=np.flatnonzero(d["split"]==0);dev=np.flatnonzero(d["split"]==1)
        local_idx=np.linspace(0,len(dev)-1,num=12,dtype=int)
        ids=dev[local_idx];v=d["images"][ids].reshape(len(ids),12,-1).astype(float)/127.5-1
        a=d["audio"];mean=a[train].mean((0,1),dtype=np.float64).astype("float32")
        sd=a[train].std((0,1),dtype=np.float64).clip(.01).astype("float32")
        audio=((a[ids]-mean)/sd).astype(float);tokens=d["tokens"]
    results={}
    for arm in ("stationary","irreversible","returning"):
        folder=run/(arm+"-137")
        hist=json.loads((folder/"progress.json").read_bytes())["history"]
        row=hist["epoch1"];assert row["step"]==312
        weight=folder/row["file"];dev_file=folder/row["score_file"]
        assert sha(weight)==row["weight_sha"] and sha(dev_file)==row["score_sha"]
        s={k:t.detach().numpy().astype(float) for k,t in torch.load(weight,map_location="cpu",weights_only=True).items()}
        av=linear(v,s,"face")+linear(audio,s,"sound")+s["position"]+s["type_code"][0]
        words=s["word.weight"][tokens]+s["position"]+s["type_code"][1]
        emb,ma=encode(av,s);text,mt=encode(words,s);score=12*emb@text.T
        with np.load(dev_file) as f:ref=f["logits"][local_idx].astype(float)
        maxerr=float(abs(ref-score).max())
        assert maxerr<2e-4 and np.array_equal(score.argmax(1),ref.argmax(1)) and max(ma,mt)<3e-6
        results[arm]=dict(weight_sha256=row["weight_sha"],development_archive_sha256=row["score_sha"],scores=int(ref.size),
                          max_absolute_logit_difference=maxerr,max_total_mass_discrepancy=max(ma,mt),exact_top1_agreement=True)
    return {"seed":137,"endpoint":"epoch1","held_predictions":0,"data_sha256":SHA_DATA,
            "development_row_indices":local_idx.tolist(),"results":results,
            "method":"NumPy float64 builds all frontends, timestep and layer recurrences, stochastic mass transitions, financial interpolation, GELU feedforward and normalized prompt scores from checkpoint tensors. PyTorch only deserializes weights."}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("run",type=Path);p.add_argument("data_npz",type=Path)
    a=p.parse_args();print(json.dumps(main(a.run,a.data_npz),indent=2))
