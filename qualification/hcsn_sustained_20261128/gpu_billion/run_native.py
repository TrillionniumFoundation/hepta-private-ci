"""On-device billion-parameter direct writing and matched-site BP on exact CREMA-D clips."""
import argparse
import contextlib
import gc
import hashlib
import io
import json
import lzma
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F


def sha(data):
    return hashlib.sha256(data).hexdigest()


def synchronized():
    torch.cuda.synchronize()
    return time.perf_counter()


def amp():
    return torch.autocast("cuda",dtype=torch.float16,cache_enabled=False)


def sites(net):
    return {**{f"read{i}":m.read.weight for i,m in enumerate(net.mixer)},"projection":net.out[1].weight}


def hashes(weights):
    return {k:sha(t.detach().float().contiguous().cpu().numpy().tobytes()) for k,t in weights.items()}


def load_inputs(folder):
    data=(folder/"subset.xz").read_bytes()
    meta=json.loads((folder/"subset.json").read_text())
    if sha(data)!=meta["packed_sha256"]:
        raise ValueError("compressed input identity")
    with np.load(io.BytesIO(lzma.decompress(data))) as a:
        v={k:a[k] for k in meta["values_sha256"]}
        fields={k:a["law_"+k] for k in meta["law_sha256"]}
        restored=np.ascontiguousarray(a["third_differences"].T)
        for _ in range(3):
            restored=np.cumsum(restored,axis=0,dtype=np.uint32)
        kernel=restored.view(np.float32).reshape(4097,4,5)
    for k,item in v.items():
        if sha(item.tobytes())!=meta["values_sha256"][k]:
            raise ValueError("sample identity "+k)
    for k,item in fields.items():
        if sha(item.tobytes())!=meta["law_sha256"][k]:
            raise ValueError("price array "+k)
    if sha(kernel.tobytes())!=meta["kernel_sha256"]:
        raise ValueError("transport kernel identity")
    np.savez(folder/"law4.npz",**fields,kernel=kernel)
    return v,meta


def ridge(x,y):
    x=x.double()
    y=y.double()
    penalty=max(1e-9,.01*float(x.square().sum())/x.size(1))
    gram=x@x.T
    gram.diagonal().add_(penalty)
    return (x.T@torch.linalg.solve(gram,y)).T.float()


@torch.no_grad()
def direct(net,inputs,shuffle):
    v,a,y,tokens=inputs
    gen=torch.Generator().manual_seed(137+71439)
    proto=F.normalize(torch.randn(6,72,4096,generator=gen),dim=-1).cuda()*4096**.5
    target=F.normalize(torch.randn(72,256,generator=gen),dim=-1).cuda()
    hidden_y=y[torch.randperm(len(y),generator=gen,device="cpu").cuda()] if shuffle else y
    hidden_y=hidden_y.repeat(2)
    with amp():
        h=torch.cat((net.front(v,a),net.text(tokens[y]))).float()
    lower=None
    for m,n1,ff,n2,classes in zip(net.mixer,net.n1,net.ff,net.n2,proto):
        features=[]
        hook=m.read.register_forward_pre_hook(lambda _,args:features.append(args[0][:,-1].float().clone()))
        try:
            with amp():
                out,_,_=m(n1(h),lower,net.law)
        finally:
            hook.remove()
        last=(h+out)[:,-1]
        delta=ridge(features[0],classes[hidden_y]*last.square().mean().sqrt()-last)
        m.read.weight.add_(delta,alpha=.5)
        with amp():
            update,lower,_=m(n1(h),lower,net.law)
            h=h+update
            h=(h+ff(n2(h))).float()
    net.out[1].weight.copy_(ridge(net.out[0](h[:,-1]),target[y.repeat(2)]))


def bp(net,inputs,pair_loss):
    v,a,y,tokens=inputs
    params=list(sites(net).values())
    for w in params:w.requires_grad_(True)
    opt=torch.optim.AdamW(params,lr=.0001,weight_decay=.01,foreach=False)
    opt.zero_grad(set_to_none=True)
    with amp():
        av,txt=net(v,a,tokens[y])
    loss=pair_loss(av.float(),txt.float(),y)
    loss.backward()
    grad=float(torch.nn.utils.clip_grad_norm_(params,1.,error_if_nonfinite=True))
    opt.step()
    net.requires_grad_(False)
    for w in params:w.grad=None
    return {"contrastive_loss":float(loss.detach()),"grad_norm":grad}


