"""Measure BP's training-time bracket for the direct writer's official validation NLL."""
import argparse
import json
from pathlib import Path
import time
import torch
from write import LanguageModel,Windows,evaluate


def run(root,seed):
    ref=json.loads((root/'direct'/f'direct-{seed}-init71.json').read_text())
    target=ref['scores']['valid']['nll']
    train,valid,test=[Windows(root/(key+'.npy')) for key in ('train','valid','test')]
    torch.manual_seed(seed)
    start=time.perf_counter()
    m=LanguageModel(33278,'hx');opt=torch.optim.AdamW(m.parameters(),lr=.003,weight_decay=.01,foreach=False)
    elapsed=time.perf_counter()-start
    order=torch.Generator().manual_seed(seed+500);epochs=0;steps=0;tokens=0;history=[]
    while epochs<2:
        ids=torch.randperm(len(train.x),generator=order);epochs+=1
        for lo in range(0,len(ids),32):
            i=ids[lo:lo+32];s=time.perf_counter()
            m.train();opt.zero_grad(set_to_none=True)
            loss=m.losses(train.x[i],train.y[i]);loss.mean().backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(),1.);opt.step()
            elapsed+=time.perf_counter()-s;steps+=1;tokens+=loss.numel()
            if steps%16:continue
            score=evaluate(m,valid,32,'cpu')
            history.append(dict(step=steps,tokens=tokens,train_seconds=elapsed,valid_nll=score['nll']))
            if score['nll']<=target:
                return dict(seed=seed,target_valid_nll=target,direct_train_seconds=ref['training_seconds'],
                            first_observed_crossing=history[-1],last_above=history[-2] if len(history)>1 else None,
                            test=evaluate(m,test,32,'cpu'),history=history)
    raise ArithmeticError('No observed target crossing in two complete passes')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    dummy=torch.nn.Linear(1,1);torch.optim.AdamW(dummy.parameters()).zero_grad()
    result=[run(a.root,s) for s in (137,311,557)]
    (a.root/'direct'/'target_time.json').write_text(json.dumps(result,indent=2)+'\n')
