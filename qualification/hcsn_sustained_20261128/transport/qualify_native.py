"""Run a pinned PyTorch parent and its opt-in FFT variant on the same tasks/device."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

import torch

from fft_transport import transported_mass


def sha_git(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode()+data).hexdigest()


def patched_module(core, tmp):
    for filename, expected in (
        ("population.py", POPULATION_BLOB),
        ("he_xiong.py", "6c5d0c62e18b9df3b53bee0e356ffa2b85631405"),
    ):
        data=(core/filename).read_bytes()
        if sha_git(data)!=expected:
            raise ValueError(f"unexpected upstream source for {filename}")
        (tmp/filename).write_bytes(data)
    subprocess.run(["patch","--fuzz=0","-p1","-i",str(HERE/"compact_population.patch")],
                   check=True,cwd=tmp)
    sys.path.insert(0,str(tmp))
    import population
    return population


def native_equivalence(population, device, dtype):
    results=[]
    for k in (12,64):
        for port in ("boundary","priced","augmented"):
            torch.manual_seed(1000+k)
            dense=population.ContinuousSpikingNetwork(4,3,2,atoms=k,port=port).to(device,dtype)
            compact=copy.deepcopy(dense)
            compact.first.matrix_free=compact.second.matrix_free=True
            frames=torch.randn((7,4,4),dtype=dtype,device=device)
            weight=torch.randn((7,4,2),dtype=dtype,device=device)
            def run(model):
                data=frames.detach().clone().requires_grad_(True)
                logits,states=model(data)
                # A weighted task objective traverses both layers and recurrent time steps.
                loss=(logits*weight).mean()
                loss.backward()
                grads={n:p.grad.detach() for n,p in model.named_parameters()}
                return logits.detach(),[x.detach() for layer in states for x in layer],grads,data.grad
            a,sa,ga,da=run(dense); b,sb,gb,db=run(compact)
            def err(x,y): return float((x-y).abs().max())
            metrics={"logits":err(a,b),"last_states":max(err(x,y) for x,y in zip(sa,sb)),
                     "frames_gradient":err(da,db),"parameter_gradients":{n:err(x,gb[n]) for n,x in ga.items()}}
            worst=max(metrics["logits"],metrics["last_states"],metrics["frames_gradient"],
                      *metrics["parameter_gradients"].values())
            tol=2e-10 if dtype==torch.float64 else 4e-4
            if not worst<=tol: raise ValueError(f"native mismatch, atoms={k}, port={port}: {metrics}")
            results.append({"atoms":k,"port":port,"tolerances":tol,**metrics})
    return results


def timing(population, device, dtype, repeats):
    out=[]
    def sync():
        if device.type=="cuda": torch.cuda.synchronize()
    for k in (8,12,32,64,128,256,512):
        p=population.BoundaryPopulation(1,1,atoms=k).to(device,dtype)
        torch.manual_seed(7)
        m=torch.rand((8,k),device=device,dtype=dtype); m=m/m.sum(-1,keepdim=True)
        d=torch.rand((8,),device=device,dtype=dtype)*.32-.16
        target=torch.randn((8,k),device=device,dtype=dtype)
        def timed(fft):
            sync(); t=time.perf_counter()
            mass=m.detach().requires_grad_(True); delta=d.detach().requires_grad_(True)
            if fft:
                z,h=transported_mass(mass,delta,p.grid,sigma=p.prices.p.sigma,a=p.prices.a,dt=p.dt)
            else:
                K,q=p.kernels(p.grid+delta[:,None])
                z=(mass[...,None]*K).sum(-2);h=(mass*q).sum(-1)
            v=(z*target).sum()+h.sum()
            grads=torch.autograd.grad(v,(mass,delta))
            sync()
            return time.perf_counter()-t,(z.detach(),h.detach(),*grads)
        _,ref=timed(False);_,act=timed(True)
        err=[float((u-v).abs().max()) for u,v in zip(ref,act)]
        tol=3e-9 if dtype==torch.float64 else 4e-4
        if not max(err)<=tol: raise ValueError(f"kernel compare {k}: {err}")
        sample={"dense":[],"fft":[]}
        for i in range(repeats):
            for name in (("dense","fft") if i%2==0 else ("fft","dense")):
                elapsed,_=timed(name=="fft"); sample[name].append(elapsed)
        out.append({"atoms":k,"rows":8,"max_abs_live_flow_massgrad_shiftgrad":err,
                    "time_seconds":sample,
                    "dense_over_fft_median":statistics.median(sample['dense'])/statistics.median(sample['fft'])})
    return out


HERE=Path(__file__).resolve().parent
POPULATION_BLOB="82d010cbbcaf67a5895d717a9f0b9d8991b5613c"
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--core",type=Path,required=True)
    parser.add_argument("--device",choices=("cpu","cuda"),required=True)
    parser.add_argument("--dtype",choices=("float64","float32"),default="float64")
    parser.add_argument("--repeats",type=int,default=5)
    parser.add_argument("--output",type=Path,default=Path("native_transport_result.json"))
    args=parser.parse_args()
    device=torch.device(args.device)
    if device.type=="cuda" and not torch.cuda.is_available():
        raise RuntimeError("requested CUDA device unavailable")
    dtype=getattr(torch,args.dtype)
    torch.set_num_threads(1)
    with tempfile.TemporaryDirectory() as d:
        module=patched_module(args.core.resolve(),Path(d))
        report={"source_commit":"b3fdc981568ab9ce122d2fb569372651e0b4b314",
                "device":str(device),"dtype":args.dtype,"torch":str(torch.__version__),
                "hardware":torch.cuda.get_device_name(0) if device.type=="cuda" else platform.machine(),
                "rocm":torch.version.hip,"cuda_version":torch.version.cuda,
                "native_equivalence":native_equivalence(module,device,dtype),
                "timing":timing(module,device,dtype,args.repeats)}
    args.output.write_text(json.dumps(report,indent=2)+"\n")
    print(args.output)
