"""Verify the actual local GPU kernels, per-caption evaluator and physical front-end gradients."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import os
import platform
import time
import numpy as np
import torch
from torch.nn import functional as F

def main(worker,out):
    sp=importlib.util.spec_from_file_location('frozen_worker',worker)
    m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
    if not torch.backends.mps.is_available():raise RuntimeError('no MPS')
    if os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK','0')!='0':raise RuntimeError('CPU fallback enabled')
    torch.set_num_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    pack=base64.b85decode(m.PACK);xt,yt,sp,vocab=m.decode(pack,torch.device('cpu'))
    x,c,splits,v2=m.decode(pack,torch.device('mps'));assert vocab==v2
    assert torch.equal(x.cpu(),xt) and torch.equal(c.cpu(),yt)
    tst={};tables=m.law_tables()
    for arm in m.ARMS:
        torch.manual_seed(137);ref=m.Captioner(64,2,vocab,arm,tables)
        net=m.Captioner(64,2,vocab,arm,tables).to('mps');net.load_state_dict(ref.state_dict())
        q=sp[0][:3];y=yt[q,0];result=ref(xt[q],y[:,:-1])
        g=net(x[q],c[q,0,:-1]);loss=F.cross_entropy(g.flatten(0,1),c[q,0,1:].flatten(),ignore_index=0)
        opt=torch.optim.AdamW(net.parameters(),lr=.0003);opt.zero_grad();loss.backward()
        grad={k:float(v.grad.norm().cpu()) for k,v in net.front.named_parameters()}
        assert all(torch.isfinite(p.grad).all() for p in net.parameters())
        opt.step();torch.mps.synchronize()
        diff=float((g.detach().cpu()-result.detach()).abs().max())
        cost,n=m.evalset(net,x,c,splits[1][:3],torch.device('mps'))
        assert diff<.005 and cost.shape==(3,3) and np.isfinite(cost).all()
        tst[arm]=dict(all_grad_finite=True,front_gradient_norms=grad,cpu_logit_max_abs=diff,loss=float(loss.detach()),tokens=int(n.sum()))
    # Native production widths and checkpoint reload of a CPU state dictionary.
    probes={}
    for d,depth in m.SIZES:
        tic=time.monotonic()
        net=m.Captioner(d,depth,vocab,'physical',tables).to('mps');q=sp[0][:24]
        opt=torch.optim.AdamW(net.parameters(),lr=.0003);y=c[q,0];g=net(x[q],y[:,:-1])
        l=F.cross_entropy(g.flatten(0,1),y[:,1:].flatten(),ignore_index=0)
        l.backward();opt.step();torch.mps.synchronize()
        probes[d]=dict(params=sum(p.numel() for p in net.parameters()),loss=float(l.detach()),wall_s=time.monotonic()-tic,
                       gpu_allocated=torch.mps.current_allocated_memory(),driver_allocated=torch.mps.driver_allocated_memory())
        del net,opt,g,l;torch.mps.empty_cache()
    output=dict(torch=str(torch.__version__),system=platform.mac_ver()[0],mps_available=True,fallback_enabled=False,arms=tst,
                production_batch_24=probes,utc_epoch=time.time(),source_sha256=m.sha(worker))
    out.write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('worker','out'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();main(a.worker,a.out)