@torch.no_grad()
def score(net,v,a,t,y):
    with amp():
        txt=torch.cat([net.encode(net.text(part)) for part in t.split(8)])
        av=net.encode(net.front(v,a))
    z=(12*(av.float()@txt.float().T)).cpu()
    if z.shape!=(2,72) or not torch.isfinite(z).all():
        raise ValueError("incomplete or nonfinite scores")
    return dict(scores=z.numpy().tolist(),nll=float(F.cross_entropy(z,y.cpu())),
                correct=int((z.argmax(1)==y.cpu()).sum()))


def run(folder,out):
    started=time.perf_counter()
    if not torch.cuda.is_available():
        raise RuntimeError("native CUDA allocation required")
    device=torch.cuda.get_device_name()
    if "T4" not in device:
        raise RuntimeError("requested T4, received "+device)
    probe=float(torch.arange(8,device="cuda",dtype=torch.float32).square().sum())
    if probe!=140:
        raise ValueError("CUDA arithmetic")
    arr,meta=load_inputs(folder)
    assert arr["fold"].tolist()==[0]*16+[1,1,2,2]
    sys.path.insert(0,str(folder))
    from encoder import AVText,pair_loss
    net=AVText("literal",4096,137,int(arr["tokens"].max())+1,folder/"law4.npz").to("cuda").eval()
    net.requires_grad_(False)
    full=sum(p.numel() for p in net.parameters())
    selected=sites(net)
    writable=sum(p.numel() for p in selected.values())
    if full!=1016475200 or writable!=4980736:raise ValueError("unexpected model size")
    base={k:p.detach().clone() for k,p in selected.items()}
    parent=hashes(base)
    v,a,y,t=[torch.from_numpy(arr[k]).cuda() for k in ("v","audio","y","tokens")]
    inputs=v[:16],a[:16],y[:16],t
    prep=synchronized()-started
    rows={}
    for arm in ("keep","forward","shuffled","bp"):
        net.requires_grad_(False)
        with torch.no_grad():
            for k,p in selected.items():p.copy_(base[k])
        if hashes(selected)!=parent:raise ValueError("parent reconstruction")
        torch.cuda.reset_peak_memory_stats()
        t0=synchronized()
        extra={}
        if arm=="bp":extra=bp(net,inputs,pair_loss)
        elif arm!="keep":direct(net,inputs,arm=="shuffled")
        fit=synchronized()-t0
        max_alloc=torch.cuda.max_memory_allocated()
        changed={k:int((p!=base[k]).count_nonzero()) for k,p in selected.items()}
        if (arm=="keep" and sum(changed.values())) or (arm!="keep" and min(changed.values())==0):
            raise ValueError("unexpected effective write count")
        patch={k:p.detach().cpu().clone() for k,p in selected.items()}
        patchfile=folder/(arm+".pt")
        torch.save(patch,patchfile)
        content_hashes=hashes(patch)
        dev=score(net,v[16:18],a[16:18],t,y[16:18])
        rows[arm]=dict(fit_s=fit,fit_save_dev_s=synchronized()-t0,peak_fit_allocated_bytes=max_alloc,
                       changed=changed,weight_array_sha256=content_hashes,weights_file_sha256=sha(patchfile.read_bytes()),dev=dev,**extra)
        del patch
        print(arm,"development",round(fit,4),flush=True)
    seal=folder/"frozen.json"
    seal.write_text(json.dumps(rows,sort_keys=True,allow_nan=False))
    cold={}
    for arm,rec in rows.items():
        p=folder/(arm+".pt")
        if sha(p.read_bytes())!=rec["weights_file_sha256"]:raise ValueError("changed patch")
        w=torch.load(p,map_location="cpu",weights_only=True)
        if hashes(w)!=rec["weight_array_sha256"]:raise ValueError("changed matrices")
        with torch.no_grad():
            for k,param in selected.items():param.copy_(w[k])
        tic=synchronized()
        cold[arm]=score(net,v[18:20],a[18:20],t,y[18:20])
        cold[arm]["cold_s"]=synchronized()-tic
    report=dict(device=device,torch=str(torch.__version__),cuda=torch.version.cuda,cuda_probe=probe,
                source_subset_sha256=meta["packed_sha256"],source_law_sha256=meta["source_table_sha256"],
                ids=arr["ids"].tolist(),labels=y.cpu().tolist(),full_parameters=full,writable_parameters=writable,
                preparation_s=prep,total_s=synchronized()-started,parent_hashes=parent,
                development_seal_sha256=sha(seal.read_bytes()),development=rows,cold=cold)
    out.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("folder",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    run(a.folder.resolve(),a.output.resolve())
