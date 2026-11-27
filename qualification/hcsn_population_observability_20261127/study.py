"""Run the independent ROG reconstruction on a single CPU core. See ROG_PROTOCOL.md.

python study.py fit <run_directory>
python study.py confirm <run_directory>
python study.py score <run_directory>
All sources and weights are hashed before the call to convert official test records.
"""
import argparse,hashlib,json,os,platform,time
from pathlib import Path
from copy import deepcopy
import numpy as np
from panels import SETS,prepare

SEEDS=(109,271,443); ARMS=("monetary","probability","gate","lif","gru","transformer4","transformer16")
HERE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(p,data):p.write_text(json.dumps(data,indent=2,allow_nan=False)+"\n")
def err(prob,y):return ((np.eye(prob.shape[1])[y]-prob)**2).sum(1)
def dtw(x,train):
    distances=[]
    for signal in x:
        local=np.sum((signal[None,:,None,:]-train[:,None,:,:])**2,-1)
        n,a,b=local.shape;C=np.full((n,a+1,b+1),np.inf);C[:,0,0]=0.
        for j in range(1,a+1):
            for k in range(1,b+1):
                C[:,j,k]=local[:,j-1,k-1]+np.minimum(np.minimum(C[:,j-1,k],C[:,j,k-1]),C[:,j-1,k-1])
        distances.append(C[:,-1,-1])
    return np.stack(distances)
def vote(y,dist,k,alpha,num):
    nn=np.argsort(dist,axis=1,kind="stable")[:,:k]
    return (np.eye(num)[y[nn]].sum(1)+alpha)/(k+alpha*num)
def classical(z,ds,out):
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import SVC
    x=z["x"].reshape(len(z["x"]),-1);xd=z["x_dev"].reshape(len(z["x_dev"]),-1)
    y=z["y"];yd=z["y_dev"]
    for arm in ("logistic","rbf"):
        t=time.monotonic();best=np.inf;history=[]
        for c in (.01,.1,1.,10.,100.):
            model=LogisticRegression(C=c,max_iter=2000) if arm=="logistic" else SVC(C=c,probability=True,gamma="scale",random_state=109)
            model.fit(x,y);loss=float(err(model.predict_proba(xd),yd).mean())
            history.append([c,loss])
            if loss<best:best=loss;rule=model;bestc=c
        p=out/(ds+"-"+arm+".joblib");joblib.dump(rule,p)
        write(out/(ds+"-"+arm+".fit.json"),dict(arm=arm,elapsed=time.monotonic()-t,dev=best,C=bestc,history=history,sha256=sha(p)))
    t=time.monotonic();distance=dtw(z["x_dev"],z["x"]);hist=[]
    for k in (1,3,5,9):
        for a in (.1,1.):
            b=float(err(vote(y,distance,k,a,len(z["labels"])),yd).mean());hist.append([b,k,a])
    row=min(hist,key=lambda item:item[0])
    write(out/(ds+"-dtw.fit.json"),dict(dev=row[0],k=row[1],smoothing=row[2],history=hist,elapsed=time.monotonic()-t))
def neural(z,ds,arm,seed,out):
    import torch
    from population import make
    xt=torch.from_numpy(z["x"]);yt=torch.from_numpy(z["y"]);xd=torch.from_numpy(z["x_dev"]);yd=z["y_dev"]
    cls=len(z["labels"]);d=xt.shape[-1];best=cap=np.inf;history=[];state={};t0=time.monotonic()
    for rate in ((.001,.003,.008) if arm.startswith("transformer") else (.008,)):
        torch.manual_seed(seed);rng=np.random.default_rng(seed);net=make(arm,d,cls)
        pars=list(net.parameters());mom=[(torch.zeros_like(p),torch.zeros_like(p)) for p in pars]
        start=time.monotonic()
        for step in range(97):
            if step in (0,16,48,96):
                net.eval()
                with torch.no_grad():
                    pr=torch.cat([net(a) for a in xd.split(64)]).softmax(-1).numpy()
                v=float(err(pr,yd).mean());ts=time.monotonic()-start
                item=dict(step=step,rate=rate,dev=v,seconds_from_candidate_start=ts,seconds_from_family_start=time.monotonic()-t0)
                history.append(item)
                if v<best:best=v;state["full"]=deepcopy(net.state_dict());selected=item
                if (step==0 or ts<=30) and v<cap:cap=v;state["cap"]=deepcopy(net.state_dict());limited=item
            if step==96:break
            net.train();net.zero_grad(set_to_none=True);ix=rng.integers(len(yt),size=16)
            torch.nn.functional.cross_entropy(net(xt[ix]),yt[ix]).backward()
            with torch.no_grad():
                norm=torch.sqrt(sum(p.grad.square().sum() for p in pars if p.grad is not None))
                if not torch.isfinite(norm):raise FloatingPointError("gradient norm")
                sc=min(1.,2/(norm.item()+1e-6));it=step+1
                for p,(m,v) in zip(pars,mom):
                    if p.grad is None:continue
                    g=p.grad*sc;m.lerp_(g,.1);v.mul_(.999).addcmul_(g,g,value=.001)
                    den=v.sqrt().div_((1-.999**it)**.5).add_(1e-8)
                    p.addcdiv_(m,den,value=-rate/(1-.9**it))
    stem=f"{ds}-{arm}-{seed}";path=out/(stem+".pt")
    tmp=out/(stem+".new");torch.save(state,tmp);tmp.replace(path)
    write(out/(stem+".fit.json"),dict(dataset=ds,arm=arm,seed=seed,dev=best,cap_dev=cap,selected=selected,limited=limited,
                                      history=history,elapsed=time.monotonic()-t0,parameters=sum(p.numel() for p in pars),sha256=sha(path)))
