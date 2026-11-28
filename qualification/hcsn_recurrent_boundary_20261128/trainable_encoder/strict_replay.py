"""Verify frozen sources and re-run the pretrained 15-cell HCSN panel without changing original observations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime,timezone

import numpy as np
import torch

ARMS=("stationary","irreversible","returning","lif","sdpa")
SEEDS=(137,311,557)
RUNGS=(120.,900.,2600.)
LABELS={"epoch1","time120","time900","time2600"}
GATES=("4.1","3.6","3.0")
MODEL_SOURCE={"train.py":"189783642d5fbecf7ba22e486b2363994fcadadd45aaddf2e8d65387df765d48",
              "network.py":"8b1b7108444bddabf0b34dde45524fd689e69373a2d601209657e6e918160be8",
              "study.py":"69e8cf12bcfcd414175250405ac08286901457377d76c1ad28f08d33a775dbc1"}
INPUTS={"src/encoder.py":"1c5ee669c47adaca3bec2ae3def64aec117596c8628345beb300e143628824df",
        "src/hcsn_temporal.py":"1c5ee332f549e3d9ffbff21bfeeef0e181d34e0606e5c27b38bcc66a48ae5eec",
        "src/law4.npz":"de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4",
        "data/data.npz":"18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad"}
TABLES={"stationary":"2aef78714f394379c8eea53abb387d34dc08341504289d89b64b15a8848cff1c",
        "irreversible":"f9c114c2940ecb821bdcbf28c5e0eecaa78eabfc2651e3018b545652b430cf66",
        "returning":"b276da1df27b4c4811910f6bc597e7326f442f3695031cccb998c19a30b08717"}
TABLE_MANIFEST="285a752ef2515ec0c08a998a6d696d188c36ed7c6d0f2bd0ce846559467b3842"

def check(condition,message):
    if not condition:raise ValueError(message)

def sha(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

class Evidence:
    def __init__(self,out):
        self.out=out
        self.objects=out/"objects"
        self.objects.mkdir(parents=True,exist_ok=True)
        self.files={}
    def preserve(self,name,source,expected=None):
        digest=sha(source)
        check(expected is None or digest==expected,"changed "+name)
        dest=self.objects/digest
        if not dest.exists():
            with tempfile.NamedTemporaryFile(dir=self.objects,delete=False) as t:
                temp=Path(t.name)
                with source.open("rb") as f:shutil.copyfileobj(f,t)
            try:
                check(sha(temp)==digest,"source changed during capture "+name)
                try:os.link(temp,dest)
                except FileExistsError:pass
            finally:temp.unlink(missing_ok=True)
        check(sha(dest)==digest,"stored payload digest mismatch")
        check(name not in self.files or self.files[name]==digest,"conflicting logical name "+name)
        self.files[name]=digest
        return dest
    def array(self,name,x):
        with tempfile.NamedTemporaryFile(dir=self.out) as f:
            np.save(f,x,allow_pickle=False);f.flush()
            return self.preserve(name,Path(f.name))

def read(p):return json.loads(p.read_bytes())

def quality(x,y):
    f=x.astype(np.float64)
    return np.stack((np.logaddexp.reduce(f,axis=1)-f[np.arange(len(y)),y],(f.argmax(1)==y).astype(float)))

def check_metrics(values,claimed):
    measured=values.mean(axis=1)
    numbers=np.asarray([claimed["nll"],claimed["top1"]])
    check(np.isfinite(numbers).all() and max(abs(numbers-measured))<3e-5,"metrics disagree with original scores")

def independent_inference(net,data,ids):
    # Keep the same chunk sizes to support bitwise FP32 reproducibility. The study.inference function is not called.
    net.eval()
    with torch.no_grad():
        prompt=net.encode(net.text(data.tokens))
        batches=np.array_split(ids,(len(ids)+31)//32)
        return torch.cat([12*(net.encode(net.front(data.v[r],data.audio[r]))@prompt.T) for r in batches]).cpu().numpy()

def replay(a):
    check(a.atol>=0 and a.rtol>=0 and np.isfinite([a.atol,a.rtol]).all(),"invalid tolerances")
    ev=Evidence(a.archive)
    for name,d in MODEL_SOURCE.items():ev.preserve(f"source/{name}", a.parent_study if name=="study.py" else a.code/name,d)
    for name,d in INPUTS.items():ev.preserve("inputs/"+name,a.data_root/name,d)
    table_path=ev.preserve("source/tables/tables.json",a.code/"tables/tables.json",TABLE_MANIFEST)
    tables=read(table_path)
    check(set(tables)==set(TABLES),"pricing candidates")
    for k,h in TABLES.items():
        file=k+".npz"
        check(tables[k]["sha256"]==h and tables[k]["file"]==file,"table metadata")
        ev.preserve("source/tables/"+file,a.code/"tables"/file,h)
    recipe=read(ev.preserve("original/recipe.json",a.run/"recipe.json"))
    check(recipe=={"sources":MODEL_SOURCE,"inputs":INPUTS,"tables":tables,"arms":list(ARMS),"seeds":list(SEEDS),
                   "rungs":list(RUNGS),"torch":recipe["torch"]},"unregistered run recipe")
    if str(torch.__version__)!=recipe["torch"]:
        check(a.atol>0 or a.rtol>0,"cross-version verification requires explicit numeric tolerances")
    # Only previously hashed and captured source files may supply the data, encoder and pricing model.
    sys.path[:0]=[str(a.code.resolve()),str((a.data_root/"src").resolve()),str(a.parent_study.parent.resolve())]
    import network,study,encoder,hcsn_temporal
    for mod,d in ((network,MODEL_SOURCE["network.py"]),(study,MODEL_SOURCE["study.py"]),
                  (encoder,INPUTS["src/encoder.py"]),(hcsn_temporal,INPUTS["src/hcsn_temporal.py"])):
        check(sha(Path(mod.__file__))==d,"unexpected imported code "+mod.__name__)
    torch.set_num_threads(1)
    data=study.Data(a.data_root)
    check(len(data.train)==4984 and len(data.dev)==1147 and len(data.test)==1311 and len(data.tokens)==72,"data dimensions")
    full=not a.development_only
    records={}; observations={}; summary={}; detail={}
    cells=[(arm,s,f"{arm}-{s}") for arm in ARMS for s in SEEDS]
    if full:
        term=read(ev.preserve("original/terminal.json",a.run/"terminal.json"))
        panel=read(ev.preserve("original/seal.json",a.run/"seal.json",term["seal_sha"]))
        exp={k for _,_,k in cells}
        check(set(panel)==set(term["panels"])==exp,"incomplete frozen panel")
        ident=ev.preserve("original/held-identities.npz",a.run/"held-identities.npz",term["identities_sha"])
        with np.load(ident,allow_pickle=False) as ids:
            for key,val in (("actors",data.actors[data.test]),("labels",data.y[data.test].numpy()),("ids",data.names[data.test])):
                check(np.array_equal(ids[key],val),"held identity mismatch "+key)
    def score_array(net,rows,p,expected,name,claimed):
        orig=ev.preserve("original/"+name,p,expected)
        with np.load(orig,allow_pickle=False) as archive:
            check(archive.files==["logits"],"unexpected score fields "+name)
            z=archive["logits"]
        check(z.dtype==np.float32 and z.shape==(len(rows),72) and np.isfinite(z).all(),"invalid stored array "+name)
        new=independent_inference(net,data,rows)
        check(z.shape==new.shape and z.dtype==new.dtype and np.isfinite(new).all(),"invalid replay "+name)
        maxerr=float(np.max(abs(new-z)))
        check(np.allclose(new,z,atol=a.atol,rtol=a.rtol),"logit discrepancy "+name+" maximum "+str(maxerr))
        exact=new.tobytes()==z.tobytes()
        if a.atol==a.rtol==0:check(exact,"floating point bit patterns differ "+name)
        ev.array("replay/"+name+".npy",new)
        scores=quality(z,data.y[rows].numpy())
        check_metrics(scores,claimed)
        observations[name]={"original_logit_sha256":hashlib.sha256(z.tobytes()).hexdigest(),
                            "replayed_logit_sha256":hashlib.sha256(new.tobytes()).hexdigest(),
                            "bitwise_equal":exact,"max_abs_error":maxerr,"score_count":int(z.size)}
        return scores
    for arm,seed,key in cells:
        cell=a.run/key
        if full:
            choice=panel[key];hist=choice["history"];actual=term["panels"][key]
            check(set(hist)==LABELS,"missing epoch or clock "+key)
        else:
            p=cell/"progress.json"
            if not p.exists():continue
            prog=read(ev.preserve("original/"+key+"/progress.json",p))
            check(prog["arm"]==arm and prog["seed"]==seed,"progress identity")
            hist=prog["history"]
            check(set(hist)<=LABELS,"unexpected checkpoint label")
            if not hist:continue
        net=network.make_model(a.data_root,a.code,arm,seed,data)
        seen={}; labels_sorted=sorted(hist,key=lambda k:hist[k]["step"])
        for lab in labels_sorted:
            r=hist[lab];st=r["step"]
            check(type(st) is int and st>0,"invalid step")
            check(r["samples"]==(st//312)*4984+min(16*(st%312),4984),"sample prefix "+key)
            if lab=="epoch1":check(st==312,"incorrect epoch number")
            else:check(np.isfinite(r["active"]) and r["active"]>=int(lab[4:]),"clock not reached")
            check(r["file"]==f"step{st}.pt" and r["score_file"]==f"step{st}-dev.npz","noncanonical checkpoint")
            if st in seen:check(r==seen[st],"step has conflicting identities");continue
            seen[st]=r
            weight=ev.preserve(f"original/{key}/"+r["file"],cell/r["file"],r["weight_sha"])
            net.load_state_dict(torch.load(weight,map_location="cpu",weights_only=True),strict=True)
            # Pricing and transport buffers are frozen by the registered construction.
            if arm in TABLES:
                fresh=network.make_model(a.data_root,a.code,arm,seed,data)
                for bk,v in net.law.state_dict().items():
                    check(torch.equal(v,fresh.law.state_dict()[bk]),"registered financial buffer changed "+bk)
            score_array(net,data.dev,cell/r["score_file"],r["score_sha"],key+"/"+r["score_file"],r["development"])
            if full:
                h=actual[str(st)];name=f"step{st}-held.npz"
                check(h["file"]==name,"noncanonical cold record")
                scores=score_array(net,data.test,cell/name,h["sha"],key+"/"+name,h["quality"])
                for same,row in hist.items():
                    if row["step"]==st:summary[key,same]=scores
        if not full:continue
        check(set(actual)=={str(s) for s in seen}|({"no_wire"} if arm=="returning" else set()),"cold coverage "+key)
        check(set(choice["gates"])==set(GATES),"missing registered gate "+key)
        best=min(labels_sorted,key=lambda lab:hist[lab]["development"]["nll"])
        check(choice["best"]==best,"best candidate "+key)
        summary[key,"best"]=summary[key,best]
        detail[key]={}
        for g in GATES:
            pick=next((l for l in labels_sorted if hist[l]["development"]["nll"]<=float(g)),None)
            check(choice["gates"][g]==pick,"gate selection "+key)
            detail[key][g]={"first_development":pick,"paired_held_pass":bool(pick and summary[key,pick][0].mean()<=float(g))}
        if arm=="returning":
            selected=hist[best]
            path=ev.objects/ev.files[f"original/{key}/"+selected["file"]]
            net.load_state_dict(torch.load(path,map_location="cpu",weights_only=True),strict=True)
            with torch.no_grad():
                for mixer in list(net.mixer)[1:]:mixer.wire.weight.zero_()
            h=actual["no_wire"];name=f"step{selected['step']}-held-nowire.npz"
            check(h["file"]==name,"no-wire checkpoint identity")
            summary[key,"no_wire"]=score_array(net,data.test,cell/name,h["sha"],key+"/"+name,h["quality"])
    check(observations,"no original endpoint to replay")
    if full:
        actors=data.actors[data.test];groups=[np.flatnonzero(actors==x) for x in np.unique(actors)]
        rng=np.random.default_rng(93623);draws=rng.integers(0,len(groups),(4000,len(groups)))
        w=np.array([np.bincount(row,minlength=len(groups)) for row in draws]);den=w@np.array(list(map(len,groups)))
        for label in sorted(LABELS|{"best"}):
            for ctrl in (*[x for x in ARMS if x!="returning"],"no_wire"):
                if ctrl=="no_wire" and label!="best":continue
                ct="returning" if ctrl=="no_wire" else ctrl
                cl="no_wire" if ctrl=="no_wire" else label
                d=np.mean([summary[f"returning-{s}",label]-summary[f"{ct}-{s}",cl] for s in SEEDS],axis=0)
                sums=np.array([d[:,i].sum(1) for i in groups]);ci=np.quantile((w@sums)/den[:,None],[.025,.975],axis=0).T
                records[label+"-returning-minus-"+ctrl]={"mean":d.mean(1).tolist(),"actor_95":ci.tolist()}
    receipt={"mode":"full" if full else "development_only","utc":datetime.now(timezone.utc).isoformat(),
             "torch_original":recipe["torch"],"torch_replay":str(torch.__version__),"atol":a.atol,"rtol":a.rtol,
             "script_sha256":sha(Path(__file__)),"cells_with_scores":len({k.split("/")[0] for k in observations}),
             "score_arrays":len(observations),"logits":sum(z["score_count"] for z in observations.values()),
             "all_bitwise_equal":all(z["bitwise_equal"] for z in observations.values()),
             "max_abs_error":max(z["max_abs_error"] for z in observations.values()),"arrays":observations,
             "objects_by_name":ev.files,"gates":detail,"actor_contrasts":records}
    receipt["terminal_sha"]=ev.files.get("original/terminal.json")
    receipt["seal_sha"]=ev.files.get("original/seal.json")
    receipt["original_arrays_and_weights_archived"]=True
    payload=(json.dumps(receipt,indent=2,allow_nan=False)+"\n").encode()
    path=a.archive/("receipt-"+hashlib.sha256(payload).hexdigest()+".json")
    with path.open("xb") as f:f.write(payload)
    print(json.dumps({k:receipt[k] for k in ("mode","cells_with_scores","score_arrays","logits","all_bitwise_equal","max_abs_error")}),flush=True)
    if full:
        dest=a.run/"strict_verification.json"
        # First successful publication remains the canonical original. Reruns retain independent receipts in archive.
        with tempfile.NamedTemporaryFile(dir=a.run,delete=False) as tmp:
            tmp.write(payload);tmp.flush()
            transient=Path(tmp.name)
        try:
            try:os.link(transient,dest)
            except FileExistsError:
                prior=read(dest)
                for k in ("terminal_sha","seal_sha","script_sha256","mode","cells_with_scores","objects_by_name","gates","actor_contrasts"):
                    check(prior.get(k)==receipt[k],"conflicting prior strict verification "+k)
        finally:transient.unlink(missing_ok=True)
    print(str(path),flush=True)

if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    for n in ("run","data_root","code","parent_study","archive"):cli.add_argument(n,type=Path)
    cli.add_argument("--development-only",action="store_true")
    cli.add_argument("--atol",type=float,default=0.)
    cli.add_argument("--rtol",type=float,default=0.)
    replay(cli.parse_args())
