"""Cold end-to-end paired times under a shared development and held acceptance gate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def child(folder,seed,method,gate,reference):
    import resource
    import numpy as np
    import torch
    import train
    from model import Network
    torch.set_num_threads(1)
    if method=="bp":
        train.EPOCHS=(1,) if gate>4 else (1,3)
    train.run(folder,seed,"financial",method)
    x,y,_,(_,_,held)=train.load_data(train.DATA)
    study=json.loads((folder/f"financial-{method}-{seed}-seal.json").read_text())
    key=study["gate_first"][str(gate)]
    if key is None:raise AssertionError("missed development gate")
    table,gain,_=train.make_table("financial")
    net=Network("financial",table,gain)
    with np.load(folder/(key+".npz")) as arrays:
        net.load_state_dict({k:torch.from_numpy(v) for k,v in arrays.items()})
    with torch.no_grad():z=net(torch.from_numpy(x[held].astype('float32'))).numpy()
    l=train.local_scores(z.astype(float),y[held])[0].mean()
    gold=json.loads(reference.read_text())["summary"]["financial-"+method][str(seed)]["gates"][str(gate)]
    if abs(l-gold["cold"])>1e-5 or gold["key"]!=key or l>gate:raise ValueError((l,gold,key))
    cpu=resource.getrusage(resource.RUSAGE_SELF)
    (folder/"done.json").write_text(json.dumps(dict(key=key,held=float(l),dev=next(r["dev"] for r in study["rows"] if r["key"]==key),
                    cpu=cpu.ru_utime+cpu.ru_stime,affinity=sorted(os.sched_getaffinity(0)))))


def run_panel(reference,out):
    allowed=sorted(os.sched_getaffinity(0));cpu=allowed[len(allowed)//2]
    os.sched_setaffinity(0,{cpu})
    rows=[]
    for repeat in range(2):
        for i,seed in enumerate((137,311,557)):
            for gate,method in ((4.10,"direct"),(3.75,"five")):
                pair=[method,"bp"] if (repeat+i)%2==0 else ["bp",method]
                for name in pair:
                    with tempfile.TemporaryDirectory() as d:
                        t=time.perf_counter()
                        proc=subprocess.run([sys.executable,__file__,"--directory",d,"--seed",str(seed),
                                "--method",name,"--gate",str(gate),"--reference",str(reference)],capture_output=True,text=True)
                        wall=time.perf_counter()-t
                        if proc.returncode:raise RuntimeError(proc.stderr)
                        done=json.loads((Path(d)/"done.json").read_text())
                        rows.append(dict(seed=seed,repeat=repeat,method=name,gate=gate,wall=wall,**done))
                        out.with_suffix(".partial").write_text(json.dumps(rows,indent=2)+"\n")
    out.write_text(json.dumps(dict(cpu=cpu,rows=rows),indent=2)+"\n")
if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--directory",type=Path);a.add_argument("--seed",type=int);a.add_argument("--method")
    a.add_argument("--gate",type=float);a.add_argument("--reference",type=Path,required=True);a.add_argument("--out",type=Path)
    p=a.parse_args()
    if p.directory:child(p.directory,p.seed,p.method,p.gate,p.reference)
    else:run_panel(p.reference,p.out)
