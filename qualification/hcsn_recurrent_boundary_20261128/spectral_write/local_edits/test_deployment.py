"""Test only development-frozen local probability fits and train BP through the same measured budgets."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score import per_word, summarize
from verify import forward


def original_fit(cls,record,out,test,xx,yy):
    file=out/(record['tag']+'.npz')
    if sha256(file.read_bytes()).hexdigest()!=record['sha256']:raise ArithmeticError('wrong weights')
    model=cls(33278,'hx').eval()
    with np.load(file) as arr:
        model.load_state_dict({k:torch.from_numpy(v) for k,v in arr.items()})
        w={k:v.astype(float) for k,v in arr.items()}
    fp=per_word(model,test);cut=per_word(model,test,cut=True)
    with torch.no_grad():
        for layer in model.blocks:
            layer.out.weight.zero_();layer.out.bias.zero_()
    off=per_word(model,test)
    ref=np.concatenate([forward(w,xx[i:i+8],yy[i:i+8]) for i in range(0,len(xx),8)])
    peak=float(np.max(np.abs(ref-fp)))
    if peak>2e-4:raise ArithmeticError((record['tag'],peak))
    scorefile=out/(record['tag']+'-original.npz')
    np.savez_compressed(scorefile,nll=fp,cut=cut,without_feedback=off)
    return dict(normal=summarize(fp),cut=summarize(cut),without_feedback=summarize(off),
                maximum_numpy_error=peak,mean_numpy_error=float(np.mean(ref-fp)),
                score_sha256=sha256(scorefile.read_bytes()).hexdigest())


def compare(cls,windows,root,out,seed,settings):
    target_times=sorted(set(settings.values()));torch.manual_seed(seed);tic=time.perf_counter()
    model=cls(33278,'hx');train=windows(root/'train.npy')
    opt=torch.optim.AdamW(model.parameters(),lr=.003,weight_decay=.01,foreach=False)
    g=torch.Generator().manual_seed(seed+500);active=time.perf_counter()-tic
    processed=steps=0;frozen=[]
    while target_times:
        for idx in torch.randperm(len(train.x),generator=g).split(32):
            t=time.perf_counter()
            opt.zero_grad(set_to_none=True);loss=model.losses(train.x[idx],train.y[idx]);loss.mean().backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.);opt.step()
            active+=time.perf_counter()-t;steps+=1;processed+=loss.numel()
            if active>=target_times[0]:
                labels=[]
                while target_times and active>=target_times[0]:
                    limit=target_times.pop(0);labels.extend(k for k,v in settings.items() if v==limit)
                frozen.append((dict(labels=labels,elapsed_s=active,steps=steps,train_words=processed),
                               {k:v.detach().clone() for k,v in model.state_dict().items()}))
            if not target_times:break
    rows=[];va=windows(root/'valid.npy');te=windows(root/'test.npy')
    for i,(row,state) in enumerate(frozen):
        model.load_state_dict(state)
        valid=per_word(model,va);scores=per_word(model,te)
        file=out/f'bp-{seed}-{i}-original.npz';np.savez_compressed(file,valid=valid,test=scores)
        rows.append(dict(**row,valid=summarize(valid),test=summarize(scores),sha256=sha256(file.read_bytes()).hexdigest()))
    return rows


def main(a):
    sys.path.insert(0,str(a.data/'src'))
    from model import LanguageModel
    from train import Windows
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if a.wait:
        while not (a.out/'seal.json').exists():time.sleep(15)
    torch.optim.AdamW(torch.nn.Linear(1,1).parameters()).zero_grad()
    seal=json.loads((a.out/'seal.json').read_bytes())
    if set(seal)!={'137','311','557'}:raise ArithmeticError('development seal incomplete')
    selections={}
    for k,h in seal.items():
        p=a.out/f'dev-{k}.json';raw=p.read_bytes()
        if sha256(raw).hexdigest()!=h:raise ArithmeticError('changed development result')
        selections[k]=json.loads(raw)
    test=Windows(a.data/'test.npy');x=test.x.numpy();y=test.y.numpy();result={}
    for sk,dev in selections.items():
        seed=int(sk);selected=dev['chosen'];fixed=f'local-{seed}-4-4';chosen={}
        for row in dev['all']:
            if row['tag'] in {fixed,selected}:
                chosen[row['tag']]=dict(fit_s=row['cumulative_fit_s'],**original_fit(LanguageModel,row,a.out,test,x,y))
        settings={'default_fit':chosen[fixed]['fit_s'],'selected_fit':chosen[selected]['fit_s'],
                  'full_development_search':dev['total_fit_and_selection_wall_s']}
        bp=compare(LanguageModel,Windows,a.data,a.out,seed,settings)
        result[sk]=dict(selected=selected,default=fixed,deployed=chosen,bp=bp)
        print(seed,{k:round(v['normal']['ppl'],3) for k,v in chosen.items()},
              [(v['labels'],round(v['test']['ppl'],3)) for v in bp],flush=True)
        (a.out/f'test-{seed}.json').write_text(json.dumps(result[sk],indent=2)+'\n')
    (a.out/'terminal.json').write_text(json.dumps(dict(seal=seal,seeds=result),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('out',type=Path);p.add_argument('--wait',action='store_true')
    main(p.parse_args())
