"""Single-thread, prospective time-budgeted paired RSICD study."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import numpy as np

REF=Path(os.environ.get("HCSN_REFERENCE", Path(__file__).resolve().parents[1] / "hcsn_continuous_20261127/paired_catalog"))
sys.path.insert(0,str(REF))
from common import ROOT, setup_data, gallery, score, store_model, load_model
from construct import fit, encode

SEEDS=[109,271,463]
SHORT=(12,60)
LONG=(120,600,1800,3600,7200)
FAMILIES=["literal","smooth","linear","conventional"]
def sha(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def atomic(path, obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=1,allow_nan=False));tmp.replace(path)
def settings(out,d,V):
    with np.load(ROOT/"law.npz") as f:z=dict(f)
    return z,np.flatnonzero(d["split"]==0),gallery(d,1)
def by_quality(row):
    return row["dev_r1"],row["dev_r5"],-row["time"]
def make_row(start,metrics,**kwargs):
    return {"dev_r1":metrics["strict_R1"],"dev_r5":metrics["strict_R5"],"time":time.perf_counter()-start,**kwargs}
def trial_dir(panel,family,seed):
    return ROOT/panel/(family+"-"+str(seed))
def constructive(panel,family,seed):
    out=trial_dir(panel,family,seed);out.mkdir(parents=True,exist_ok=True);start=time.perf_counter()
    d,V=setup_data();z,tr,dv=settings(out,d,V);rows=[]
    for w,reg in [(12,.1),(24,.1),(12,1.),(24,1.)]:
        # All model families use the same input gallery and scoring recipe.
        m=fit(V,d,tr,family,w,reg,seed,z);I,T=encode(V,d,dv,m,family,z);quality,_=score(I,T,d,dv)
        state=out/f'w{w}-r{reg}.npz';store_model(state,m,{"kind":np.array(family)})
        row=make_row(start,quality,width=w,ridge=reg,state=state.name,hash=sha(state));rows.append(row)
        atomic(out/"history.json",rows)
    atomic(out/"complete.json",{"fit_and_dev_s":time.perf_counter()-start,"num_states":len(rows)})
def neural(panel,seed):
    out=trial_dir(panel,"conventional",seed);out.mkdir(parents=True,exist_ok=True);start=time.perf_counter()
    import torch
    from neural import Conventional,Inputs,predictions,masked_infonce
    from adam import Adam
    torch.set_num_threads(1)
    d,V=setup_data();tr=np.flatnonzero(d["split"]==0);dv=gallery(d,1);inputs=Inputs("conv",d,V,"cpu")
    rates=[.001,.0003]; order=[0,1] if SEEDS.index(seed)%2==0 else [1,0]
    nets=[];ops=[];gens=[];steps=[0,0];rows=[];best=None
    for lr in rates:
        torch.manual_seed(seed);net=Conventional(int(d["tokens"].max())+1,24)
        nets.append(net);ops.append(Adam(net.parameters(),lr,weight_decay=.001));gens.append(np.random.default_rng(seed))
    bounds=LONG if panel=="long" else SHORT
    prior=0.0
    resume_path=out/"training.resume.pt"
    if panel=="long" and resume_path.exists():
        saved=torch.load(resume_path,map_location="cpu",weights_only=False)
        if saved["seed"]!=seed or saved["dataset"]!=sha(ROOT/"prepared.json"):
            raise RuntimeError("incompatible recovery")
        rows=saved["rows"];steps=saved["steps"];best=saved["best"];prior=saved["elapsed"]
        for i in range(2):
            nets[i].load_state_dict(saved["nets"][i])
            ops[i].n,ops[i].state=saved["optimizers"][i]
            gens[i].bit_generator.state=saved["generators"][i]
    def elapsed():
        return prior+time.perf_counter()-start
    def save_progress():
        if panel!="long":return
        tmp=out/"training.resume.tmp"
        checkpoint={"seed":seed,"dataset":sha(ROOT/"prepared.json"),"rows":rows,"steps":steps,
                    "best":best,"elapsed":elapsed(),"nets":[m.state_dict() for m in nets],
                    "optimizers":[(op.n,op.state) for op in ops],"generators":[g.bit_generator.state for g in gens]}
        torch.save(checkpoint,tmp);tmp.replace(resume_path)
    def evaluate(i):
        nonlocal best
        net=nets[i];net.eval();image=[];text=[]
        with torch.no_grad():
            for j in range(0,len(dv),128):
                x,y=net(*inputs.batch(dv[j:j+128]));image.append(x.numpy());text.append(y.numpy())
        metrics,_=score(np.concatenate(image),np.concatenate(text),d,dv)
        row=make_row(start,metrics,rate=rates[i],step=steps[i],state=None);quality=(row["dev_r1"],row["dev_r5"])
        if best is None or quality>best:
            path=out/f'lr{i}-s{steps[i]}.pt';torch.save(net.state_dict(),path);row["state"]=path.name;row["hash"]=sha(path);best=quality
        row["time"]=elapsed();rows.append(row);atomic(out/"history.json",rows)
    if not rows:
        for i in order:evaluate(i)
    last_save=elapsed()
    while elapsed() < max(bounds):
        for i in order:
            if elapsed()>=max(bounds):break
            net=nets[i];net.train();opt=ops[i]
            for _ in range(32):
                ix=gens[i].choice(tr,64,replace=False);opt.zero_grad()
                x,y=net(*inputs.batch(ix));loss=masked_infonce(x,y,torch.tensor(d["title"][ix]))
                loss.backward();opt.step();steps[i]+=1
            evaluate(i)
        if elapsed()-last_save >= 60:
            save_progress();last_save=elapsed()
    save_progress()
    atomic(out/"complete.json",{"fit_and_dev_s":elapsed(),"optimizer_steps":steps,"stop":"time_cap","model_params":sum(p.numel() for p in nets[0].parameters())})
def seal(panel):
    bounds=LONG if panel=="long" else SHORT
    selection={}
    for family in FAMILIES:
        for seed in SEEDS:
            runpanel="short" if panel=="long" and family!="conventional" else panel
            out=trial_dir(runpanel,family,seed)
            if not (out/"complete.json").exists():raise RuntimeError(f"outstanding fit {out.name}")
            rows=json.loads((out/"history.json").read_text())
            for t in bounds:
                eligible=[r for r in rows if r["state"] is not None and r["time"]<=t]
                key=f"{family}/{seed}/{t}"
                if not eligible:selection[key]=None;continue
                choice=max(eligible,key=by_quality);state=out/choice["state"];assert sha(state)==choice["hash"]
                selection[key]={"path":str(state.relative_to(ROOT)),"sha256":choice["hash"],"row":choice,"all_candidates_within_budget":sum(r['time']<=t for r in rows)}
    atomic(ROOT/panel/"seal.json",selection)
def confirm(panel):
    start=time.perf_counter();dest=ROOT/panel/"seal.json";selection=json.loads(dest.read_text());d,V=setup_data();ix=gallery(d,2)
    assert len(ix)==(d["split"]==2).sum()
    with np.load(ROOT/"law.npz") as f:z=dict(f)
    pred={}; scores={}; clocks={};cache={}
    for k,item in selection.items():
        if item is None:continue
        method,seed,budget=k.split("/")
        if item["sha256"] not in cache:
            s=time.perf_counter(); state=ROOT/item["path"];assert sha(state)==item["sha256"]
            if method=="conventional":
                import torch
                from neural import Conventional,Inputs
                torch.set_num_threads(1);net=Conventional(int(d['tokens'].max())+1,24)
                net.load_state_dict(torch.load(state,map_location='cpu',weights_only=True));net.eval();inputs=Inputs("conv",d,V,"cpu")
                I=[];T=[]
                with torch.no_grad():
                    for j in range(0,len(ix),128):
                        x,y=net(*inputs.batch(ix[j:j+128]));I.append(x.numpy());T.append(y.numpy())
                I,T=np.concatenate(I),np.concatenate(T)
            else:
                m,_=load_model(state);I,T=encode(V,d,ix,m,method,z)
            metrics,ranks=score(I,T,d,ix)
            rr=np.stack([ranks['image_to_text'],ranks['text_to_image']]).astype('int16')
            metrics['category_R1']=float((rr[:,:,2]==1).mean())
            cache[item["sha256"]]=(metrics,rr,time.perf_counter()-s)
        scores[k],pred[k],clocks[k]=cache[item["sha256"]]
    predfile=ROOT/panel/"cold_ranks.npz"
    np.savez_compressed(predfile,**pred)
    ci={}
    for t in (LONG if panel=='long' else SHORT):
        for a,b in [('literal','conventional'),('literal','smooth'),('literal','linear'),('conventional','linear')]:
            if any(f'{m}/{s}/{t}' not in pred for s in SEEDS for m in (a,b)):continue
            sides=[np.mean([(pred[f'{m}/{s}/{t}'][:,:,0]==1).mean(0) for s in SEEDS],axis=0) for m in (a,b)]
            diff=sides[0]-sides[1];rng=np.random.default_rng(220711);boots=np.concatenate([diff[rng.integers(len(diff),size=(100,len(diff)))].mean(1) for _ in range(80)])
            ci[f'{a}-{b}/{t}']={'estimate':float(diff.mean()),'paired95':np.quantile(boots,[.025,.975]).tolist()}
    atomic(ROOT/panel/"results.json",{"scores":scores,"cold_state_seconds":clocks,"paired":ci,"gallery":len(ix),"seeds":SEEDS,"seal_sha":sha(dest),"rank_sha":sha(predfile),"cold_confirm_s":time.perf_counter()-start})
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("action",choices=["fit","seal","confirm"]);p.add_argument("panel",choices=["short","long"]);p.add_argument("family",nargs="?",choices=FAMILIES);p.add_argument("seed",nargs="?",type=int);a=p.parse_args()
    if a.action=="fit":
        if a.family=="conventional":neural(a.panel,a.seed)
        else:constructive(a.panel,a.family,a.seed)
    elif a.action=="seal":seal(a.panel)
    else:confirm(a.panel)
