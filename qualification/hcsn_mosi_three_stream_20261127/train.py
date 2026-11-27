"""Fit one arm with time-limited development selection. No test file is opened."""
import time
ENTRY=time.perf_counter();ENTRYCPU=time.process_time()
import argparse
import json
import os
from pathlib import Path
import numpy as np
import torch
from models import *
from source import sha


def local_ridge(x,t,lam):
    x=x.to(torch.float64);t=t.to(torch.float64)
    gram=x.T@x;pen=lam*(gram.diag().mean().clamp(min=1e-10))
    gram.diagonal().add_(pen)
    return torch.linalg.solve(gram,x.T@t).to(torch.float32)


@torch.inference_mode()
def readout(head,h,y,lam):
    # Centering fits a free intercept. Choose the primal or the smaller dual system exactly.
    h=h.to(torch.float64);yy=y.double().reshape(-1,1);m=h.mean(0);b=yy.mean(0)
    h-=m;yy=yy-b
    pen=lam*(h.square().sum()/h.shape[1]).clamp(min=1e-10)
    if h.shape[1]>len(h):
        c=h@h.T;c.diagonal().add_(pen);w=h.T@torch.linalg.solve(c,yy)
    else:
        c=h.T@h;c.diagonal().add_(pen);w=torch.linalg.solve(c,h.T@yy)
    head.weight.copy_(w.T.float());head.bias.copy_((b-m@w).float())


def task_code(y):
    # Barycentric code on integer rating anchors preserves magnitude and sign.
    z=(y+3.).clamp(0,6);lo=z.floor().long();hi=(lo+1).clamp(max=6)
    a=torch.zeros(len(y),7);a.scatter_add_(1,lo[:,None],(1-z+lo)[:,None])
    a.scatter_add_(1,hi[:,None],(z-lo)[:,None]);return a


