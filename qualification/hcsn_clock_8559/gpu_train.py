"""Single-GPU synchronized fit clocks with restartable weights and optimizer."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import time
import numpy as np
import torch
from torch.nn import functional as F
from model import ARMS,Classifier
from train import Data,SEEDS,RUNGS,MATCHED,atomic_json,digest,save,evaluate,apply


def cpu_params(m):
    return {k:p.detach().cpu().clone() for k,p in m.named_parameters()}

def board():
    try:
        v=subprocess.run(['nvidia-smi','--query-gpu=timestamp,name,memory.free,utilization.gpu,power.draw',
                          '--format=csv,noheader'],capture_output=True,text=True,timeout=6)
        return v.stdout.strip()
    except Exception as e:return str(e)

def run_arm(d,root,arm,seed,budget):
    out=root/f'{arm}-{seed}';out.mkdir(exist_ok=True)
    record=out/f'rung-{budget}.json';selected=out/f'selected-{budget}.pt'
    if record.exists():
        assert digest(selected)==json.loads(record.read_text())['selected_hash']
        return
    start=time.perf_counter();torch.manual_seed(seed)
    m=Classifier(arm).cuda()
    opt=torch.optim.AdamW(m.parameters(),lr=.001,weight_decay=.01)
    gen=torch.Generator().manual_seed(seed+17001)
    restart=out/'resume.pt'
    stats=dict(step=0,fit_cpu_s=0.,fit_wall_s=0.,overhead_wall_s=0.,best=None,validation=[],loss=None)
    if restart.exists():
        c=torch.load(restart,weights_only=True,map_location='cpu')
        assert (c['arm'],c['seed'])==(arm,seed)
        apply(m,c['weights']);opt.load_state_dict(c['optimizer']);gen.set_state(c['stream']);stats=c['stats']
    before_board=board()
    torch.cuda.synchronize();stats['overhead_wall_s']+=time.perf_counter()-start
    def checkpoint():
        cost=time.perf_counter()
        save(restart,dict(arm=arm,seed=seed,weights=cpu_params(m),optimizer=opt.state_dict(),stream=gen.get_state(),stats=stats))
        stats['overhead_wall_s']+=time.perf_counter()-cost
    last=stats['fit_wall_s'];m.train()
    torch.cuda.reset_peak_memory_stats()
    while stats['fit_wall_s']<budget:
        wall=time.perf_counter();cpu=time.process_time()
        ids=torch.randint(len(d.x),(48,),generator=gen).cuda()
        opt.zero_grad(set_to_none=True)
        loss=F.cross_entropy(m(d.x[ids]),d.y[ids]);loss.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(),1.,error_if_nonfinite=True);opt.step()
        torch.cuda.synchronize();v=float(loss.detach().item())
        if not np.isfinite(v):raise ValueError('nonfinite training loss')
        stats['fit_wall_s']+=time.perf_counter()-wall;stats['fit_cpu_s']+=time.process_time()-cpu
        stats['step']+=1;stats['loss']=v
        if stats['step'] in MATCHED:
            stamp=time.perf_counter();save(out/f'update-{stats["step"]}.pt',cpu_params(m));stats['overhead_wall_s']+=time.perf_counter()-stamp
        if stats['fit_wall_s']-last>=30.:checkpoint();last=stats['fit_wall_s']
    st=time.perf_counter();v=evaluate(m,d.xd,d.yd,d.sd)
    v.update(step=stats['step'],budget=budget,fit_gpu_wall_s=stats['fit_wall_s'])
    old=stats['best']
    if old is None or (v['dev_macro'],-v['dev_nll'],-v['step'])>(old['dev_macro'],-old['dev_nll'],-old['step']):
        stats['best']=dict(v);save(out/'best.pt',cpu_params(m))
    save(selected,torch.load(out/'best.pt',weights_only=True,map_location='cpu'))
    if stats['validation'] and stats['validation'][-1]['budget']==budget:stats['validation'].pop()
    stats['validation'].append(v)
    torch.cuda.synchronize();stats['overhead_wall_s']+=time.perf_counter()-st
    checkpoint()
    r=dict(stats,arm=arm,seed=seed,budget=budget,param_count=sum(p.numel() for p in m.parameters()),
           data_setup_wall_s=d.setup_wall_s,selected_hash=digest(selected),device=torch.cuda.get_device_name(),
           torch_version=str(torch.__version__),pre_gpu=before_board,post_gpu=board(),gpu_peak_reserved=torch.cuda.max_memory_reserved(),
           observed_at=time.time(),clock='synchronized accelerator fit wall time')
    atomic_json(record,r)
    print(arm,seed,budget,stats['step'],stats['best'],flush=True)


def main(a):
    assert torch.cuda.is_available()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.40)
    start=time.perf_counter();data=Data(a.data)
    for field in ('x','y','xd','yd','sd'):setattr(data,field,getattr(data,field).cuda())
    torch.cuda.synchronize();data.setup_wall_s=time.perf_counter()-start
    a.out.mkdir(parents=True,exist_ok=True)
    for budget in a.rungs:
        jobs=[(arm,seed) for seed in SEEDS for arm in ARMS]
        for ix in np.random.default_rng(201126+budget).permutation(len(jobs)):
            arm,seed=jobs[ix];run_arm(data,a.out,arm,seed,budget)
        entries=[]
        for arm,seed in jobs:
            rec=a.out/f'{arm}-{seed}'/f'rung-{budget}.json';r=json.loads(rec.read_text())
            entries.append(dict(arm=arm,seed=seed,budget=budget,receipt_sha256=digest(rec),selected_sha256=r['selected_hash']))
        atomic_json(a.out/f'seal-{budget}.json',entries)
        print('SEALED',budget,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('out',type=Path)
    p.add_argument('--rungs',nargs='+',type=int,default=RUNGS);main(p.parse_args())
