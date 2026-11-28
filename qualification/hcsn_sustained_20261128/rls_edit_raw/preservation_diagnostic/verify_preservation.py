"""NumPy replay of every development coefficient, its selected heads and all new held logits."""
import argparse
import os
from pathlib import Path
import numpy as np
from verify_release import read,write,sha,entry,calc,components,masks,normalized


def verify(root):
    d=root/'preservation_diagnostic';final=read(d/'terminal.json');seal=read(d/'development_seal.json')
    assert final['selection_sha256']==sha(d/'development_seal.json') and seal['mu']==final['mu']
    valid={str(mu):np.zeros((3,6),dtype=bool) for mu in (8,16,32,64,128,256,512)}
    maximum=0.;devnll=0.;weightmax=0.
    for si,s in enumerate((137,311,557)):
        with np.load(root/'run'/str(s)/'basis.npz') as b:
            x,tx,w0,y,ids,dev,dy=[b[k] for k in ('train','text','W0','train_y','train_ids','dev','dev_y')]
        sel=np.flatnonzero(y//6>=6);sel=sel[np.argsort(ids[sel],kind='stable')]
        i=np.random.default_rng(912731).choice(sel,128,replace=False);i=i[np.argsort(ids[i],kind='stable')]
        a=np.concatenate([tx,x[i]]).astype('d');w0=w0.astype('d');target=normalized(tx.astype('d')@w0)
        q0=calc(dev,tx,w0)
        with np.load(root/'run'/str(s)/'held.npz') as b:
            held,hy,hi=[b[k] for k in ('held','held_y','held_ids')]
        with np.load(d/f'held-{s}.npz') as hs,np.load(d/f'heads-{s}.npz') as heads:
            assert sha(d/f'heads-{s}.npz')==seal['weight_sha256'][str(s)] and sha(d/f'held-{s}.npz')==final['held_files'][str(s)]
            assert np.array_equal(hs['ids'],hi) and np.array_equal(hs['y'],hy)
            for j in range(6):
                m=y//6<=j;k=x[m].astype('d');v=np.linalg.norm(k@w0,axis=1,keepdims=True)*target[6*(y[m]//6)+(y[m]%6+1)%6]
                for mu in map(int,valid):
                    g=np.eye(96)+mu**2*a.T@a+k.T@k;rhs=w0+mu**2*a.T@(a@w0)+k.T@v
                    w=np.linalg.solve(g,rhs);z=calc(dev,tx,w);values=components(z,q0,dy,j);base=components(q0,q0,dy,j)
                    rs=seal['all_development'][str(mu)][str(s)][str(j)]
                    for group,mask in masks(dy,j).items():
                        if mask.any():devnll=max(devnll,abs(values['nll'][mask].mean()-rs['development'][group]['nll']))
                    diff={key:(base['nll'][mask]-values['nll'][mask]).mean() for key,mask in masks(dy,j).items() if mask.any()}
                    keep=masks(dy,j)['protected'];good=diff['current']>=.10 and (j==0 or diff['past']>=.05) and -diff['protected']<=.10 and (base['top1'][keep]-values['top1'][keep]).mean()<=.02
                    assert bool(good)==rs['pass'];valid[str(mu)][si,j]=good
                    if mu==final['mu']:
                        weightmax=max(weightmax,float(abs(w-heads[f'W{j}']).max()))
                        maximum=max(maximum,float(abs(calc(held,tx,heads[f'W{j}'])-hs[f'scores{j}']).max()))
    assert maximum<3e-5 and devnll<3e-5 and weightmax<2e-6
    def ranking(mu):
        a=valid[str(mu)];return (int(a.all()),int(a[:,-1].all()),int(a[:,-1].sum()),int(a.all(0).sum()),int(a.sum()),-mu)
    assert max(map(int,valid),key=ranking)==final['mu']
    release=root/'release_preservation';release.mkdir(exist_ok=True)
    check={'verified':True,'dev_candidates':126,'selected_held_heads':18,'mu':final['mu'],'max_abs_development_nll_difference':devnll,
           'max_abs_selected_weight_delta_against_cumulative_FP64':weightmax,'max_abs_held_score_delta':maximum}
    write(release/'verification.json',check)
    paths=[p for p in d.iterdir() if p.is_file()]+[root/'PRESERVATION_DIAGNOSTIC.md',root/'preservation_diagnostic.py',Path(__file__)]
    for p in paths:
        tgt=release/p.name
        if not tgt.exists():os.link(p,tgt)
        assert sha(tgt)==sha(p)
    objs={p.name:entry(p) for p in release.iterdir() if p.name!='manifest.json'}
    write(release/'manifest.json',{'verified':check,'terminal_sha256':sha(d/'terminal.json'),'objects':objs})
    print('verified preservation',check,sha(release/'manifest.json'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);verify(p.parse_args().root)
