"""Paired CUDA readout update on frozen real-audiovisual HCSN parents."""
import argparse
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
START=time.perf_counter()

import numpy as np
import torch
import torch.nn.functional as F

def worker(args):
    code=Path(args.data)/'semantic_executor.py'
    spec=importlib.util.spec_from_file_location('profile',code)
    profile=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    hardware=profile.device()
    torch.set_num_threads(1)
    root=Path(args.parents); dest=Path(args.out)
    key=f'centered_{args.seed}'
    filename=root/(key+'.pt')
    if json.loads((root/'seal.json').read_text())[key]!=profile.digest(filename):
        raise ValueError('Unsealed parent')
    common={'seed':args.seed,'method':args.method,'hardware':hardware,'parent_sha256':profile.digest(filename)}
    net=profile.Hybrid('centered').cuda().eval()
    net.load_state_dict(torch.load(filename,map_location='cuda',weights_only=True))
    tr=profile.raw(args.data,'train')
    stat=(tr[0].mean(axis=(0,1,2)),np.maximum(tr[0].std(axis=(0,1,2)),.001),
          np.float32(max(tr[1][:,-1].std(),.001)))
    dst=dest/f'{args.method}_{args.seed}.pt'
    def inputs(split):
        return profile.normalized(profile.raw(args.data,split),stat)
    def feature_matrix(source):
        with torch.inference_mode():
            xs,base,labels,_=source
            batch,ticks,choices,width=xs.shape
            seq=xs.permute(1,0,2,3).reshape(ticks,batch*choices,width)
            state=None
            for tick in seq:
                if state is not None:
                    msg=torch.cat(((state.message[:,0]-net.body.fixed_boundary)[:,None],state.message[:,1:]),1)
                    state=replace(state,message=msg)
                logits,feat,state=net.body(tick[None],state=state,return_features=True)
            z=base+(logits[-1,:,1]-logits[-1,:,0]).reshape(batch,choices)
            h=feat[-1].reshape(batch,choices,-1)
            return (h[:,1]-h[:,0]).double(), (z[:,1]-z[:,0]).double()
    if args.mode=='fit':
        train=inputs('train')
        val=inputs('dev')
        design,incumbent=feature_matrix(train)
        scale=design.square().mean(0).sqrt().clamp_min(1.e-4)
        design=design/scale
        target=(2*train[2]-1).double()-incumbent
        torch.cuda.synchronize()
        feature_time=time.perf_counter()-START
        begin=time.perf_counter()
        lam=.5
        calls=0
        def objective(w):
            return (design.mv(w)-target).square().mean()/2+lam*w.square().sum()/2
        if args.method=='direct':
            gram=design.T@design/len(target)+lam*torch.eye(design.shape[1],dtype=design.dtype,device=design.device)
            w=torch.linalg.solve(gram,design.T@target/len(target))
        else:
            w=torch.zeros(design.shape[1],dtype=design.dtype,device=design.device,requires_grad=True)
            solver=torch.optim.LBFGS([w],lr=1,max_iter=60,max_eval=100,
                 tolerance_grad=1.e-10,tolerance_change=1.e-14,line_search_fn='strong_wolfe')
            def closure():
                nonlocal calls
                calls+=1
                solver.zero_grad()
                loss=objective(w)
                loss.backward()
                return loss
            solver.step(closure)
        torch.cuda.synchronize()
        opt_time=time.perf_counter()-begin
        with torch.no_grad():
            w=w.detach()
            grad=design.T@(design.mv(w)-target)/len(target)+lam*w
            delta=(w/scale/2).to(net.head.weight)
            net.head.weight[1].add_(delta)
            net.head.weight[0].sub_(delta)
            phys=net(*train[:2]); delta_pred=incumbent+design.mv(w)
            margin_error=((phys[:,1]-phys[:,0]).double()-delta_pred).abs().max().item()
            devlogits=net(*val[:2]); goodness=profile.scores(devlogits,val[2])
        torch.save(net.state_dict(),dst)
        torch.cuda.synchronize()
        common.update(objective=objective(w).item(),gradient_norm=grad.norm().item(),calls=calls,
               solve_wall=opt_time,cold_through_features=feature_time,projected_physical_error=margin_error,
               candidate_sha256=profile.digest(dst),dev=goodness,wall=time.perf_counter()-START)
    else:
        idn=f'{args.method}_{args.seed}'
        if json.loads((dest/'seal.json').read_text())[idn]!=profile.digest(dst):
            raise ValueError('Unsealed readout')
        with torch.inference_mode():
            panels={s:inputs(s) for s in ('test','retain')}
            original={s:net(*v[:2]).clone() for s,v in panels.items()}
            net.load_state_dict(torch.load(dst,map_location='cuda',weights_only=True))
            for s,v in panels.items():
                z=net(*v[:2]);old=original[s]
                common[s]=dict(edited=profile.scores(z,v[2]),parent=profile.scores(old,v[2]),
                    margins=(z[:,1]-z[:,0]).tolist(),parent_margins=(old[:,1]-old[:,0]).tolist(),
                    labels=v[2].tolist(),groups=v[3])
        torch.cuda.synchronize()
        common['wall']=time.perf_counter()-START
    profile.save(common,dest/f'{args.method}_{args.seed}.{args.mode}.json')

def run(a):
    loc=Path(a.out);loc.mkdir(exist_ok=False,parents=True)
    keys=[(s,m) for i,s in enumerate((47,83,137)) for m in (('direct','bp') if i%2==0 else ('bp','direct'))]
    output=[]
    for mode in ('fit','eval'):
        if mode=='eval':
            import hashlib
            ids={f'{m}_{s}':hashlib.sha256((loc/f'{m}_{s}.pt').read_bytes()).hexdigest() for s,m in keys}
            (loc/'seal.json').write_text(json.dumps(ids,sort_keys=True))
        for s,m in keys:
            t=time.perf_counter()
            subprocess.run([sys.executable,__file__,mode,'--data',a.data,'--parents',a.parents,'--out',a.out,
                            '--method',m,'--seed',str(s)],check=True)
            row=json.loads((loc/f'{m}_{s}.{mode}.json').read_text())
            row.update(mode=mode,process_wall=time.perf_counter()-t)
            output.append(row)
            print(mode,s,m,row['process_wall'],flush=True)
    (loc/'result.json').write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=('run','fit','eval'))
    p.add_argument('--data',required=True);p.add_argument('--parents',required=True);p.add_argument('--out',required=True)
    p.add_argument('--method',choices=('direct','bp'));p.add_argument('--seed',type=int)
    a=p.parse_args()
    run(a) if a.mode=='run' else worker(a)
