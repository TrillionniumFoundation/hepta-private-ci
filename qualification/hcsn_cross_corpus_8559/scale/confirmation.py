"""Seal every source-only checkpoint, then evaluate verified immutable weights in cold processes."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from confirm import shuffled
from hard_pairs import neighbors,eval_pairs
from linear import project
from score import metrics

CLOCK=(30,120,600,2100,4200)
SEEDS=(2039,4729,8047)
ARMS=('literal','smooth','lif','sdpa')
GALLERIES=('rs_test','nw_test','ucm','sydney')
MODES=('pair','shuffle','image_constant','text_constant')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def write(path,doc):
    temp=path.with_suffix(path.suffix+'.part')
    temp.write_text(json.dumps(doc,indent=2)+'\n')
    os.replace(temp,path)


def seal(work,law):
    if (work/'seal.json').exists():return
    assert not (work/'cold').exists()
    data=read(work/'data'/'data.json')
    for n,v in data['arrays'].items():assert sha(work/'data'/n)==v,n
    models=[]
    for arm in ARMS:
        for seed in SEEDS:
            base=work/'fits'/f'{arm}-{seed}';selected=read(base/'selected.json');ledger=selected['ledger']
            assert ledger['clock_done']==list(CLOCK) and ledger['events'][-1]['budgets']==[4200]
            assert [x['step'] for x in ledger['events']]==sorted(set(x['step'] for x in ledger['events']))
            for row in ledger['events']:
                assert sha(base/f"s{row['step']}.pt")==row['sha256']
            assert selected['best']==max(ledger['events'],key=lambda r:r['dev_mean'])
            by_clock={}
            for b in CLOCK:
                i=next(j for j,row in enumerate(ledger['events']) if b in row['budgets'])
                by_clock[str(b)]=max(ledger['events'][:i+1],key=lambda r:r['dev_mean'])['step']
            models.append(dict(arm=arm,seed=seed,n_param=selected['n_param'],events=ledger['events'],by_clock=by_clock,selected=selected['best']['step'],training_ledger_tail={k:v for k,v in ledger.items() if k!='events'}))
    linear=read(work/'linear.json');assert sha(work/'linear.npz')==linear['sha256']
    paths=[*HERE.glob('*.py'),*[HERE.parent/x for x in ('population_mixer.py','linear.py','score.py','hard_pairs.py','confirm.py','report.py')]]
    sources={str(p.relative_to(HERE.parent)):sha(p) for p in paths}
    write(work/'seal.json',dict(data=data,law=sha(law),linear=linear,models=models,sources=sources,sealed_unix=time.time()))


def evaluate(work,law,arm,seed,step):
    from train import arrays
    seal_doc=read(work/'seal.json')
    assert sha(law)==seal_doc['law']
    selected=arm=='linear'
    if arm=='linear':
        assert (seed,step)==(0,0);path=work/'linear.npz'
        assert sha(path)==seal_doc['linear']['sha256'];model=np.load(path)
    else:
        import torch
        from encoder import Encoder
        from train import encoded
        torch.set_num_threads(1)
        rec=next(r for r in seal_doc['models'] if (r['arm'],r['seed'])==(arm,seed))
        event=next(r for r in rec['events'] if r['step']==step)
        selected=step==rec['selected'];path=work/'fits'/f'{arm}-{seed}'/f's{step}.pt'
        assert sha(path)==event['sha256']
        model=Encoder(arm,seed,seal_doc['data']['vocab'],law)
        model.load_state_dict(torch.load(path,map_location='cpu',weights_only=True))
    d=arrays(work/'data');items={};receipt={};base=work/'cold'/f'{arm}-{seed}-{step}'
    for name in GALLERIES:
        t=time.perf_counter();ix=np.flatnonzero(d['splits']==name);groups=d['groups'][ix,0]
        if arm=='linear':
            vectors=[project(model,d['pixels'][j],d['tokens'][j,0]) for j in np.array_split(ix,(len(ix)+255)//256)]
            im,txt=(np.concatenate(x) for x in zip(*vectors))
        else:
            im,txt=encoded(model,d,ix)
        # Reuse detached unimodal embeddings for score-space negative interventions.
        sim=im@txt.T;perm=shuffled(groups)
        for mode,mat in [('pair',sim),('shuffle',sim[perm]),('image_constant',np.broadcast_to(sim[:1],sim.shape)),('text_constant',np.broadcast_to(sim[:,:1],sim.shape))]:
            items[f'{name}_{mode}']=metrics(mat,groups).astype(np.float32)
        if selected:
            peers=np.load(work/'cold'/f'{name}-peers.npy',allow_pickle=False)
            items[f'{name}_hard']=eval_pairs(im,txt,peers).astype(np.float32)
        items[f'{name}_group']=groups;items[f'{name}_id']=d['ids'][ix]
        items[f'{name}_image']=im;items[f'{name}_text']=txt
        receipt[name]=dict(n=len(ix),unique_primary=len(np.unique(groups)),concordance=float(items[f'{name}_pair'][:,:,0].mean()),elapsed_s=time.perf_counter()-t)
    with base.with_suffix('.npz.part').open('wb') as f:np.savez_compressed(f,**items)
    os.replace(base.with_suffix('.npz.part'),base.with_suffix('.npz'))
    write(base.with_suffix('.json'),dict(trial=[arm,seed,step],selected=selected,galleries=receipt,sha256=sha(base.with_suffix('.npz'))))


def confirm(work,law):
    assert (work/'seal.json').is_file()
    from train import arrays
    c=work/'cold';c.mkdir(exist_ok=True)
    with (work/'confirmation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        d=arrays(work/'data');ss=read(work/'seal.json')
        for n,v in ss['data']['arrays'].items():assert sha(work/'data'/n)==v
        for name in GALLERIES:
            p=c/f'{name}-peers.npy'
            if not p.exists():
                ix=np.flatnonzero(d['splits']==name)
                with p.with_suffix('.npy.part').open('wb') as f:np.save(f,neighbors(d['tokens'][ix,0],d['groups'][ix,0],d['ids'][ix]))
                os.replace(p.with_suffix('.npy.part'),p)
        jobs=[('linear',0,0)]+[(row['arm'],row['seed'],e['step']) for row in ss['models'] for e in row['events']]
        for arm,seed,step in jobs:
            base=c/f'{arm}-{seed}-{step}';rp=base.with_suffix('.process.json')
            if rp.exists():
                assert sha(base.with_suffix('.npz'))==read(base.with_suffix('.json'))['sha256']
                continue
            t=time.perf_counter()
            subprocess.run([sys.executable,str(HERE/'confirmation.py'),str(work),str(law),'--one',arm,str(seed),str(step)],check=True)
            write(rp,dict(wall_s=time.perf_counter()-t,arm=arm,seed=seed,step=step))
            print('confirmed',arm,seed,step,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);p.add_argument('law',type=Path)
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--seal',action='store_true');mode.add_argument('--confirm',action='store_true');mode.add_argument('--one',nargs=3)
    a=p.parse_args()
    if a.seal:seal(a.work,a.law)
    elif a.confirm:confirm(a.work,a.law)
    else:evaluate(a.work,a.law,a.one[0],int(a.one[1]),int(a.one[2]))
