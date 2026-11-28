"""Independent interpreter-to-held-result time for predeclared direct fit and development-matched BP."""
import argparse
import json
from pathlib import Path
import random
import subprocess
import sys
import time


def child(a):
    import numpy as np
    import torch
    sys.path.insert(0,str(a.data/'src'))
    from model import LanguageModel
    from train import Windows,evaluate
    from write import fit
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    schedule=json.loads((a.out/'terminal.json').read_bytes())['results'][str(a.seed)]
    dd=json.loads((a.out/'development.json').read_bytes())[str(a.seed)]['records'][0]
    # Freeze the first recorded BP checkpoint matching the preset analytic model
    # on development only. Rebuild exactly that number of updates in a new process.
    stepcount=next(x['steps'] for x in schedule['bp'] if x['valid']['nll']<=dd['validation']['nll'])
    torch.manual_seed(a.seed)
    trained=0
    start=time.perf_counter()
    if a.arm=='spectral':
        net,_=fit(LanguageModel,np.load(a.data/'train.npy'),33278,a.seed,16,.25)
        trained=len(np.load(a.data/'train.npy',mmap_mode='r'))-1
    else:
        tr=Windows(a.data/'train.npy');net=LanguageModel(33278,'hx')
        opt=torch.optim.AdamW(net.parameters(),lr=.003,weight_decay=.01,foreach=False)
        g=torch.Generator().manual_seed(a.seed+500)
        steps=0
        while steps<stepcount:
            for inds in torch.randperm(len(tr.x),generator=g).split(32):
                opt.zero_grad(set_to_none=True);loss=net.losses(tr.x[inds],tr.y[inds]);loss.mean().backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step();steps+=1;trained+=loss.numel()
                if steps==stepcount:break
    active=time.perf_counter()-start
    result=evaluate(net,Windows(a.data/'test.npy'),32,'cpu')
    print(json.dumps(dict(seed=a.seed,method=a.arm,processed_targets=trained,fit_s=active,
                          bp_steps=stepcount if a.arm=='bp' else 0,test=result)))


def parent(a):
    pairs=[(s,i) for s in (137,311,557) for i in range(3)]
    random.Random(226113).shuffle(pairs);rows=[]
    for n,(seed,rep) in enumerate(pairs):
        order=['spectral','bp'] if n%2 else ['bp','spectral']
        for arm in order:
            cmd=[sys.executable,__file__,str(a.data),str(a.out),'--arm',arm,'--seed',str(seed)]
            start=time.perf_counter();res=subprocess.run(cmd,text=True,capture_output=True,check=True)
            elapsed=time.perf_counter()-start
            row=json.loads(res.stdout);row.update(external_wall_s=elapsed,replicate=rep)
            rows.append(row);print(seed,rep,arm,round(elapsed,3),round(row['test']['ppl'],3),flush=True)
            temp=a.out/'cold.partial';temp.write_text(json.dumps(rows,indent=2)+'\n')
    temp.replace(a.out/'cold.json')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('out',type=Path)
    p.add_argument('--arm',choices=('spectral','bp'));p.add_argument('--seed',type=int)
    args=p.parse_args();child(args) if args.arm else parent(args)
