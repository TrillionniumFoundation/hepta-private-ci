#!/usr/bin/env python3
"""Research E5: sparse Packed Head SGD with safe, scoped, two-wave persistence.

Frozen *synthetic* starting Heads (not pretrained Stem weights), a 50%-overlap
active set, and cumulative sparse per-Cell momentum are stored in immutable
safetensors. Offline consistency != signed Worker/CAS/WAL/FinalUse qualification.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path
import torch
import torch.nn.functional as F
from safetensors.torch import save, load
from e5_sparse_packed_sgd import packed_bank, selected_indices, SHAPES, PER_HEAD
from e5_packed_head_fanout import packed_forward

SCHEMA="hepta.e5.continual-cell-delta-shadow.v1"
MAX_BYTES=128*1024*1024
class Invalid(ValueError):pass

def digest(data):return hashlib.sha256(data).hexdigest()
def sha(v,zero=False):
    if type(v) is not str or len(v)!=64 or (not zero and v=="0"*64) or any(c not in "0123456789abcdef" for c in v):
        raise Invalid("invalid 64-hex digest")
    return v
def stable(v):
    if type(v) is not str or not 1<=len(v)<=128 or any(not(c.isascii() and (c.isalnum() or c in "._:-")) for c in v):
        raise Invalid("invalid stable identity")
    return v
def pairs(entries):
    obj={}
    for k,v in entries:
        if k in obj:raise Invalid("duplicate JSON field")
        obj[k]=v
    return obj
def read(path):
    raw=Path(path).read_bytes()
    if not 4<len(raw)<=32768:raise Invalid("incomplete receipt")
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid("nonfinite JSON")))
def config(cells,active,seed,scope,fence,source):
    if cells not in (64,256,1024,4096) or type(active) is not int or not 2<=active<=cells//2 or type(seed) is not int or seed<0:raise Invalid("bad physical Cell cohort")
    stable(scope);sha(fence);sha(source)
    return dict(cells=cells,active=active,seed=seed,scope=scope,fence=fence,source=source)
def schedule(config,wave):
    cells,active,seed=(config[k] for k in ("cells","active","seed"))
    initial=selected_indices(torch,cells,active,seed)
    if wave==1:return initial
    if wave!=2:raise Invalid("unsupported wave")
    prior=initial[::2][:active//2]
    unused=torch.ones(cells,dtype=torch.bool);unused[initial]=False
    unused_ids=torch.arange(cells)[unused]
    gen=torch.Generator().manual_seed(seed+94719)
    new=unused_ids[torch.randperm(len(unused_ids),generator=gen)[:active-len(prior)]]
    return torch.cat((prior,new)).sort()[0]
def fresh(c):
    return dict(weights=packed_bank(torch,c["cells"],c["seed"]),
                momentum={},steps=torch.zeros(c["cells"],dtype=torch.int64),generation=0)
def state_hash(state):
    h=hashlib.sha256(b"hepta.e5.all-weights-and-per-cell-momentum.v1")
    for name,values in sorted(state["weights"].items()):
        h.update(name.encode()+b"\0");h.update(values.detach().contiguous().numpy().tobytes())
    for idx in sorted(state["momentum"]):
        h.update(idx.to_bytes(8,"little"))
        for name,m in sorted(state["momentum"][idx].items()):
            h.update(name.encode()+b"\0");h.update(m.detach().contiguous().numpy().tobytes())
    h.update(state["steps"].numpy().tobytes())
    return h.hexdigest()
def wave(state,c,phase):
    if state["generation"]!=phase-1:raise Invalid("nonmonotone SGD wave")
    indices=schedule(c,phase);ids=indices.tolist();before=state["steps"].clone()
    tensors={k:torch.nn.Parameter(v.index_select(0,indices).detach().clone()) for k,v in state["weights"].items()}
    opt=torch.optim.SGD(tensors.values(),lr=0.01,momentum=0.9)
    for name,param in tensors.items():
        opt.state[param]["momentum_buffer"]=torch.stack([
            state["momentum"][idx][name] if idx in state["momentum"] else torch.zeros_like(state["weights"][name][idx])
            for idx in ids]).clone()
    feature=(torch.round(torch.linspace(-1,1,384)*(1<<24))/(1<<24)).reshape(1,-1).expand(c["active"],-1)
    local=((indices.float()%23-11).reshape(-1,1).expand(-1,64))/20+(phase-1)*0.1
    labels=(indices*7+3+phase-1)%8
    losses=[];tick=time.perf_counter_ns()
    for _ in range(3):
        opt.zero_grad(set_to_none=True)
        logits=packed_forward(torch,tensors,feature,local)
        loss=F.cross_entropy(logits,labels,reduction="sum")
        if not bool(torch.isfinite(loss)):raise Invalid("nonfinite SGD loss")
        losses.append(float(loss.detach()));loss.backward()
        if any(v.grad is None or not bool(torch.isfinite(v.grad).all()) for v in tensors.values()):raise Invalid("gradient failure")
        opt.step()
    train_ms=(time.perf_counter_ns()-tick)/1e6
    with torch.no_grad():
        for name,param in tensors.items():state["weights"][name].index_copy_(0,indices,param.detach())
        for j,idx in enumerate(ids):
            state["momentum"][idx]={name:opt.state[param]["momentum_buffer"][j].detach().clone() for name,param in tensors.items()}
        state["steps"].index_add_(0,indices,torch.full_like(indices,3))
    dormant=torch.ones(c["cells"],dtype=torch.bool);dormant[indices]=False
    if not torch.equal(before[dormant],state["steps"][dormant]) or feature.requires_grad or local.requires_grad:
        raise Invalid("dormant state or shared-feature gradient escaped")
    state["generation"]=phase
    return dict(generation=phase,active=c["active"],repeated_active=len(set(ids)&set(schedule(c,1).tolist())),
                learned_cell_count=len(state["momentum"]),cumulative_steps=int(state["steps"].sum()),
                losses=losses,sgd_wall_ms=train_ms,bank_sha256=state_hash(state))
def freeze(state,c):
    touched=sorted(state["momentum"])
    index=torch.tensor(touched,dtype=torch.int64)
    tensor={"idx":index,"steps":state["steps"].index_select(0,index)}
    for name,shape in SHAPES.items():
        tensor["w."+name]=state["weights"][name].index_select(0,index).contiguous()
        tensor["m."+name]=torch.stack([state["momentum"][i][name] for i in touched]).contiguous()
    raw=save(tensor,metadata={"schema":SCHEMA,"authority":"DENY_ALL"})
    if not 8<len(raw)<=MAX_BYTES:raise Invalid("sparse snapshot budget")
    return raw
def save_checkpoint(root,name,state,c,parent="0"*64,failpoint=False):
    root=Path(root);stable(name);sha(parent,zero=True)
    if not root.is_dir() or root.is_symlink():raise Invalid("unsafe evidence root")
    binary=root/(name+".safetensors");receipt=root/(name+".receipt.json")
    if binary.exists() or receipt.exists() or binary.is_symlink() or receipt.is_symlink():raise FileExistsError("snapshot immutable")
    data=freeze(state,c)
    note=dict(schema=SCHEMA,authority="DENY_ALL",production_promotion_permitted=False,
              native_worker_or_ndu_verified=False,config=c,generation=state["generation"],
              previous_sha256=parent,body_sha256=digest(data),body_bytes=len(data),
              touched_cells=len(state["momentum"]),weights_sha256=state_hash(state))
    _new_file(binary,data)
    if failpoint:raise RuntimeError("fault after body before receipt")
    _new_file(receipt,(json.dumps(note,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode())
    fd=os.open(str(root),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return note
def _new_file(path,data):
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        blob=memoryview(data)
        for i in range(0,len(blob),1<<20):
            part=blob[i:i+(1<<20)]
            while part:
                n=os.write(fd,part)
                if n<=0:raise OSError("short snapshot write")
                part=part[n:]
        os.fsync(fd)
    finally:os.close(fd)
def restore(root,name,c,generation,parent=None):
    root=Path(root);stable(name)
    file=root/(name+".safetensors");note=root/(name+".receipt.json")
    if root.is_symlink() or file.is_symlink() or note.is_symlink() or not file.is_file() or not note.is_file():raise Invalid("missing committed snapshot")
    receipt=read(note)
    if (receipt.get("schema")!=SCHEMA or receipt.get("authority")!="DENY_ALL" or
        receipt.get("production_promotion_permitted") is not False or
        receipt.get("native_worker_or_ndu_verified") is not False or
        receipt.get("config")!=c or receipt.get("generation")!=generation or
        generation not in (1,2) or (parent is not None and receipt.get("previous_sha256")!=sha(parent,zero=True))):
        raise Invalid("scope, fence, generation or parent drift")
    if not 8<file.stat().st_size<=MAX_BYTES or file.stat().st_size!=receipt.get("body_bytes"):raise Invalid("unsafe snapshot size")
    content=file.read_bytes()
    if digest(content)!=sha(receipt.get("body_sha256")):raise Invalid("snapshot byte tampering")
    try:blob=load(content)
    except Exception as exc:raise Invalid("unsafe safetensors payload") from exc
    expected={"idx","steps"}|{"w."+k for k in SHAPES}|{"m."+k for k in SHAPES}
    if set(blob)!=expected:raise Invalid("invalid tensor inventory")
    indices=blob["idx"];steps=blob["steps"]
    if indices.ndim!=1 or indices.dtype!=torch.int64 or steps.shape!=indices.shape or steps.dtype!=torch.int64:raise Invalid("optimizer index shape")
    ids=indices.tolist()
    if ids!=sorted(set(ids)) or any(not 0<=i<c["cells"] for i in ids) or not bool(torch.all(steps>0)) or not bool(torch.all(steps%3==0)) or len(ids)!=receipt["touched_cells"]:raise Invalid("optimizer history changed")
    state=fresh(c)
    state["generation"]=generation;state["steps"].index_copy_(0,indices,steps)
    for name,shape in SHAPES.items():
        weights=blob["w."+name];mom=blob["m."+name]
        if (weights.shape!=(len(ids),*shape) or mom.shape!=weights.shape or
            weights.dtype!=torch.float32 or mom.dtype!=torch.float32 or
            not bool(torch.isfinite(weights).all()) or not bool(torch.isfinite(mom).all())):raise Invalid("wrong/nonfinite Cell tensors")
        with torch.no_grad():state["weights"][name].index_copy_(0,indices,weights)
        for j,idx in enumerate(ids):state["momentum"].setdefault(idx,{})[name]=mom[j].clone()
    if {i for i,s in enumerate(state["steps"].tolist()) if s>0}!=set(ids) or state_hash(state)!=receipt["weights_sha256"]:
        raise Invalid("Cell weights/steps/momentum don't reconstruct")
    return state,receipt
def execute(c,root,action):
    torch.set_num_threads(1)
    began=time.perf_counter_ns()
    if action=="first":
        state=fresh(c);measurement=wave(state,c,1)
        receipt=save_checkpoint(root,"wave1",state,c)
    elif action=="second":
        state,parent=restore(root,"wave1",c,1,"0"*64)
        measurement=wave(state,c,2)
        receipt=save_checkpoint(root,"wave2",state,c,parent["body_sha256"])
    elif action=="reference":
        state=fresh(c);wave(state,c,1);measurement=wave(state,c,2);receipt=None
    elif action=="verify":
        _,parent=restore(root,"wave1",c,1,"0"*64)
        state,receipt=restore(root,"wave2",c,2,parent["body_sha256"])
        original=fresh(c);wave(original,c,1);measured=wave(original,c,2)
        if state_hash(state)!=state_hash(original):raise Invalid("cold restart diverged")
        measurement={"cold_restart_equals_uninterrupted":True,"source_waves":2,
                     "complete_head_parameters":c["cells"]*PER_HEAD,
                     "sparse_checkpoint_bytes":receipt["body_bytes"],
                     "updated_cells":len(state["momentum"]),
                     "reference_losses":measured["losses"]}
    else:raise Invalid("unsupported experiment step")
    return dict(schema=SCHEMA+".report",mode=action,authority="DENY_ALL",
                production_promotion_permitted=False,synthetic_feature_and_labels=True,
                pretrained_encoder_or_native_worker_verified=False,
                actual_sparse_sgd_execution=True,config=c,measurement=measurement,
                checkpoint=receipt,process_wall_ms=(time.perf_counter_ns()-began)/1e6)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--action",required=True,choices=("first","second","reference","verify"))
    p.add_argument("--cells",required=True,type=int)
    p.add_argument("--active",required=True,type=int)
    p.add_argument("--seed",type=int,default=20261014)
    p.add_argument("--scope",default="research.neuron-cell")
    p.add_argument("--fence",default="a"*64)
    p.add_argument("--source",default="b"*64)
    p.add_argument("--directory",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError("write-once output")
    c=config(a.cells,a.active,a.seed,a.scope,a.fence,a.source)
    report=execute(c,a.directory,a.action)
    with a.output.open("x",encoding="utf8") as file:json.dump(report,file,sort_keys=True,indent=2,allow_nan=False);file.write("\n")
if __name__=="__main__":main()