def fit(root):
    import torch,scipy,sklearn
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    out=root/"fit";out.mkdir(exist_ok=True,parents=True)
    ledger={f:sha(HERE/f) for f in ("literal_original.py","population.py","panels.py","study.py","ROG_PROTOCOL.md")}
    seal=out/"fit-source.json"
    if seal.exists():assert json.loads(seal.read_text())==ledger
    else:write(seal,ledger)
    prepare(root/"raw",root/"panels","fit")
    choose={}
    for ds in SETS:
        z=np.load(root/"panels"/(ds+"-fit.npz"),allow_pickle=False)
        if not (out/(ds+"-dtw.fit.json")).exists():classical(z,ds,out)
        for seed in SEEDS:
            order=list(ARMS[:5]);np.random.default_rng(seed).shuffle(order)
            for arm in order+list(ARMS[5:]):
                stem=f"{ds}-{arm}-{seed}";path=out/(stem+".pt");record=out/(stem+".fit.json")
                if record.exists() and path.exists():
                    assert json.loads(record.read_text())["sha256"]==sha(path)
                    continue
                neural(z,ds,arm,seed,out);print("completed fit",stem,flush=True)
        d={}
        for arm in ("logistic","rbf","gru"):
            d[arm]=float(np.mean([json.loads(i.read_text())["dev"] for i in out.glob(f"{ds}-{arm}*.fit.json")]))
        choose[ds]={"selected":min(d,key=d.get),"dev":d}
    weights={p.name:sha(p) for p in out.iterdir() if p.suffix in (".pt",".joblib") or p.name.endswith("-dtw.fit.json")}
    assert len(weights)==72
    write(out/"SEAL.json",dict(files=weights,fit_sources=ledger,ordinary=choose,torch=torch.__version__,numpy=np.__version__,scipy=scipy.__version__,
             sklearn=sklearn.__version__,cpu_workers=torch.get_num_threads(),node=platform.node(),timestamp=time.time()))
def confirm(root):
    import torch,joblib
    from population import make
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    out=root/"fit";seal=json.loads((out/"SEAL.json").read_text())
    assert all(sha(out/f)==v for f,v in seal["files"].items())
    assert all(sha(HERE/f)==v for f,v in seal["fit_sources"].items())
    prepare(root/"raw",root/"panels","confirm")
    pred=root/"prediction";pred.mkdir(exist_ok=True)
    for ds in SETS:
        za=np.load(root/"panels"/(ds+"-fit.npz"),allow_pickle=False);z=np.load(root/"panels"/(ds+"-test.npz"),allow_pickle=False)
        x=torch.from_numpy(z["x"]);k=len(z["labels"]);xf=x.numpy().reshape(len(x),-1)
        for arm in list(ARMS)+["logistic","rbf","dtw"]:
            for seed in SEEDS if arm in ARMS else (0,):
                stem=f"{ds}-{arm}"+(f"-{seed}" if seed else "")
                target=pred/(stem+".npz");receipt=pred/(stem+".json")
                if target.exists() and receipt.exists():
                    assert sha(target)==json.loads(receipt.read_text())["sha256"];continue
                t=time.monotonic();data={"y":z["y"],"ids":z["id"]};details={}
                if arm in ("logistic","rbf"):
                    data["full"]=joblib.load(out/(stem+".joblib")).predict_proba(xf)
                elif arm=="dtw":
                    cfg=json.loads((out/(stem+".fit.json")).read_text())
                    data["full"]=vote(za["y"],dtw(z["x"],za["x"]),cfg["k"],cfg["smoothing"],k)
                else:
                    ck=torch.load(out/(stem+".pt"),weights_only=True,map_location="cpu")
                    net=make(arm,x.shape[-1],k);net.load_state_dict(ck["full"]);net.eval()
                    with torch.no_grad():
                        full=torch.cat([net(batch) for batch in x.split(64)])
                        data["full"]=full.softmax(-1).numpy();details["full_seconds_including_load"]=time.monotonic()-t
                        if arm in ("monetary","probability","gate"):
                            tr=torch.cat([net(batch,trace=True)[1] for batch in x.split(64)])
                            for j,f in enumerate(("hits","first","repeat")):data[f]=tr[...,j].sum(1).numpy()
                            details["max_mass_error"]=float((tr[...,3]-1).abs().max())
                            for rm in ("risk","both","reset"):
                                q=torch.cat([net(batch,remove=rm) for batch in x.split(64)])
                                data["without_"+rm]=q.softmax(-1).numpy()
                                details["mean_abs_logit_change_without_"+rm]=float((q-full).abs().mean())
                        net.load_state_dict(ck["cap"])
                        data["cap"]=torch.cat([net(batch) for batch in x.split(64)]).softmax(-1).numpy()
                np.savez_compressed(target,**data)
                write(receipt,dict(details,sha256=sha(target),elapsed=time.monotonic()-t))
        print("confirmed",ds,flush=True)
