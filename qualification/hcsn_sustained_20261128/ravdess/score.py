"""Source-frozen external emotion scoring for original, analytic and sustained models."""
import argparse
import builtins
import fcntl
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import ModuleType
import time

import numpy as np
import torch
from torch.nn import functional as F

SEEDS=(137,311,557)


def digest(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
    with os.fdopen(descriptor,"rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError("nonregular input "+str(path))
        return hashlib.file_digest(f,"sha256").hexdigest()


def load(path):return json.loads(captured(path).decode("utf-8"))


def write(path,obj):
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,indent=2,allow_nan=False)+"\n");tmp.replace(path)


def captured(path,want=None):
    # Read one regular inode; source hardlinks and symlinks may still name it.
    descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
    with os.fdopen(descriptor,"rb") as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):raise ValueError("nonregular input "+str(path))
        raw=stream.read(before.st_size+1)
        after=os.fstat(stream.fileno())
    fields=("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")
    if len(raw)!=before.st_size or any(getattr(before,k)!=getattr(after,k) for k in fields):
        raise ValueError("input changed during read "+str(path))
    if want is not None and hashlib.sha256(raw).hexdigest()!=want:
        raise ValueError("input identity "+str(path))
    return raw


def source_modules(src,study,analytic):
    paths={"hcsn_temporal":src/"src/hcsn_temporal.py","encoder":src/"src/encoder.py",
           "torch_prices":analytic/"torch_prices.py","exact_law":analytic/"exact_law.py",
           "encoder_adapter":analytic/"encoder_adapter.py","study":study/"study.py"}
    payloads={name:captured(path) for name,path in paths.items()}
    modules={}
    for name in paths:
        module=ModuleType("_ravdess_"+name);module.__file__=str(paths[name])
        namespace=dict(vars(builtins));ordinary=namespace["__import__"]
        dependencies=dict(modules)
        def bound_import(name,globals=None,locals=None,fromlist=(),level=0,
                         dependencies=dependencies,ordinary=ordinary):
            if level==0 and name in dependencies:return dependencies[name]
            return ordinary(name,globals,locals,fromlist,level)
        namespace["__import__"]=bound_import;module.__dict__["__builtins__"]=namespace
        exec(compile(payloads[name],str(paths[name]),"exec",dont_inherit=True,optimize=0),module.__dict__)
        modules[name]=module
    pins={str(paths[name]):hashlib.sha256(raw).hexdigest() for name,raw in payloads.items()}
    return modules,pins


def current(pins):
    for path,want in pins.items():
        if digest(Path(path))!=want:raise ValueError("scoring context changed "+path)


def terminal_matches(result,context,out):
    if result.get("resume_context")!=context:raise ValueError("unbound or changed scoring context")
    models=context["models"]
    if (result.get("group")!=context["group"] or result.get("external_sha256")!=context["external_sha256"]
            or load(out/"source_models.json")!=models
            or result.get("source_selection_sha256")!=digest(out/"source_models.json")
            or set(result.get("models",{}))!=set(models)
            or result.get("controls_sha256")!=digest(out/"controls.npz")):
        raise ValueError("incomplete scoring terminal")
    for key,pin in models.items():
        row=result["models"][key]
        if (row.get("weight_sha256")!=pin["sha256"]
                or row.get("external_scores_sha256")!=digest(out/(key+".npz"))):
            raise ValueError("scoring output identity "+key)


def verified_state(path,want):
    return torch.load(BytesIO(captured(path,want)),weights_only=True,map_location="cpu")


def save_arrays(path,**arrays):
    buffer=BytesIO();np.savez_compressed(buffer,**arrays);raw=buffer.getvalue()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def losses(scores,y):
    return np.logaddexp.reduce(scores,axis=1)-scores[np.arange(len(y)),y]


def measure(z,y):
    ell=losses(z,y);correct=(z.argmax(1)==y)
    return dict(nll=float(ell.mean()),top1=float(correct.mean()),balanced_accuracy=float(np.mean([
        correct[y==i].mean() for i in range(6)]))),ell,correct


def features(v,a):
    tile=v.astype("float32").reshape(len(v),12,4,7,4,7).mean((3,5))/127.5-1
    v=tile.reshape(len(v),12,16)
    return np.concatenate([v.mean(1),v.std(1),a.mean(1),a.std(1)],axis=1).astype("float64")


