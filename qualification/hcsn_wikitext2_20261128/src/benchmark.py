"""Same-core interleaved optimizer-update timing with a fixed training batch."""
import argparse
import json
from pathlib import Path
import statistics
import time

import torch
from model import LanguageModel
from train import Windows


def run(root,steps):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    torch.manual_seed(7181)
    data=Windows(root/'train.npy')
    idx=torch.randperm(len(data.x))[:32]
    x,y=data.x[idx],data.y[idx]
    rows={}
    kinds=['hx','sdpa','smooth','lif']
    pairs={}
    for k in kinds:
        m=LanguageModel(33278,k)
        pairs[k]=(m,torch.optim.AdamW(m.parameters(),lr=.003,weight_decay=.01,foreach=False))
        rows[k]=[]
    def update(m,opt):
        opt.zero_grad(set_to_none=True)
        nll=m.losses(x,y).mean();nll.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(),1.);opt.step()
    for m,opt in pairs.values():
        for _ in range(4):update(m,opt)
    for it in range(8):
        # Balanced order over two full rotations, alternating direction.
        order=kinds[it%4:]+kinds[:it%4]
        if it>=4:order=order[::-1]
        for k in order:
            st=time.perf_counter();ct=time.process_time()
            for _ in range(steps):update(*pairs[k])
            rows[k].append(dict(seconds=time.perf_counter()-st,cpu_seconds=time.process_time()-ct))
    return dict(torch=str(torch.__version__),threads=1,tokens_per_round=32*128*steps,rounds=8,
                device='one pinned CPU core',rows=rows,
                median_tok_s={k:32*128*steps/statistics.median([q['seconds'] for q in v]) for k,v in rows.items()})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--steps',type=int,default=8)
    z=p.parse_args();print(json.dumps(run(z.root,z.steps),indent=2))
