"""Match same-core end-to-end fitting time to a freshly measured direct write."""
import argparse
import json
from pathlib import Path
import time

import torch
from write import Writer,LanguageModel,Windows,evaluate


def clock(root,seed):
    # Bootstrap common framework imports/backend before either measured arm.
    dummy=torch.nn.Linear(1,1);torch.optim.AdamW(dummy.parameters()).zero_grad()
    torch.manual_seed(71)
    with torch.no_grad():
        s=time.perf_counter();w=Writer(root,seed);sha=w.finish();budget=time.perf_counter()-s
    torch.manual_seed(seed)
    s=time.perf_counter()
    train=Windows(root/'train.npy');model=LanguageModel(33278,'hx')
    opt=torch.optim.AdamW(model.parameters(),lr=.003,weight_decay=.01,foreach=False)
    order=torch.Generator().manual_seed(seed+500)
    done=steps=0;elapsed=0.
    while elapsed<budget:
        idx=torch.randperm(len(train.x),generator=order)
        for lo in range(0,len(idx),32):
            i=idx[lo:lo+32];opt.zero_grad(set_to_none=True)
            losses=model.losses(train.x[i],train.y[i]);losses.mean().backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.);opt.step()
            steps+=1;done+=losses.numel();elapsed=time.perf_counter()-s
            if elapsed>=budget:break
    held={k:evaluate(model,Windows(root/(k+'.npy')),32,'cpu') for k in ('valid','test')}
    p=root/'direct'/f'direct-{seed}-init71.json';checks=json.loads(p.read_text())
    if sha!=checks['state_hash']:raise ArithmeticError('Repeated direct fit changed weights')
    return dict(seed=seed,direct_seconds=budget,direct_state_sha256=sha,direct_test=checks['scores']['test'],
                bp_seconds=elapsed,bp_train_targets=done,bp_steps=steps,bp_scores=held)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);z=p.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    rows=[clock(z.root,seed) for seed in (137,311,557)]
    (z.root/'direct'/'matched_clock.json').write_text(json.dumps(rows,indent=2)+'\n')
