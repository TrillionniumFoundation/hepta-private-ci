import time
BEGIN=time.perf_counter()
import hashlib,json,sys,os
from pathlib import Path
import numpy as np
import torch
from gpu_model import StreamNetwork
base=Path(__file__).resolve().parent
plan=json.loads((base/"gpu_protocol.json").read_text());panel=base/"gpu_panel"
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,record):
    tmp=p.with_suffix(".pending");tmp.write_text(json.dumps(record,sort_keys=True,allow_nan=False)+"\n");os.replace(tmp,p)
def cpuweights(m):return {k:v.detach().cpu().clone() for k,v in m.state_dict().items()}
def seedmodel(w,arm):
    torch.manual_seed(w["seed"]);torch.cuda.manual_seed_all(w["seed"])
    return StreamNetwork(arm,w["n"],w["depth"],w["precision"]).cuda()
def data(w,split):
    file=panel/f"{w['task']}-{w['t']}-{split}.npz"
    if sha(file)!=json.loads((panel/"manifest.json").read_text())[file.name]["sha256"]:raise ValueError("panel drift")
    a=np.load(file,allow_pickle=False);dtype=torch.float64 if w["precision"]=="float64" else torch.float32
    return torch.from_numpy(a["x"]).to(device="cuda",dtype=dtype),torch.from_numpy(a["y"]).cuda(),a['ids'].tolist(),a['groups'].tolist()
@torch.no_grad()
def predict(m,x,y):
    m.eval();pr=torch.cat([m(b)[-1].softmax(-1)[:,1] for b in x.split(6,1)])
    cp,y=pr.cpu().double().numpy(),y.cpu().numpy();dec=cp>=.5
    if not np.isfinite(cp).all():raise FloatingPointError("non-finite prediction")
    return cp.tolist(),{"brier":float(np.mean((cp-y)**2)),"accuracy":float((dec==y).mean()),"balanced_accuracy":float(np.mean([(dec[y==i]==i).mean() for i in (0,1) if (y==i).any()]))}
def fit(w,arm,dir):
    train=data(w,"train");dev=data(w,"dev");m=seedmodel(w,arm)
    opt=torch.optim.Adam(m.parameters(),lr=plan["lr"]);rng=torch.Generator().manual_seed(11*w['seed'])
    initial=hashlib.sha256(b"".join(k.encode()+v.detach().cpu().numpy().tobytes() for k,v in m.named_parameters())).hexdigest()
    best=float("inf");first=None;history=[];target=plan["quality_targets"][w["task"]]
    torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize();start=time.perf_counter()
    for step in range(plan["steps"]+1):
        if step:
            m.train();rows=torch.randperm(len(train[1]),generator=rng)[:plan['batch']].cuda()
            opt.zero_grad(set_to_none=True);z=m(train[0][:,rows])[-1]
            loss=torch.nn.functional.cross_entropy(z,train[1][rows]);loss.backward()
            g=torch.nn.utils.clip_grad_norm_(m.parameters(),plan["clip"]);assert torch.isfinite(g)&torch.isfinite(loss)
            opt.step()
        if step in plan["dev_checkpoints"]:
            _,score=predict(m,*dev[:2]);torch.cuda.synchronize()
            elapsed=time.perf_counter()-BEGIN
            history.append(dict(step=step,process_s=elapsed,train_dev_s=time.perf_counter()-start,score=score))
            if first is None and score['brier']<=target:
                first=dict(step=step,process_s=elapsed);torch.save(cpuweights(m),dir/'threshold.pt')
            if score['brier']<best:
                best=score['brier'];selected=step;torch.save(cpuweights(m),dir/'selected.pt')
            write(dir/'train_progress.json',{"step":step,"history":history})
    torch.cuda.synchronize()
    write(dir/'fit.json',dict(initial=initial,selected=selected,first_hit=first,history=history,
      selected_sha256=sha(dir/'selected.pt'),threshold_sha256=sha(dir/'threshold.pt') if first else None,
      peak_gpu_bytes=torch.cuda.max_memory_allocated(),n_train=len(train[1]),n_dev=len(dev[1]),
      total_trainable=sum(p.numel() for p in m.parameters() if p.requires_grad),
      train_dev_s=time.perf_counter()-start,process_body_s=time.perf_counter()-BEGIN,
      torch=str(torch.__version__),hip=torch.version.hip,device=torch.cuda.get_device_name(),w=w,arm=arm))
def confirm(w,arm,dir):
    digest=json.loads((dir.parent/'seal.json').read_text())[arm]
    if sha(dir/'fit.json')!=digest:raise ValueError("fit seal mismatch")
    fit=json.loads((dir/'fit.json').read_text());x,y,ids,groups=data(w,"test");m=seedmodel(w,arm);evals={}
    for name in ("selected","threshold","quantized"):
        actual="selected" if name=="quantized" else name
        if fit[actual+"_sha256"] is None:continue
        file=dir/(actual+".pt")
        if sha(file)!=fit[actual+"_sha256"]:raise ValueError("weights differ")
        m.load_state_dict(torch.load(file,weights_only=True))
        if name=="quantized":
            with torch.no_grad():
                for q in m.parameters():
                    if q.requires_grad:
                        scale=q.abs().max()/127
                        if float(scale)>0:q.copy_((q/scale).round().clamp(-127,127)*scale)
        t=time.perf_counter();p,score=predict(m,x,y);torch.cuda.synchronize()
        evals[name]={"p":p,"metrics":score,"inference_wall_s":time.perf_counter()-t}
    write(dir/'predictions.json',dict(ids=ids,groups=groups,y=y.cpu().tolist(),evaluations=evals,
      process_body_s=time.perf_counter()-BEGIN,arm=arm,w=w))
if __name__=="__main__":
    mode,i,arm=sys.argv[1:];w=plan['waves'][int(i)];dir=base/'runs'/f"{int(i):04}"/arm;dir.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(1);torch.backends.cuda.matmul.allow_tf32=False
    if not torch.cuda.is_available():raise RuntimeError("no accelerator")
    torch.cuda.set_device(0)
    (fit if mode=="fit" else confirm)(w,arm,dir)