def source_only_control(src,external):
    start=time.perf_counter()
    with np.load(src/"data/data.npz") as d:
        x=features(d["images"],d["audio"]);fold=d["split"];y=d["labels"]%6
    tr=fold==0;dev=fold==1
    mean=x[tr].mean(0);sd=x[tr].std(0).clip(1e-4)
    xx=(x-mean)/sd
    gram=xx[tr].T@xx[tr]
    prior=np.bincount(y[tr],minlength=6)/tr.sum()
    xty=xx[tr].T@(np.eye(6)[y[tr]]-prior)
    base=gram.trace()/len(gram)
    estimates=[]
    for alpha in (.0001,.01,1.):
        weight=np.linalg.solve(gram+np.eye(len(gram))*base*alpha,xty)
        for scale in (1.,4.,16.,64.):
            z=(xx[dev]@weight+prior)*scale
            estimates.append((float(losses(z,y[dev]).mean()),alpha,scale,weight))
    dev_nll,alpha,scale,w=min(estimates,key=lambda v:v[:3])
    frozen=dict(alpha=alpha,scale=scale,dev_nll=dev_nll,prior=prior.tolist(),
                weight_sha256=hashlib.sha256(w.tobytes()).hexdigest(),source_fit_s=time.perf_counter()-start)
    with np.load(external) as d:
        xnew=(features(d["video"],d["audio"])-mean)/sd
    return frozen,{"ridge":(xnew@w+prior)*scale,
                   "class_prior":np.broadcast_to(np.log(prior),(len(xnew),6)),
                   "uniform":np.zeros((len(xnew),6),dtype=float)}


def specifications(kind,study,analytic):
    if kind=="full":root=study/"whole_edit";filename="development_seal.json"
    elif kind=="analytic":root=analytic/"run";filename="seal.json"
    else:root=study/"run";filename="seal.json"
    raw=captured(root/filename);terminal=captured(root/"terminal.json")
    r=json.loads(raw)
    if hashlib.sha256(raw).hexdigest()!=json.loads(terminal)["seal_sha256"]:
        raise ValueError(kind+" seal")
    pins={str(root/filename):hashlib.sha256(raw).hexdigest(),
          str(root/"terminal.json"):hashlib.sha256(terminal).hexdigest()}
    if kind=="full":
        models=[]
        for arm in ("forward","same_site_bp","full_bp"):
            for seed in SEEDS:
                k=f"{arm}-{seed}";epoch=r["picks"][k]["raw"]
                row=next(v for v in r["fits"][k] if v["epoch"]==epoch)
                models.append((arm,"raw_dev_best",seed,root/k/row["weights"],row["sha256"]))
    elif kind=="analytic":
        models=[(grp["arm"],tag,grp["seed"],root/k/row["file"],row["sha256"])
                for k,grp in r.items() for tag,row in grp["history"].items()]
    else:
        models=[(arm,"raw_dev_best",seed,root/f"{arm}-{seed}"/r[f"{arm}-{seed}"]["best"]["file"],
                 r[f"{arm}-{seed}"]["best"]["sha256"])
                for arm in ("literal","smooth","lif","sdpa") for seed in SEEDS]
    return models,pins


