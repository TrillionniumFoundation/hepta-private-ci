"""Run the kernel, every comparator and one genuine update locally before GPU dispatch."""
import argparse
import importlib.util
from pathlib import Path
import time
import torch

p=argparse.ArgumentParser();p.add_argument('path',type=Path);args=p.parse_args()
sp=importlib.util.spec_from_file_location('hcsn_scale',args.path);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
torch.set_num_threads(1);m.torch.backends.mha.set_fastpath_enabled(False)
tables=m.law_tables()
device=torch.device('cpu');x,c,splits,v=m.decode(m.base64.b85decode(m.PACK),device)
for arm in m.ARMS:
    torch.manual_seed(137);net=m.Captioner(64,2,v,arm,tables)
    opt=torch.optim.AdamW(net.parameters(),lr=.0003)
    y=c[splits[0][:3],0]
    out=net(x[splits[0][:3]],y[:,:-1]);loss=m.F.cross_entropy(out.flatten(0,1),y[:,1:].flatten(),ignore_index=0)
    loss.backward()
    print(arm,out.shape,float(loss.detach()),[(n,round(float(p.grad.norm()),7)) for n,p in net.front.named_parameters() if p.grad is not None],flush=True)
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in net.parameters())
    opt.step()
    q,n=m.evalset(net,x,c,splits[1][:3],device)
    assert q.shape==n.shape==(3,c.shape[1]) and (n>0).all()
print('split',list(map(len,splits)),v)
