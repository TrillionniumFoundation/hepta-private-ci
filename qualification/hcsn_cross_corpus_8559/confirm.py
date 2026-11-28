"""Seal source selections before transmitting test pixels or captions to a trained model."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ARMS=['literal','smooth','sdpa']
SEEDS=[371,719,1123]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(work):
    assert not (work/'cold').exists()
    items=[]
    for a in ARMS:
        for seed in SEEDS:
            base=work/'fits'/f'{a}-{seed}';d=json.loads((base/'selected.json').read_text())
            assert len(d['rungs'])==3
            for r in d['rungs']:assert sha(base/f"{r['step']}.pt")==r['sha256']
            items.append(d)
    c=json.loads((work/'linear.json').read_text());assert sha(work/'linear.npz')==c['sha256']
    out=dict(neural=items,linear=c,input=sha(work/'input.npz'),code={p.name:sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))})
    p=work/'seal.json'
    with p.open('x') as f:json.dump(out,f,indent=2)
    return p


def shuffled(g):
    rng=np.random.default_rng(8713);p=rng.permutation(len(g))
    for k in range(len(g)):
        if g[p[k]]==g[k]:
            possible=np.flatnonzero((g[p]!=g[k]) & (g!=g[p[k]]))
            j=int(rng.choice(possible));p[k],p[j]=p[j],p[k]
    assert np.all(g[p]!=g)
    return p


def cold(work,law,arm,seed,step):
    from score import score_embeddings
    from linear import project
    start=time.perf_counter()
    s=json.loads((work/'seal.json').read_text());assert sha(work/'input.npz')==s['input']
    out=work/'cold';out.mkdir(exist_ok=True)
    dest=out/f'{arm}-{seed}-{step}'
    if arm=='linear':
        checkpoint=work/'linear.npz';assert sha(checkpoint)==s['linear']['sha256']
        model=np.load(checkpoint)
    else:
        import torch
        from network import Encoder
        from fit import embed
        torch.set_num_threads(1)
        checkpoint=work/'fits'/f'{arm}-{seed}'/f'{step}.pt'
        desc=next(v for v in s['neural'] if (v['arm'],v['seed'])==(arm,seed))
        assert sha(checkpoint)==next(v for v in desc['rungs'] if v['step']==step)['sha256']
    with np.load(work/'input.npz') as d:
        pix=d['images'];tok=d['tokens'];groups=d['groups'];split=d['split'];vocab=int(d['vocab']);names=d['names']
    if arm!='linear':
        model=Encoder(arm,seed,vocab,law)
        model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True))
        pix=torch.from_numpy(pix);tok=torch.from_numpy(tok.astype(np.int64))
    reports={};data={}
    for gallery,ix in [('rsicd',np.flatnonzero(split==2)),('ucm',np.flatnonzero(split==3))]:
        t0=time.perf_counter()
        im,tx=(project(model,pix[ix],tok[ix,0]) if arm=='linear' else embed(model,pix,tok,ix))
        g=groups[ix,0];perm=shuffled(g)
        # Replacing every modality input by the same observed input makes its encoded output constant.
        # Broadcast an actual observed encoded value. The two towers do not share an input-dependent operation.
        options={'pair':(im,tx),'shuffle':(im[perm],tx),
                 'image_constant':(np.broadcast_to(im[:1],im.shape).copy(),tx),
                 'text_constant':(im,np.broadcast_to(tx[:1],tx.shape).copy())}
        for mode,(a,b) in options.items():
            values=score_embeddings(a,b,g)
            data[f'{gallery}_{mode}']=values
        data[f'{gallery}_image']=im;data[f'{gallery}_text']=tx;data[f'{gallery}_group']=g;data[f'{gallery}_id']=names[ix]
        reports[gallery]={'n':len(ix),'unique_primary':len(set(g.tolist())),
                          'primary':data[f'{gallery}_pair'][:,:,0].mean().item(),
                          'wall_s':time.perf_counter()-t0}
    np.savez_compressed(dest.with_suffix('.npz'),**data)
    rec=dict(galleries=reports,elapsed_s=time.perf_counter()-start,file_sha256=sha(dest.with_suffix('.npz')))
    dest.with_suffix('.json').write_text(json.dumps(rec,indent=2)+'\n')


def driver(work,law):
    if not (work/'seal.json').exists():seal(work)
    s=json.loads((work/'seal.json').read_text());receipts=[]
    for a,seed,step in [('linear',0,0)]+[(row['arm'],row['seed'],r['step']) for row in s['neural'] for r in row['rungs']]:
        n=f'{a}-{seed}-{step}';t=time.perf_counter();p=work/'cold'/f'{n}.process.json'
        if p.exists():
            assert (work/'cold'/f'{n}.npz').is_file();continue
        cmd=[sys.executable,__file__,str(work),str(law),'--one',a,str(seed),str(step)]
        subprocess.run(cmd,check=True);wall=time.perf_counter()-t
        p.write_text(json.dumps({'cold_process_wall_s':wall,'arm':a,'seed':seed,'step':step})+'\n')
        print(n,round(wall,2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);p.add_argument('law',type=Path);p.add_argument('--one',nargs=3);p.add_argument('--seal-only',action='store_true');a=p.parse_args()
    if a.seal_only:print(sha(seal(a.work)))
    elif a.one:cold(a.work,a.law,a.one[0],int(a.one[1]),int(a.one[2]))
    else:driver(a.work,a.law)
