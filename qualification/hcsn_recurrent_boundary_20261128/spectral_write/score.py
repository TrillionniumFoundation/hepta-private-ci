"""Evaluate sealed deployments and measure the time for ordinary BP on the same CPU."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import torch


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_model(cls, root, row):
    file = root/(row['tag']+'.npz')
    if checksum(file) != row['sha256']:
        raise ValueError(file)
    model = cls(33278,'hx')
    with np.load(file) as arr:
        model.load_state_dict({k:torch.from_numpy(v) for k,v in arr.items()})
    return model.eval()


@torch.inference_mode()
def per_word(model, windows, cut=False):
    scores = []
    for a,b in zip(windows.x.split(32),windows.y.split(32)):
        scores.append(model.losses(a,b,cut=cut).numpy().astype(np.float32,copy=False))
    arrays = np.concatenate(scores)
    if len(arrays) != windows.count or not np.isfinite(arrays).all():
        raise ValueError('incomplete corpus score')
    return arrays


def summarize(scores):
    nll = float(scores.mean(dtype=np.float64))
    return dict(targets=len(scores),nll=nll,ppl=math.exp(nll))


def bp_path(cls, windows, evaluate, root, output, seed, records, chosen):
    # All checkpoints are frozen on cumulative model fitting time, excluding
    # named validation, checkpoint I/O and the terminal held scoring.
    fixed = records[0]
    cumulative_search = sum(r['wall_s']+r['validation_s'] for r in records)
    schedule = sorted(set([fixed['wall_s'],chosen['wall_s'],cumulative_search,4.,8.,16.,32.,64.]))
    torch.manual_seed(seed)
    clock=time.perf_counter()
    model=cls(33278,'hx')
    data=windows(root/'train.npy')
    optimizer=torch.optim.AdamW(model.parameters(),lr=.003,weight_decay=.01,foreach=False)
    active=time.perf_counter()-clock
    validation=windows(root/'valid.npy')
    held=windows(root/'test.npy')
    generator=torch.Generator().manual_seed(seed+500)
    steps=tokens=0
    frozen=[]
    while schedule:
        for ii in torch.randperm(len(data.x),generator=generator).split(32):
            start=time.perf_counter()
            optimizer.zero_grad(set_to_none=True)
            loss=model.losses(data.x[ii],data.y[ii])
            loss.mean().backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            optimizer.step()
            active+=time.perf_counter()-start
            steps+=1
            tokens+=loss.numel()
            if active >= schedule[0]:
                labels=[]
                while schedule and active>=schedule[0]:
                    labels.append(schedule.pop(0))
                state={k:v.detach().clone() for k,v in model.state_dict().items()}
                dv=evaluate(model,validation,32,'cpu')
                frozen.append((dict(budgets=labels,steps=steps,targets=tokens,training_wall_s=active,valid=dv), state))
            if not schedule:break
    # Only after every validation endpoint exists, read the held labels.
    out=[]
    for i,(row,state) in enumerate(frozen):
        model.load_state_dict(state)
        scores=per_word(model,held)
        file=output/f'bp-{seed}-{i}-original.npz'
        np.savez_compressed(file, per_word_nll=scores)
        row.update(test=summarize(scores),sealed_per_word_sha256=checksum(file))
        out.append(row)
    return out


def main(args):
    sys.path.insert(0,str(args.data/'src'))
    from model import LanguageModel
    from train import evaluate, Windows
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.optim.AdamW(torch.nn.Linear(1,1).parameters()).zero_grad()
    devpath=args.out/'development.json'
    seal=checksum(devpath)
    study=json.loads(devpath.read_bytes())
    held=Windows(args.data/'test.npy')
    results={}
    for seed in (137,311,557):
        ss=study[str(seed)]
        chosen=next(row for row in ss['records'] if row['tag']==ss['chosen'])
        fixed=ss['records'][0]
        fits={}
        for r in {row['tag']:row for row in [fixed,chosen]}.values():
            model=load_model(LanguageModel,args.out,r)
            scores={'normal':per_word(model,held),'cut':per_word(model,held,cut=True)}
            nohist=copy.deepcopy(model)
            with torch.no_grad():
                for b in nohist.blocks:b.qkv.weight[32:64].zero_()
            scores['without_history']=per_word(nohist,held)
            nofeedback=copy.deepcopy(model)
            with torch.no_grad():
                for b in nofeedback.blocks:b.out.weight.zero_();b.out.bias.zero_()
            scores['without_feedback']=per_word(nofeedback,held)
            f=args.out/(r['tag']+'-original-test.npz')
            np.savez_compressed(f, **scores)
            # Paired resampling unit is a contiguous block of 128 adjacent targets.
            unit=128
            rng=np.random.default_rng(173311)
            lengths=np.diff(np.r_[np.arange(0,held.count,unit),held.count])
            contrasts={}
            for key in scores:
                if key=='normal':continue
                diff=np.add.reduceat(scores[key].astype(float)-scores['normal'],np.arange(0,held.count,unit))
                means=[]
                for _ in range(50):
                    idx=rng.integers(0,len(diff),(100,len(diff)))
                    means.extend((diff[idx].sum(1)/lengths[idx].sum(1)).tolist())
                contrasts[key]={'nll_difference':float(diff.sum()/lengths.sum()),'block_bootstrap_95':np.quantile(means,[.025,.975]).tolist()}
            fits[r['tag']]=dict(scores={k:summarize(val) for k,val in scores.items()},intervention_contrasts=contrasts,
                                 file=f.name,sha256=checksum(f))
            print(r['tag'],fits[r['tag']]['scores']['normal'],flush=True)
        bp=bp_path(LanguageModel,Windows,evaluate,args.data,args.out,seed,ss['records'],chosen)
        results[str(seed)]=dict(chosen=ss['chosen'],fixed=fixed['tag'],fits=fits,bp=bp)
        (args.out/f'held-seed-{seed}.json').write_text(json.dumps(results[str(seed)],indent=2)+'\n')
        print('bp',seed,[(round(v['training_wall_s'],2),round(v['test']['ppl'],2)) for v in bp],flush=True)
    if checksum(devpath)!=seal:raise ValueError('development seal changed')
    (args.out/'terminal.json').write_text(json.dumps(dict(development_sha256=seal,results=results),indent=2)+'\n')


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('data',type=Path)
    ap.add_argument('out',type=Path)
    main(ap.parse_args())
