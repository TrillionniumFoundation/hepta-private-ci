"""Offline paired GPU pilot on two real streams. Model code and public, preprocessed records are embedded."""
import base64,hashlib,io,json,os,platform,sys,tempfile,time,zipfile
from pathlib import Path
START=time.perf_counter()
def unpack_source(payload):
    b=base64.b64decode(payload);root=Path(tempfile.mkdtemp(prefix="hcsn-feedback-"))
    with zipfile.ZipFile(io.BytesIO(b)) as f:
        for name in f.namelist():
            if name.startswith("/") or ".." in Path(name).parts: raise ValueError("foreign input path")
        f.extractall(root)
    return root
def write(root,record):
    p=Path("result.json");temp=p.with_suffix(".pending");temp.write_text(json.dumps(record,sort_keys=True,allow_nan=False)+"\n");os.replace(temp,p)
def main(payload):
    root=unpack_source(payload);sys.path.insert(0,str(root))
    import numpy as np
    import torch
    from model import FeedbackBoundary
    from boundary_variant import BoundaryVariant
    from qualification.hcsn_closure_20261124.baselines import GRUClassifier, CausalTransformer
    torch.set_num_threads(1); torch.backends.cuda.matmul.allow_tf32=False
    if not torch.cuda.is_available():raise RuntimeError("GPU required")
    CUDA=torch.device("cuda:0");torch.cuda.set_device(CUDA)
    # Verify real device work before any experimental slot.
    probe=torch.arange(128,dtype=torch.float64,device=CUDA);signature=float((probe@probe).item())
    assert signature==690880.
    data=np.load(root/"panel.npz",allow_pickle=False)
    plan=json.loads((root/"plan.json").read_text())
    out={"protocol":plan,"torch":str(torch.__version__),"device":torch.cuda.get_device_name(0),
         "cuda":torch.version.cuda,"hip":torch.version.hip,"gpu_check":signature,
         "source_panel_sha256":hashlib.sha256((root/"panel.npz").read_bytes()).hexdigest(),"slots":{}}
    write(root,out)
    def mkm(v):
        return (FeedbackBoundary("dual") if v=="newton" else BoundaryVariant("dual","halley") if v=="halley"
                else GRUClassifier(8) if v=="gru" else CausalTransformer(8))
    def metrics(pr,y):
        y=np.asarray(y);p=np.asarray(pr);pred=p>=.5
        return {"n":len(p),"accuracy":float((pred==y).mean()),"balanced_accuracy":float(np.mean([(pred[y==a]==a).mean() for a in [0,1] if (y==a).any()])),"brier":float(np.mean((p-y)**2))}
    def array(k):return torch.from_numpy(data[k].copy()).to(CUDA)
    snapshots={}
    for ds in plan["tasks"]:
        tr=array(ds+"_train_x");yt=array(ds+"_train_y");dv=array(ds+"_dev_x");yd=array(ds+"_dev_y")
        for arm in plan["order"][ds]:
            st=time.perf_counter();torch.manual_seed(plan["seed"]);torch.cuda.manual_seed_all(plan["seed"])
            m=mkm(arm).to(CUDA);opt=torch.optim.Adam(m.parameters(),lr=.003)
            g=torch.Generator().manual_seed(11*plan["seed"]); best=float("inf");history=[]
            for step in range(plan["steps"]+1):
                if step:
                    m.train();ix=torch.randperm(len(yt),generator=g)[:plan["batch"]].to(CUDA)
                    opt.zero_grad(set_to_none=True);z=m(tr[:,ix])[-1]
                    loss=torch.nn.functional.cross_entropy(z,yt[ix]);loss.backward()
                    norm=torch.nn.utils.clip_grad_norm_(m.parameters(),2);assert torch.isfinite(norm)
                    opt.step()
                if step in [0,plan["steps"]//2,plan["steps"]]:
                    with torch.no_grad():m.eval();p=m(dv)[-1].softmax(-1)[:,1]
                    score=(p-yd).square().mean().item()
                    history.append([step,score])
                    if score<best:
                        selected=step;best=score;buf=io.BytesIO();torch.save({k:v.detach().cpu() for k,v in m.state_dict().items()},buf);snapshots[(ds,arm)]=buf.getvalue()
            torch.cuda.synchronize(); out["slots"][ds+"/"+arm]={"fit_wall_s":time.perf_counter()-st,"dev":history,"selected":selected,
               "weight_sha256":hashlib.sha256(snapshots[(ds,arm)]).hexdigest(),"parameters":sum(p.numel() for p in m.parameters() if p.requires_grad)}
            write(root,out)
    out["seal"]={k:v["weight_sha256"] for k,v in out["slots"].items()};write(root,out)
    for (ds,arm),content in snapshots.items():
        st=time.perf_counter();m=mkm(arm).to(CUDA);m.load_state_dict(torch.load(io.BytesIO(content),weights_only=True));m.eval()
        with torch.no_grad():p=m(array(ds+"_eval_x"))[-1].softmax(-1)[:,1].cpu().tolist()
        y=data[ds+"_eval_y"].tolist();torch.cuda.synchronize()
        now=out["slots"][ds+"/"+arm]
        now.update(reload_eval_wall_s=time.perf_counter()-st,ids=data[ds+"_eval_ids"].tolist(),y=y,p=p,score=metrics(p,y),
                   weights_cpu_torch_base64=base64.b64encode(content).decode())
        write(root,out)
    out["process_wall_seconds"]=time.perf_counter()-START;out["complete"]=True;write(root,out)
