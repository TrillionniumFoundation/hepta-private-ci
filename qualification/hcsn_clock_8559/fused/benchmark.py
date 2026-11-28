"""Real SHD gradients, forward, backward/update and compilation costs for the native population."""
import argparse
import copy
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch
from torch.nn import functional as F
from native import enable,Classifier,COST,library
from train import Data,SEEDS

def copy_parameters(source,target):
    with torch.no_grad():
        for p,q in zip(target.parameters(),source.parameters()):p.copy_(q)
def execute(m,x,y,update=False):
    x=x.clone().requires_grad_();m.zero_grad(set_to_none=True)
    opt=torch.optim.AdamW(m.parameters(),lr=.001,weight_decay=.01) if update else None
    before=time.perf_counter();cp=time.process_time();pred=m(x);loss=F.cross_entropy(pred,y)
    forward=time.perf_counter()-before;loss.backward()
    if opt:
        torch.nn.utils.clip_grad_norm_(m.parameters(),1.,error_if_nonfinite=True);opt.step()
    timing=dict(forward_wall_s=forward,all_wall_s=time.perf_counter()-before,all_cpu_s=time.process_time()-cp)
    values={name:p.grad.detach().numpy().copy() for name,p in m.named_parameters()}
    values['input']=x.grad.detach().numpy().copy();values['logits']=pred.detach().numpy()
    return timing,values,float(loss.detach())

def main(root,out):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    data=Data(root);library()
    log=[];panels=[]
    for seed in SEEDS:
        gen=np.random.default_rng(seed+821);torch.manual_seed(seed)
        for arm in ('literal','smooth','fixed','no_feedback'):
            a=Classifier(arm);b=enable(copy.deepcopy(a))
            for scale in (.1,1.,3.):
                idx=gen.integers(0,len(data.x),size=16)
                x,y=data.x[idx]*scale,data.y[idx]
                wa,va,la=execute(a,x,y);wb,vb,lb=execute(b,x,y)
                metrics={}
                for k,p in va.items():
                    q=vb[k];dif=np.abs(p-q)
                    metrics[k]=dict(max_abs=float(dif.max()),l2_rel=float(np.linalg.norm(p-q)/max(1.e-10,np.linalg.norm(p))))
                panels.append(dict(arm=arm,seed=seed,scale=scale,reference_loss=la,native_loss=lb,gradients=metrics))
            if arm=='literal':
                for j in range(8):
                    idx=gen.integers(0,len(data.x),size=48);x,y=data.x[idx],data.y[idx]
                    order=list(gen.permutation(['native','reference']))
                    for k in order:
                        model=b if k=='native' else a
                        # Equal underlying weights for every paired call, identical optimizer and gradients.
                        if k=='native':copy_parameters(a,b)
                        else:old={n:p.detach().clone() for n,p in a.named_parameters()}
                        t,_,loss=execute(model,x,y,True)
                        if k=='reference':
                            with torch.no_grad():
                                for n,p in a.named_parameters():p.copy_(old[n])
                        log.append(dict(arm=k,trial=j,seed=seed,order=order,loss=loss,**t))
    timings={k:np.array([r['all_cpu_s'] for r in log if r['arm']==k]) for k in ('reference','native')}
    ratio=timings['reference']/timings['native']
    report=dict(compile=COST,rows=panels,timings=log,reference_median_cpu=float(np.median(timings['reference'])),
                native_median_cpu=float(np.median(timings['native'])),paired_median_speedup=float(np.median(ratio)),
                observed_speed_ratio_range=[float(ratio.min()),float(ratio.max())],data_setup_s=data.setup_wall_s)
    out.write_text(json.dumps(report,indent=1)+'\n')
    print({k:v for k,v in report.items() if k not in ('timings','rows')},flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('data',type=Path);ap.add_argument('out',type=Path);ap.add_argument('--v2',action='store_true');a=ap.parse_args()
    if a.v2:
        from native_v2 import enable,COST,library
    main(a.data,a.out)