@torch.no_grad()
def score(net,v,a,tokens):
    net.eval()
    prompts=net.encode(net.text(tokens))
    result=[]
    for ix in np.array_split(np.arange(len(v)),(len(v)+31)//32):
        embedding=net.encode(net.front(v[ix],a[ix]))
        result.append((12*(embedding@prompts.T)).numpy())
    z=np.concatenate(result)
    if z.shape!=(1056,72) or not np.isfinite(z).all():raise ValueError("external gallery")
    return z


def run(root,src,study,analytic,kind):
    out=root/("scores-"+kind);out.mkdir(exist_ok=True)
    with (out/"score.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        modules,pins=source_modules(src,study,analytic)
        hashes=modules["study"].HASHES
        for name,want in hashes.items():
            if Path(name).is_absolute() or ".." in Path(name).parts:raise ValueError("source input path")
            key=str(src/name)
            if key in pins and pins[key]!=want:raise ValueError("source "+name)
            pins[key]=want
        prepared=captured(root/"prepared.json")
        datafile=root/"external.npz";external_sha256=json.loads(prepared)["prepared_sha256"]
        specs,selection=specifications(kind,study,analytic)
        n={"full":9,"analytic":30,"sustained":12}[kind]
        models={f"{arm}-{tag}-{seed}":{"path":str(p),"sha256":want}
                for arm,tag,seed,p,want in specs}
        if len(specs)!=n or len(models)!=n:raise ValueError("incomplete weight set")
        enrolled=[*selection.items(),*((str(p),want) for _,_,_,p,want in specs),
                  (str(root/"prepared.json"),hashlib.sha256(prepared).hexdigest()),
                  (str(datafile),external_sha256),(str(Path(__file__).resolve()),digest(Path(__file__).resolve()))]
        for path,want in enrolled:
            if path in pins and pins[path]!=want:raise ValueError("conflicting input identity "+path)
            pins[path]=want
        if any(Path(key).name!=key or "\\" in key for key in models):
            raise ValueError("model output path")
        context=dict(schema="ravdess-score-context-v1",group=kind,files=pins,models=models,
                     external_sha256=external_sha256,
                     runtime=dict(python=sys.version,numpy=np.__version__,torch=str(torch.__version__)))
        current(pins)
        terminal=out/"terminal.json"
        if terminal.exists():
            terminal_matches(load(terminal),context,out)
            current(pins)
            return
        with tempfile.TemporaryDirectory(prefix="score-inputs-",dir=out) as temporary:
            frozen=Path(temporary);frozen_src=frozen/"source"
            for name,want in hashes.items():
                target=frozen_src/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(captured(src/name,want));target.chmod(0o400)
            frozen_external=frozen/"external.npz"
            frozen_external.write_bytes(captured(datafile,external_sha256));frozen_external.chmod(0o400)
            result=score_panel(out,frozen_src,frozen_external,kind,specs,context,modules)
        current(pins)
        terminal_matches(result,context,out)
        write(terminal,result)


def score_panel(out,src,datafile,kind,specs,context,modules):
    Data=modules["study"].Data
    AVText=modules["encoder"].AVText
    AnalyticAVText=modules["encoder_adapter"].AnalyticAVText
    d=Data(src)
    with np.load(src/"data/data.npz") as f:
        raw=f["audio"][d.train]
        mu=raw.mean((0,1),dtype=np.float64).astype(np.float32)
        sd=raw.std((0,1),dtype=np.float64).clip(.01).astype(np.float32)
    with np.load(datafile) as a:
        names=a["ids"];v=torch.from_numpy(a["video"]);au=torch.from_numpy((a["audio"]-mu)/sd);y=a["y"].astype(int)
    actors=np.array([int(k.split("-")[-1]) for k in names])
    if len(np.unique(actors))!=24 or len(y)!=1056 or np.bincount(y).tolist()!=[192,192,192,192,96,192]:
        raise ValueError("cohort counts")
    n=len(specs)
    write(out/"source_models.json",context["models"])
    fit,control=source_only_control(src,datafile)
    cm={k:measure(val,y)[0] for k,val in control.items()}
    controls_sha256=save_arrays(out/"controls.npz",ids=names,y=y,**control)
    st={};ell={};ok={}
    grouped={}
    for arm,tag,seed,p,want in specs:
        tic=time.perf_counter()
        model=(AnalyticAVText(96,seed,d.words,src/"src/law4.npz",learn_contract=arm=="learn",continuous=arm=="ramp")
               if kind=="analytic" and arm in ("exact","learn","ramp") else
               AVText(arm if arm in ("literal","smooth","lif","sdpa") else "literal",96,seed,d.words,src/"src/law4.npz"))
        model.load_state_dict(verified_state(p,want),strict=True)
        z=score(model,v,au,d.tokens)
        emission=np.logaddexp.reduce(z.astype(np.float64).reshape(len(y),12,6),axis=1)
        k=f"{arm}-{tag}-{seed}";grouped.setdefault((arm,tag),[]).append(k)
        m,ell[k],ok[k]=measure(emission,y)
        f=out/(k+".npz")
        score_sha256=save_arrays(f,ids=names,labels=y,source_gallery=z,emotion_logits=emission)
        st[k]=dict(metrics=m,weight_sha256=want,external_scores_sha256=score_sha256,elapsed_s=time.perf_counter()-tic)
        print(kind,k,round(m["nll"],5),round(m["balanced_accuracy"],4),flush=True)
    who,ix=np.unique(actors,return_inverse=True);draw=np.random.default_rng(413126).integers(0,len(who),(4000,len(who)))
    counts=np.bincount(ix)
    def ci(delta):
        sums=np.bincount(ix,weights=delta)
        return [float(delta.mean()),*np.quantile(sums[draw].sum(1)/counts[draw].sum(1),[.025,.975]).tolist()]
    means={};pairs={}
    for (arm,tag),keys in grouped.items():
        keys=sorted(keys)
        base=sorted(grouped["same_site_bp" if kind=="full" else "sdpa",tag])
        means[arm+"-"+tag]={k:float(np.mean([st[n]["metrics"][k] for n in keys])) for k in ("nll","top1","balanced_accuracy")}
        pairs[arm+"-"+tag]=dict(nll=ci(np.mean([ell[a]-ell[b] for a,b in zip(keys,base)],0)),
                                 top1=ci(np.mean([ok[a].astype(float)-ok[b] for a,b in zip(keys,base)],0)))
    result=dict(group=kind,external_sha256=context["external_sha256"],source_selection_sha256=digest(out/"source_models.json"),
          resume_context=context,controls_sha256=controls_sha256,
          actual_full_gallery_logits=n*1056*72,class_counts=np.bincount(y).tolist(),actor_count=len(who),
          means=means,models=st,against_reference= pairs,controls=cm,source_only_ridge=fit)
    print("computed",kind,means,flush=True)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("root","source","study","analytic"):p.add_argument(name,type=Path)
    p.add_argument("kind",choices=("full","analytic","sustained"));a=p.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    run(a.root,a.source,a.study,a.analytic,a.kind)