def main():
    q=argparse.ArgumentParser();q.add_argument('data',type=Path);q.add_argument('law',type=Path);q.add_argument('out',type=Path)
    q.add_argument('width',type=int);q.add_argument('arm');q.add_argument('seed',type=int,choices=SEEDS);a=q.parse_args()
    if (a.width,a.arm) not in designs():raise ValueError((a.width,a.arm))
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    x,y,g=read_split(a.data,'train');v,yv,gv=read_split(a.data,'valid')
    x=modalities(x,a.arm);v=modalities(v,a.arm)
    w=a.width;arm=a.arm;seed=a.seed
    a.out.mkdir(parents=True,exist_ok=True);prefix=f'{w}-{arm}-{seed}';done=a.out/(prefix+'.json')
    if done.exists():raise FileExistsError(done)
    gen=torch.Generator().manual_seed(seed+913);probe_id=torch.randperm(len(x),generator=gen)[:192]
    def initial():
        torch.manual_seed(seed)
        return model(w,arm,a.law)
    net=initial()
    init_weights=([layer.weight.detach().clone() for layer in net.layers] if isinstance(net,ThreeStage) else [])
    sourcecost={'wall':time.perf_counter()-ENTRY,'cpu':time.process_time()-ENTRYCPU}
    wall=time.perf_counter();cpu=time.process_time();elapsed=lambda:time.process_time()-cpu
    # All setup that depends on training labels/features or model initialization after this point counts.
    history=[];rank={r:None for r in RUNGS};states={r:None for r in RUNGS};selected={r:None for r in RUNGS}
    timing={'local_target_and_solves_s':0.,'feature_and_readout_s':0.,'optimizer_s':0.,'all_dev_s':0.}
    y_dev=yv.numpy()
    def consider(network,detail):
        s=time.process_time();z=predict(network,v);mae,mse=metrics(z,y_dev,gv);timing['all_dev_s']+=time.process_time()-s
        t=elapsed();rw=time.perf_counter()-wall
        row={**detail,'dev_video_mae':mae,'dev_pooled_mse':mse,'cpu':t,'wall':rw};history.append(row)
        cand=(mae,mse)
        use=[r for r in RUNGS if t<=r and (rank[r] is None or cand<rank[r])]
        if use:
            state={k:v.detach().clone() for k,v in network.state_dict().items()}
            if isinstance(network,ThreeStage):row['hidden_write_fro']=[float(torch.linalg.vector_norm(layer.weight.detach()-base)) for layer,base in zip(network.layers,init_weights)]
            for r in use:rank[r]=cand;states[r]=state;selected[r]=row.copy()
    if arm in RAW:
        f=net.inputs(x)
        for lam in PENALTIES:
            s=time.process_time();readout(net.head,f,y,lam);timing['feature_and_readout_s']+=time.process_time()-s
            consider(net,{'penalty':lam})
    elif arm=='random_h':
        s=time.process_time();initialize_norms(net,x[probe_id]);h=torch.cat([net.hidden(k).detach() for k in x.split(batch_size(net))]);timing['feature_and_readout_s']+=time.process_time()-s
        for lam in PENALTIES:
            s=time.process_time();readout(net.head,h,y,lam);timing['feature_and_readout_s']+=time.process_time()-s
            consider(net,{'penalty':lam})
    elif arm.startswith('fp_'):
        rand=torch.Generator().manual_seed(seed+2801)
        keys=[(torch.randn((n,w),generator=rand),torch.randn((7,w),generator=rand)) for n in (793,w,w)]
        labels=task_code(y)
        if arm=='fp_h_shuffle':labels=labels[torch.randperm(len(y),generator=rand)]
        for lam in PENALTIES:
            if elapsed()>=max(RUNGS):break
            h=x
            with torch.inference_mode():
                for j,((Q,U),layer) in enumerate(zip(keys,net.layers)):
                    s=time.process_time();flat=h.reshape(-1,h.shape[-1]);targets=torch.sign(flat@Q)+torch.sign(labels@U).repeat_interleave(h.shape[1],dim=0)
                    layer.weight.copy_(local_ridge(flat,targets,lam).T);timing['local_target_and_solves_s']+=time.process_time()-s
                    del targets,flat
                    s=time.process_time();h=setnorm(net,reapply_layer(net,h,j),j);timing['feature_and_readout_s']+=time.process_time()-s
                s=time.process_time();readout(net.head,grouped_repr(h),y,lam);timing['feature_and_readout_s']+=time.process_time()-s
            consider(net,{'penalty':lam,'hidden_writes':3,'label_target':'seven-anchor barycentric + sign projection'})
    else:
        learn=[]
        for lr in (.0005,.003):
            md=initial()
            if isinstance(md,ThreeStage):
                s=time.process_time();initialize_norms(md,x[probe_id]);timing['feature_and_readout_s']+=time.process_time()-s
            opt=torch.optim.AdamW(md.parameters(),lr=lr,weight_decay=1e-4)
            learn.append((lr,md,opt))
        for lr,md,opt in learn:consider(md,{'lr':lr,'steps':0})
        idxgen=torch.Generator().manual_seed(seed+771);step=0
        while elapsed()<max(RUNGS):
            step+=1;ii=torch.randint(len(x),(24,),generator=idxgen)
            for lr,md,opt in learn:
                if elapsed()>=max(RUNGS):break
                s=time.process_time();md.train();opt.zero_grad(set_to_none=True)
                loss=(md(x[ii])-y[ii]).square().mean();loss.backward()
                torch.nn.utils.clip_grad_norm_(md.parameters(),1.,error_if_nonfinite=True);opt.step();timing['optimizer_s']+=time.process_time()-s
                if step in (1,4,12) or step%24==0:consider(md,{'lr':lr,'steps':step})
    fit_cpu=elapsed();fit_wall=time.perf_counter()-wall
    serialized={};archive_wall=time.perf_counter()
    for r,weights in states.items():
        if weights is None:continue
        # The same object can be the selected candidate for several time prefixes.
        ident=id(weights)
        if ident not in serialized:
            path=a.out/(prefix+f'-r{r}.pt');torch.save(weights,path);serialized[ident]=(path.name,sha(path))
        name,checksum=serialized[ident];selected[r].update({'file':name,'sha256':checksum})
    receipt={'width':w,'arm':arm,'seed':seed,'common_process':sourcecost,'fit_cpu':fit_cpu,'fit_wall':fit_wall,'serialization_wall':time.perf_counter()-archive_wall,'thread_count':torch.get_num_threads(),'affinity':sorted(os.sched_getaffinity(0)), 'parameter_count':sum(p.numel() for p in net.parameters()),'input_dims':793,'hidden_depth':3 if isinstance(net,ThreeStage) else (len(net.layers) if hasattr(net,'layers') else 0),'cost_breakdown_cpu':timing,'history':history,'selected':selected}
    done.write_text(json.dumps(receipt,sort_keys=True,indent=1,allow_nan=False)+'\n')
    print(prefix,receipt['parameter_count'],len(history),round(fit_cpu,2),flush=True)


if __name__=='__main__':main()
