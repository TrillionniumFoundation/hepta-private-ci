import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch


def check(core):
    sys.path.insert(0,str(core.resolve()))
    from parallel import ScanSpikingNetwork
    from population import ContinuousSpikingNetwork
    torch.set_num_threads(1);torch.manual_seed(35312)
    tests=[];worst=0.
    for n in (1,2,3,7,8,15,16,17,33):
        net=ScanSpikingNetwork(3,2,3,atoms=8)
        x=(torch.randn(n,2,3,dtype=torch.float64)*.18).requires_grad_(True)
        # Reference is the original state-recursive implementation with internal drive disabled.
        original=ContinuousSpikingNetwork(3,2,3,atoms=8,port='priced')
        with torch.no_grad():
            for q,w in [(original.first,net.first.law),(original.second,net.second.law)]:
                q.sender.load_state_dict(w.sender.state_dict());q.recurrent.weight.zero_();q.feedback.zero_()
        m1,_=original.first(x);m2,_=original.second(m1[...,:4].flatten(-2))
        base=net.head(m2[...,:4].flatten(-2))
        ys,final=net(x)
        err_ref=float((base-ys).abs().max().detach())
        pars=(x,*list(net.parameters()))
        d0=torch.autograd.grad(ys.square().mean(),pars,retain_graph=True)
        for mode in ('scan','block'):
            out,state=net(x,mode=mode,block=4)
            grad=torch.autograd.grad(out.square().mean(),pars)
            err=float((out-ys).abs().max().detach())
            de=max(float((a-b).abs().max()) for a,b in zip(grad,d0))
            mass=max(float((a[0].sum(-1)-1).abs().max().detach()) for a in state)
            if n>1:
                k=n//2;pa,sa=net(x[:k],mode=mode,block=4);pb,_=net(x[k:],sa,mode=mode,block=4)
                stream=float((torch.cat([pa,pb])-out).abs().max().detach())
            else:stream=0.
            worst=max(worst,err,de,err_ref,mass,stream)
            tests.append(dict(T=n,mode=mode,reference_error=err_ref,forward=err,gradient=de,conservation=mass,streaming=stream))
    assert worst<1e-10
    times=[]
    # Retain a whole-network objective and actual optimizer step for all transport strategies.
    for A in (8,12):
        for T in (16,64,256):
            x=torch.randn(T,4,3,dtype=torch.float64)*.18
            seed=ScanSpikingNetwork(3,4,3,atoms=A).state_dict()
            for mode in ('serial','scan','block'):
                net=ScanSpikingNetwork(3,4,3,atoms=A);net.load_state_dict(seed);opt=torch.optim.SGD(net.parameters(),lr=.001)
                forward=[];learning=[]
                for rep in range(6):
                    st=time.perf_counter()
                    with torch.inference_mode():net(x,mode=mode)
                    f=time.perf_counter()-st;st=time.perf_counter()
                    opt.zero_grad(set_to_none=True);y,s=net(x,mode=mode);y.square().mean().backward();opt.step()
                    w=time.perf_counter()-st
                    if rep:forward.append(f);learning.append(w)
                times.append(dict(atoms=A,T=T,width=4,batch=4,mode=mode,forward_median_s=float(np.median(forward)),training_step_median_s=float(np.median(learning)),all_forward=forward,all_train=learning,transition_bytes_per_layer=T*4*4*(A+1)**2*8))
    return dict(tests=tests,largest_checked_disagreement=worst,timing=times,torch=str(torch.__version__))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--core',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=check(a.core);a.out.write_text(json.dumps(r,indent=1)+'\n');print(r['largest_checked_disagreement'])
