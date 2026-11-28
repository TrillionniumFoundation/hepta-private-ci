"""Fresh-process post-training editing clocks at the frozen third-intervention gate."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root=Path.home()/'.local/share/hepta-research'
native=root/'hcsn-cremad-e0bf-20261127'
parents=root/'hcsn-sustained-1140569'
old=root/'hcsn-rls-edit-1140569'
trial=root/'hcsn-9de7-betaedit-study'
snap='45fdc943c0484c36313199c6ab67c2f5e2c10ce02ef63eae52605ec1daa9620e'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def one(arm,seed):
    begin=time.perf_counter()
    import importlib.util
    import torch
    import numpy as np
    from torch.nn import functional as F
    sys.path[:0]=[str(old),str(parents),str(native/'src')]
    from study import Data,HASHES
    from study_edit import feature,get_net
    from rls_core import target_labels,projected,summarize,gate
    spec=importlib.util.spec_from_file_location('beta',root/'hcsn-9de7-betaedit.py')
    fresh=importlib.util.module_from_spec(spec);spec.loader.exec_module(fresh)
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    assert sha(trial/'development_seal.json')==snap
    seal=json.loads((trial/'development_seal.json').read_text())
    assert seal['gains'][arm]==.25
    for n,digest in HASHES.items():assert sha(native/n)==digest
    data=Data(native);net,rec=get_net(native,data,seed,parents)
    kt,_=feature(net,data);keys,_=feature(net,data,data.train);kd,_=feature(net,data,data.dev)
    w0=net.out[1].weight.T.detach().contiguous().double();w=w0.clone()
    kt=kt.float();keys=keys.double();y=data.y[data.train];ids=data.names[data.train]
    eligible=np.flatnonzero(y.numpy()//6>=6)
    eligible=eligible[np.argsort(ids[eligible],kind='stable')]
    anchor=np.random.default_rng(912731).choice(eligible,128,replace=False)
    anchor=anchor[np.argsort(ids[anchor],kind='stable')]
    a=torch.cat((kt.double(),keys[anchor]));C=a.T@a/len(a)
    u=fresh.cov_basis(C);hist=torch.zeros_like(C);seen=refresh=0;allk=[];alllabels=[]
    template=F.normalize(kt.double()@w0,dim=1);yd=data.y[data.dev]
    d0=projected(kd,kt,w0.float());prefit=time.perf_counter()-begin
    trace=[]
    for stage in range(3):
        st=time.perf_counter()
        order=np.flatnonzero(y.numpy()//6==stage);order=order[np.argsort(ids[order],kind='stable')]
        k=keys[order];new=target_labels(y[order],stage)
        if arm=='beta':
            for b in range(0,len(order),32):
                z=k[b:b+32];labs=new[b:b+32]
                if seen-refresh>=1000:
                    u=fresh.cov_basis((hist/seen+3000*C)/3001);refresh=seen
                v=(z@w0).norm(dim=1,keepdim=True)*template[labs]
                d=fresh.write_head(z,v-z@w,u,hist,C,3000)
                if float(d.norm())/len(z)**.5>20:raise ValueError('update norm')
                w=(w+d).float().double();hist+=z.T@z;seen+=len(z)
        else:
            allk.append(k);alllabels.append(new)
            ka=torch.cat(allk).float();target=torch.cat(alllabels)
            w=w.float().detach().clone().requires_grad_(True)
            opt=torch.optim.Adam([w],lr=.003);base=w0.float();af=a.float()
            for _ in range(128):
                opt.zero_grad(set_to_none=True);delta=w-base
                reg=(delta.square().sum()+1024*(af@delta).square().sum())/(len(ka)*w.shape[1])
                loss=F.cross_entropy(projected(ka,kt,w),target)+reg
                loss.backward();opt.step()
            w=w.detach().double()
        fit=time.perf_counter()-st;h=(w0+.25*(w-w0)).float()
        dm=summarize(projected(kd,kt,h),d0,yd,stage);pm=summarize(d0,d0,yd,stage)
        trace.append({'stage':stage,'fit_s':fit,'development_pass':bool(gate(dm,pm))})
    with np.load(trial/f'{arm}-{seed}.npz') as orig:
        err=float(np.max(np.abs(w.float().numpy()-orig['s2'])))
    if err>7e-5:raise ValueError(('head parity',err))
    hk,_=feature(net,data,data.test);hy=data.y[data.test]
    cold=projected(hk,kt,h);p0=projected(hk,kt,w0.float());mt=summarize(cold,p0,hy,2);mb=summarize(p0,p0,hy,2)
    good=bool(gate(mt,mb) and trace[-1]['development_pass'])
    if not good:raise ValueError('frozen comparison missed its joint gate')
    print(json.dumps({'arm':arm,'seed':seed,'prefit_s':prefit,'trace':trace,'head_max_abs':err,
                      'end_to_end_inside_s':time.perf_counter()-begin,'cold_metrics':mt,'passed':good}),flush=True)


def run():
    schedule=[]
    for rep in (0,1):
        for i,seed in enumerate((137,311,557)):
            arms=('beta','task_bp32') if (i+rep)%2==0 else ('task_bp32','beta')
            schedule.extend((rep,seed,arm) for arm in arms)
    rows=[]
    for rep,seed,arm in schedule:
        st=time.perf_counter()
        proc=subprocess.run([sys.executable,__file__,arm,str(seed)],capture_output=True,text=True)
        wall=time.perf_counter()-st
        if proc.returncode:raise RuntimeError(proc.stderr[-1300:])
        row=json.loads(proc.stdout.splitlines()[-1]);row.update(repetition=rep,launch_to_exit_s=wall)
        rows.append(row)
        print(rep,seed,arm,wall,flush=True)
        target=trial/'timing_progress.json'
        tmp=target.with_suffix('.next');tmp.write_text(json.dumps(rows,indent=1)+'\n');tmp.replace(target)
    (trial/'timing_complete.json').write_text(json.dumps({'endpoint':'third intervention, joint dev/held quality',
        'source_sha256':sha(Path(__file__)),'development_sha256':snap,'runs':rows},indent=1)+'\n')


if __name__=='__main__':
    if len(sys.argv)==3:one(sys.argv[1],int(sys.argv[2]))
    else:run()