def score(root):
    seal=json.loads((root/"fit"/"SEAL.json").read_text());allsets={}
    for ds in SETS:
        tr=np.load(root/"panels"/(ds+"-fit.npz"));te=np.load(root/"panels"/(ds+"-test.npz"));classes=te["labels"];y=te["y"]
        rng=np.random.default_rng(5251)
        ix=np.concatenate([rng.choice(a,size=(5000,len(a))) for c in range(len(classes)) if len(a:=np.flatnonzero(y==c))],axis=1)
        scores={};losses={};caps={}
        for arm in list(ARMS)+["logistic","rbf","dtw"]:
            records=[];ev=[];ev_cap=[]
            for seed in SEEDS if arm in ARMS else (0,):
                stem=f"{ds}-{arm}"+(f"-{seed}" if seed else "")
                p=np.load(root/"prediction"/(stem+".npz"),allow_pickle=False)
                assert np.array_equal(p["y"],y) and np.array_equal(p["ids"],te["id"])
                pr=p["full"];assert np.isfinite(pr).all() and max(abs(pr.sum(1)-1))<1e-8
                e=err(pr,y);ev.append(e);ec=err(p["cap"] if "cap" in p else pr,y);ev_cap.append(ec)
                f=json.loads((root/"fit"/(stem+".fit.json")).read_text())
                rec=dict(seed=seed,brier=float(e.mean()),accuracy=float((pr.argmax(1)==y).mean()),
                    class_recalls=[float(np.mean(pr[y==c].argmax(1)==c)) for c in range(len(classes))],fit_seconds=f["elapsed"],parameters=f.get("parameters"))
                if "repeat" in p:
                    rec["mean_repeat_hits"]=float(p["repeat"].mean());rec["mean_total_hits"]=float(p["hits"].mean())
                    rec["frozen_brier_differences"]={what:float(np.mean(err(p["without_"+what],y)-e)) for what in ("risk","both","reset")}
                records.append(rec)
            losses[arm]=np.mean(ev,axis=0);caps[arm]=np.mean(ev_cap,axis=0)
            scores[arm]={"brier":float(losses[arm].mean()),"accuracy":float(np.mean([v["accuracy"] for v in records])),
                "macro_recall":float(np.mean([np.mean(v["class_recalls"]) for v in records])), "cap_brier":float(caps[arm].mean()),"records":records}
        contrasts={}
        for arm in scores:
            if arm=="monetary":continue
            d=losses["monetary"]-losses[arm];cd=caps["monetary"]-caps[arm]
            contrasts[arm]={"delta":float(d.mean()),"ci95":np.quantile(d[ix].mean(1),[.025,.975]).tolist(),
                "cap_delta":float(cd.mean()),"cap_ci95":np.quantile(cd[ix].mean(1),[.025,.975]).tolist(),
                "by_class":[float(d[y==c].mean()) for c in range(len(classes))]}
        chosen=seal["ordinary"][ds]["selected"]
        allsets[ds]={"methods":scores,"monetary_minus":contrasts,"ordinary":chosen,"classes":classes.tolist(),
            "sizes":[len(tr["y"]),len(tr["y_dev"]),len(y)],"class_counts":[np.bincount(z,minlength=len(classes)).tolist() for z in (tr["y"],tr["y_dev"],y)],
            "gate":all(contrasts[a]["ci95"][1]<0 for a in ("probability","gate","lif",chosen))}
    write(root/"RESULTS.json",{"sets":allsets,"gate":all(v["gate"] for v in allsets.values()),
             "scope":"Three fixed seeds on official record-level test splits. Stratified record-level bootstrap cannot cover unobserved clustering or new sites."})
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("phase",choices=["fit","confirm","score"]);ap.add_argument("run",type=Path)
    args=ap.parse_args();{"fit":fit,"confirm":confirm,"score":score}[args.phase](args.run)
