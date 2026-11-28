"""Gradient parity and measured native streaming costs for four six-layer encoders."""
import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import torch


def load_module(name,p):
    spec=importlib.util.spec_from_file_location(name,p)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def old_and_new(ref):
    folder=Path(__file__).resolve().parent
    sys.path.insert(0,str(folder))
    import encoder
    new=encoder.AVText
    original_dependency=load_module("original_hcsn_temporal",ref/"hcsn_temporal.py")
    modified=sys.modules["hcsn_temporal"]
    try:
        sys.modules["hcsn_temporal"]=original_dependency
        original=load_module("original_encoder",ref/"encoder.py").AVText
    finally:
        sys.modules["hcsn_temporal"]=modified
    return original,new


def run_chunks(model,hidden,parts):
    times,carry=0,None
    for length in parts:
        result,carry=model.encode_chunk(hidden[:,times:times+length],carry)
        times+=length
    if times!=hidden.size(1):
        raise ValueError("invalid partition")
    return result,carry


def memory_bytes(state):
    return sum(v.numel()*v.element_size() for group in state for v in group)


def derivative(model,h,fn):
    sample=h.detach().clone().requires_grad_()
    y=fn(model,sample)
    weight=torch.linspace(-.8,.7,y.size(1),device=y.device,dtype=y.dtype)
    names,vs=zip(*model.named_parameters())
    gs=torch.autograd.grad((y*weight).sum(),[sample,*vs],allow_unused=True)
    return y.detach(),dict(zip(("input",*names),gs))


def max_abs(x,y):
    return float((x-y).abs().max())


def clock(fn):
    begin=time.perf_counter()
    end=fn()
    return time.perf_counter()-begin,end


def run(ref,law,out):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    original,new=old_and_new(ref)
    arms=("literal","smooth","lif","sdpa")
    parity=[]
    for arm in arms:
        for dtype in (torch.float64,torch.float32):
            a,b=(cls(arm,96,137,56,law).to(dtype=dtype).eval() for cls in (original,new))
            b.load_state_dict(a.state_dict(),strict=True)
            gen=torch.Generator().manual_seed(98124)
            h=torch.randn(2,12,96,dtype=dtype,generator=gen)
            ref_y,ref_grad=derivative(a,h,lambda model,x:model.encode(x))
            for parts in (None,[12],[4,3,5],[1]*12):
                def pick(model,x):
                    return model.encode(x) if parts is None else run_chunks(model,x,parts)[0]
                z,gradient=derivative(b,h,pick)
                if {k for k,v in ref_grad.items() if v is None}!={k for k,v in gradient.items() if v is None}:
                    raise ValueError("different used weights")
                observed=[(k,max_abs(ref_grad[k],g)) for k,g in gradient.items() if g is not None]
                worst=max(observed,key=lambda pair:pair[1])
                atol=4e-5 if dtype==torch.float32 else 1e-7
                for k,g in gradient.items():
                    if g is not None:
                        torch.testing.assert_close(g,ref_grad[k],rtol=3e-4 if dtype==torch.float32 else 1e-6,atol=atol)
                torch.testing.assert_close(z,ref_y,rtol=3e-5,atol=1e-6)
                parity.append(dict(arm=arm,dtype=str(dtype),parts=parts,output=max_abs(z,ref_y),
                    max_grad=worst[1],max_grad_key=worst[0],input_grad=max_abs(gradient["input"],ref_grad["input"]),
                    checked_derivatives=len(observed)))
        print("parity",arm,flush=True)
    measurements=[]
    with torch.inference_mode():
        for arm in arms:
            net=new(arm,96,137,56,law).eval()
            for length in (16,64,256):
                g=torch.Generator().manual_seed(239391+length)
                h=torch.randn(1,length,96,generator=g)
                net.encode(h[:,:4])
                expected=net.encode(h)
                for chunk in (0,1,16):
                    parts=[chunk]*(length//chunk) if chunk else None
                    def evaluate():
                        if parts is None:
                            return net.encode(h),None
                        return run_chunks(net,h,parts)
                    samples=[]
                    for _ in range(3):
                        elapsed,(value,state)=clock(evaluate)
                        samples.append(elapsed)
                    torch.testing.assert_close(value,expected,atol=4e-5,rtol=1e-4)
                    measurements.append(dict(arm=arm,length=length,chunk=chunk,seconds=samples,
                          median_s=statistics.median(samples),persistent_logical_state_bytes=memory_bytes(state) if state else None,
                          max_output_abs=max_abs(expected,value)))
                print("speed",arm,length,flush=True)
    out.write_text(json.dumps(dict(device="cpu",nthreads=torch.get_num_threads(),torch=str(torch.__version__),
                      depth=6,width=96,parity=parity,measurements=measurements),indent=2)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("original",type=Path)
    p.add_argument("law",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    run(a.original.resolve(),a.law.resolve(),a.output.resolve())
