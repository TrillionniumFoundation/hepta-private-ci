"""Check actual native attention dispatch on matching layouts; microbenchmark, not quality."""
from pathlib import Path
import json
import os
import statistics
import sys
import time
import warnings

import torch
from torch.nn import functional as F
from torch.nn.attention import SDPBackend, sdpa_kernel

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'kernel_diagnostics'
OUT.mkdir(exist_ok=True)


def run(device,batch,time_steps,width):
    torch.manual_seed(71029)
    x=torch.randn(batch,time_steps,width,device=device)
    qkv=torch.nn.Linear(width,3*width,device=device)
    def block():
        q,k,v=qkv(x).reshape(batch,time_steps,3,4,width//4).permute(2,0,3,1,4).unbind(0)
        a=F.scaled_dot_product_attention(q,k,v,is_causal=True)
        loss=a.square().mean()
        qkv.zero_grad(set_to_none=True)
        loss.backward()
        return a.detach()
    sync=torch.cuda.synchronize if device=='cuda' else lambda:None
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU]) as prof:
        result=block()
        sync()
    ops={k.key:k.count for k in prof.key_averages() if ('attention' in k.key.lower() or 'scaled_dot' in k.key.lower())}
    default=[]
    for k in range(13):
        sync();start=time.monotonic();block();sync()
        if k>=3:default.append(time.monotonic()-start)
    q,k,v=qkv(x).reshape(batch,time_steps,3,4,width//4).permute(2,0,3,1,4).unbind(0)
    alternatives={}
    for name in ('MATH','FLASH_ATTENTION','EFFICIENT_ATTENTION','CUDNN_ATTENTION'):
        option=getattr(SDPBackend,name,None)
        if option is None:continue
        try:
            with warnings.catch_warnings(record=True) as w, sdpa_kernel([option]):
                sync();beg=time.monotonic();z=block();sync()
            alternatives[name]=dict(available=True,single_unwarmed_seconds=time.monotonic()-beg,
                max_abs_from_default=float((z-result).abs().max()),warnings=[str(v.message)[:230] for v in w])
        except (RuntimeError,ValueError,NotImplementedError) as e:
            alternatives[name]=dict(available=False,error=str(e)[:350])
    return dict(device=device,dtype=str(q.dtype),batch=batch,tokens=time_steps,heads=4,head_dimension=width//4,
        q_stride=list(q.stride()),k_stride=list(k.stride()),v_stride=list(v.stride()),op_trace=ops,
        median_default_forward_loss_backward_seconds=statistics.median(default),samples_seconds=default,
        forced_alternatives=alternatives)


def main():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    device=sys.argv[1]
    if device=='cuda':assert (ROOT/'panel_gpu/completion.json').is_file() and torch.cuda.is_available()
    shapes=[(16,6,20)] if device=='cpu' else [(32,35,96),(32,47,96)]
    info={'torch':str(torch.__version__),'hip':torch.version.hip,'device':torch.cuda.get_device_name() if device=='cuda' else 'ai395 CPU',
      'real_training_code_uses_native_api':True,'method':'matching contiguous packed QKV forward, causal SDPA, scalar square loss and backward; isolated microbenchmark; no full model throughput inference',
      'observations':[run(device,*s) for s in shapes]}
    temp=OUT/(device+'.part');temp.write_text(json.dumps(info,indent=2,allow_nan=False));temp.replace(OUT/(device+'.json'))
    print(device,[q['op_trace'] for q in info['observations']],flush=True)


if __name__=='__main__':main()
