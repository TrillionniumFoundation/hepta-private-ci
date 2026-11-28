"""Distill a strong generic acoustic teacher into two native hidden matrices using true unlabeled speech."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fit_model import Cell,Expired,Track,balanced,clock,dump,fields,forward,load_panel,sha,since,standardized,stats
from model import grad
from sensitivity import released_update
from named import named_fit


ARMS=('teacher_lm','teacher_bp','receiver_teacher','frozen_aux','scrambled_teacher','alpha','alpha_exact','crisp')


def bp(track,x,y):
    rates=(.003,.015,.05);pool=[]
    for lr in rates:
        mat=[z.copy() for z in track.original]
        pool.append((lr,mat,[(np.zeros_like(z),np.zeros_like(z)) for z in mat],np.random.default_rng(track.seed+8559)))
    iteration=0;n=len(x)//3
    while True:
        iteration+=1
        for lr,m,mom,rng in pool:
            track.check()
            ix=np.concatenate([q*n+rng.choice(n,16,replace=False) for q in range(3)])
            gs=grad(x[ix],m,track.p,track.law,y[ix])
            for w,g,(a,b) in zip(m,gs,mom):
                a*=.9;a+=.1*g;b*=.999;b+=.001*g*g
                w-=lr*(a/(1-.9**iteration))/(np.sqrt(b/(1-.999**iteration))+1e-8)
            if iteration==1 or iteration%4==0:track.consider(m,dict(iteration=iteration,lr=lr))


def main(a):
    root=a.source/f'{a.arch}_{a.seed}';out=a.out/f'{a.arch}_{a.seed}';out.mkdir(parents=True,exist_ok=True)
    if (out/(a.arm+'.json')).exists():return
    tick=clock();p=fields(root/'parent.npz');base=[p['encoder'],p['W']]
    law=Cell(a.law if a.arch=='literal' else root/'smooth.npz')
    teacher=fields(root/'ridge_3.npz')
    raw=fields(a.original/'new_cal.npz');nc=balanced(raw,17319);oc=balanced(fields(a.original/'old_cal.npz'),17319)
    new=standardized(nc['x'],p);old=standardized(oc['x'],p)
    aux_file=a.aux/'aux.npz'
    with np.load(aux_file) as pool:
        assert 'y' not in pool.files and 'speaker' not in pool.files
        subs=np.sort(np.random.default_rng(4618559).choice(len(pool['x']),240,replace=False))
        aux=standardized(pool['x'][subs],p)
    frozen=forward(aux,base,p,law)[0]
    adjusted=frozen+((aux.reshape(len(aux),-1)-teacher['mean'])/teacher['scale'])@teacher['w']
    if a.arm=='frozen_aux':adjusted=frozen
    if a.arm=='scrambled_teacher':adjusted=adjusted[np.random.default_rng(6158559).permutation(len(adjusted))]
    x=np.concatenate([np.repeat(new,2,axis=0),np.repeat(old,2,axis=0),aux])
    y=np.concatenate([np.repeat(np.eye(10)[nc['y']],2,axis=0),np.repeat(forward(old,base,p,law)[0],2,axis=0),adjusted])
    dev={}
    for key in ('old','new'):
        d=load_panel(a.original/(key+'_dev.npz'));dev[key]=(standardized(d['x'],p),d['y'])
    ref={k:stats(forward(z,base,p,law)[0],lab) for k,(z,lab) in dev.items()}
    setup=since(tick)
    ctx={'parent_sha':sha(root/'parent.npz'),'teacher_sha':sha(root/'ridge_3.npz'),'teacher_fit':json.loads((root/'ridge.json').read_text())['finished'],
         'aux_input_sha':sha(aux_file),'aux_subset':subs.tolist(),'unique_group_sizes':[120,120,240],'weighted_sizes':[240,240,240],
         'setup':setup,'unlabeled_teacher_change_rms':float(np.sqrt(np.mean((adjusted-frozen)**2))),'parent_dev':ref}
    dump(out/(a.arm+'_setup.json'),ctx)
    tr=Track(a.arm,a.seed,p,law,dev,out,ref,base)
    try:
        if a.arm in ('alpha','alpha_exact','crisp'):
            named_fit(tr,x,y,old,a.arm,out/(a.arm+'_geometry.json'))
        elif a.arm=='teacher_bp':bp(tr,x,y)
        else:released_update(tr,x,y,a.arm!='receiver_teacher')
    except Expired:
        pass
    tr.save()
    print(a.arch,a.seed,a.arm,len(tr.history),flush=True)


if __name__=='__main__':
    q=argparse.ArgumentParser()
    for k in ('original','source','aux','law','out'):q.add_argument(k,type=Path)
    q.add_argument('arch');q.add_argument('seed',type=int);q.add_argument('arm',choices=ARMS)
    main(q.parse_args())
