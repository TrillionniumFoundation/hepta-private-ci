"""Open the held split only after all development selections and compute photo-paired evidence."""
import argparse
from pathlib import Path
import json
import time

import numpy as np
import torch

from decoder import Corpus, KINDS, architecture, greedy
from train_threeway import SEEDS, assessed, atomic_json, hashfile


def different_photo(data,ids):
    photos=np.unique(data.photo[ids])
    if len(photos)<2:raise ValueError('require two photos')
    next_photo=dict(zip(photos,np.roll(photos,len(photos)//2)))
    matches={(data.photo[i],data.caption[i]):i for i in ids}
    default={data.photo[i]:i for i in ids}
    other=np.array([matches.get((next_photo[data.photo[i]],data.caption[i]),default[next_photo[data.photo[i]]])
                    for i in ids])
    if np.any(data.photo[other]==data.photo[ids]):raise ArithmeticError('shared photo')
    return other


def first_end(seq):
    word=list(map(int,seq));return word[:word.index(1)] if 1 in word else word


def edits(a,b):
    # Reuse one row of the word-level Levenshtein recursion.
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):current.append(min(prev[j]+1,current[-1]+1,prev[j-1]+(x!=y)))
        prev=current
    return prev[-1]


@torch.inference_mode()
def generate(model,data,held):
    values=[]
    for m in range(3):
        pred=np.concatenate([greedy(model,data,held[i:i+48],m).cpu().numpy() for i in range(0,len(held),48)])
        expected=data.modalities[m][held].cpu().numpy()
        if m<2:
            summary=dict(code_accuracy=float(np.mean(pred==expected)),
                         sequence_exact=float(np.mean((pred==expected).all(1))))
        else:
            truth=[first_end(s[s>=0]) for s in expected]
            guesses=[first_end(s) for s in pred]
            errors=sum(edits(a,b) for a,b in zip(truth,guesses))
            summary=dict(exact=float(np.mean([a==b for a,b in zip(truth,guesses)])),
                         word_error_rate=errors/sum(map(len,truth)),
                         capped_fraction=float(np.mean(~(pred==1).any(1))))
        values.append((pred,summary))
    return values


def original(model,data,held,permuted,run,tag,interventions):
    score={}
    modes=['normal','cut','wrong'] if interventions else ['normal']
    for arm in modes:
        full=[assessed(model,data,held,m,permuted if arm=='wrong' else None,cut=(arm=='cut')) for m in range(3)]
        score[arm]=np.stack([v[0] for v in full],axis=1)
        score['count']=np.stack([v[1] for v in full],axis=1)
    counts=score['count'].sum(0)
    row={k:(score[k].sum(0)/counts).tolist() for k in modes}
    if interventions:
        generated=generate(model,data,held)
        row['sequences']=[x[1] for x in generated]
        for m,(values,_) in enumerate(generated):score[f'greedy_{m}']=values.astype(np.int16)
    p=run/(tag+'-held.npz');tmp=p.with_suffix('.stage')
    with tmp.open('wb') as f:np.savez_compressed(f,**score,held=held,photo=data.photo[held])
    tmp.replace(p)
    return dict(scores=row,path=p.name,sha256=hashfile(p))


def summarize(data,held,panel,cells,run):
    photos,group=np.unique(data.photo[held],return_inverse=True)
    fits={}
    for label in ['selected','epoch1','epoch3','time600']:
        contrast={}
        for opponent in ('smooth','lif','sdpa'):
            numerator=[];denominator=None
            for seed in SEEDS:
                arms=[]
                for k in ('financial',opponent):
                    name=f'{k}-{seed}';rung=panel[name]['chosen'] if label=='selected' else label
                    f=run/cells[name][rung]['path']
                    with np.load(f) as z:
                        arms.append(z['normal']);counts=z['count']
                dif=arms[0]-arms[1]
                num=np.zeros((len(photos),3));np.add.at(num,group,dif);numerator.append(num)
                denominator=np.zeros_like(num);np.add.at(denominator,group,counts)
            actual=np.mean(numerator,0).sum(0)/denominator.sum(0)
            rng=np.random.default_rng(913715)
            samples=[]
            for _ in range(60):
                a=rng.multinomial(len(photos),np.full(len(photos),1/len(photos)),size=100)
                s=rng.multinomial(3,np.full(3,1/3),size=100)/3.
                samples.extend(np.einsum('bs,bp,spm->bm',s,a,numerator,optimize=True)/(a@denominator))
            contrast[opponent]=(actual,np.asarray(samples))
        series=np.concatenate([v[0] for v in contrast.values()])
        draws=np.concatenate([v[1] for v in contrast.values()],axis=1)
        sd=np.maximum(1e-15,draws.std(0,ddof=1))
        critical=np.quantile(np.max(np.abs(draws-series)/sd,axis=1),.95)
        intervals=np.stack((series-critical*sd,series+critical*sd),axis=-1)
        fits[label]={'order':list(contrast),'nll_financial_minus_comparator':series.reshape(3,3).tolist(),
                     'simultaneous_95':intervals.reshape(3,3,2).tolist(),'replicates':len(draws)}
    return fits


def main(a):
    if a.wait:
        while not (a.run/'sealed-development.json').exists():time.sleep(30)
    receipt=a.run/'sealed-development.json';seal=hashfile(receipt);panel=json.loads(receipt.read_text())['panel']
    names={f'{k}-{s}' for k in KINDS for s in SEEDS}
    if set(panel)!=names or any(set(p['all'])!={'time600','epoch1','epoch3'} for p in panel.values()):
        raise ValueError('unsealed joint panel')
    torch.set_num_threads(1)
    data=Corpus(a.data/'codes.npz',a.device);vocab=json.loads((a.data/'dataset.json').read_text())['vocabulary']
    held=np.flatnonzero(data.split==2);wrong=different_photo(data,held);cells={}
    for name,row in panel.items():
        done=a.run/(name+'-held.json')
        if done.exists():
            old=json.loads(done.read_text())
            if old['dev_seal']!=seal:raise RuntimeError('stale held result')
            for r in old['rows'].values():
                if hashfile(a.run/r['path'])!=r['sha256']:raise RuntimeError('stored held result corruption')
            cells[name]=old['rows'];continue
        cell=architecture(len(vocab),row['arm'],row['seed']).to(a.device).eval()
        rows={}
        for label,spec in row['all'].items():
            f=a.run/spec['weights']
            if hashfile(f)!=spec['weights_sha256']:raise ValueError(f)
            with np.load(f) as z:cell.load_state_dict({k:torch.from_numpy(v) for k,v in z.items()})
            rows[label]=original(cell,data,held,wrong,a.run,name+'-'+label,label==row['chosen'])
            print(name,label,rows[label]['scores']['normal'],flush=True)
        atomic_json(done,dict(dev_seal=seal,rows=rows))
        cells[name]=rows
    if hashfile(receipt)!=seal:raise ArithmeticError('development changed')
    contrasts=summarize(data,held,panel,cells,a.run)
    atomic_json(a.run/'terminal.json',dict(utc=time.time(),dev_seal=seal,held_photos=len(np.unique(data.photo[held])),
                    held_captions=len(held),cells=cells,contrasts=contrasts))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('run',type=Path)
    p.add_argument('--device',choices=('cuda','cpu'),required=True);p.add_argument('--wait',action='store_true')
    main(p.parse_args())
