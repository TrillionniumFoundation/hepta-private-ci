"""Recompute the metrics and normal systems without Torch; archive source, parents, and raw vectors."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import time

import numpy as np


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
def write(p,v):
    q=p.with_suffix('.part');q.write_text(json.dumps(v,sort_keys=True,indent=1,allow_nan=False)+'\n');q.replace(p)
def normalized(x):return x/np.maximum(1e-12,np.linalg.norm(x,axis=1,keepdims=True))
def calc(av,tx,w):return 12*(normalized(av.astype('d')@w.astype('d'))@normalized(tx.astype('d')@w.astype('d')).T)
def components(z,base,y,stage):
    lbl=np.where(y//6<=stage,6*(y//6)+(y%6+1)%6,y);ii=np.arange(len(y));zs=z.astype('d')
    def lsm(a):
        sub=a-a.max(1,keepdims=True);return sub-np.log(np.exp(sub).sum(1,keepdims=True))
    l,b=lsm(zs),lsm(base.astype('d'));mask=zs.copy();mask[ii,lbl]=-np.inf
    return {'nll':-l[ii,lbl],'top1':(zs.argmax(1)==lbl).astype(float),'agreement':(zs.argmax(1)==base.argmax(1)).astype(float),
            'kl_parent_edited':(np.exp(b)*(b-l)).sum(1),'target_margin':zs[ii,lbl]-mask.max(1)}
def masks(y,s):return {'current':y//6==s,'past':y//6<s,'protected':y//6>=6,'future':(y//6>s)&(y//6<6),'all':np.ones(len(y),dtype=bool)}
def entry(path):
    return {'size':path.stat().st_size,'sha256':sha(path)}
def bundle(path,files):
    temp=path.with_suffix('.part')
    with tarfile.open(temp,'w',format=tarfile.USTAR_FORMAT) as tf:
        for n,p in sorted(files.items()):
            if not p.is_file():raise ValueError(str(p))
            info=tarfile.TarInfo(n);info.size=p.stat().st_size;info.mode=0o600;info.uid=info.gid=0;info.mtime=0
            with p.open('rb') as ff:tf.addfile(info,ff)
    temp.replace(path)
    with tarfile.open(path) as tf:
        assert set(tf.getnames())==set(files)
        for info in tf:
            assert hashlib.file_digest(tf.extractfile(info),'sha256').hexdigest()==sha(files[info.name])


def run(source,out,parents):
    while not (out/'terminal.json').is_file():time.sleep(12)
    term=read(out/'terminal.json');seal=read(out/'development_seal.json')
    assert sha(out/'development_seal.json')==term['seal_sha256']
    assert sha(source/'study_edit.py')==seal['source_sha256'] and sha(source/'rls_core.py')==seal['core_sha256']
    assert sha(source/'PROTOCOL.md')==seal['protocol_sha256'] and sha(parents/'whole_edit/development_seal.json')==seal['parent_selection_sha256']
    release=source/'release';release.mkdir(exist_ok=True);files={}
    arrays={};stage_count=0;nweights=0;maxerr=0.;maxbat=0.;maxci=0.
    seeds=(137,311,557)
    for s in seeds:
        sd=out/str(s);data=sd/'held.npz';basis=sd/'basis.npz'
        assert sha(data)==read(sd/'held.json')['archive_sha256'] and sha(basis)==read(sd/'basis.json')['archive_sha256']
        with np.load(data) as a:av,tx,w0,y,ids=[a[k] for k in ('held','text','W0','held_y','held_ids')]
        with np.load(basis) as a:train,tx0,orig,yy,train_ids=[a[k] for k in ('train','text','W0','train_y','train_ids')]
        assert np.array_equal(w0,orig) and np.array_equal(tx,tx0)
        old=calc(av,tx,w0);actors=np.array([n.split('_')[0] for n in ids]);who=np.unique(actors)
        keep=np.flatnonzero(yy//6>=6);keep=keep[np.argsort(train_ids[keep],kind='stable')]
        chosen=np.random.default_rng(912731).choice(keep,128,replace=False);chosen=chosen[np.argsort(train_ids[chosen],kind='stable')]
        anchor=np.concatenate([tx,train[chosen]]).astype('d');assert anchor.shape==(200,96)
        aim=normalized(tx.astype('d')@w0.astype('d'))
        pn=seal['parents'][str(s)]['parent'];pw=parents/'whole_edit'/f'full_bp-{s}'/f"epoch{pn['epoch']}.pt"
        assert sha(pw)==pn['sha256']
        bundle(release/f'basis-parent-{s}.tar',{'parent.pt':pw,'basis.npz':basis,'held.npz':data,'basis.json':sd/'basis.json','held.json':sd/'held.json'})
        for arm in term['methods']:
            k=f'{s}/{arm}';paths={}
            for j in range(6):
                st=str(j);folder=sd/arm
                fit=folder/f'stage{j}.json';fp=folder/f'stage{j}.npz';held=folder/f'held{j}.npz';rec=read(fit)
                assert sha(fit)==seal['stages'][k][st]['metadata'] and sha(fp)==seal['stages'][k][st]['weights_hash']
                assert sha(held)==term['cold_scores'][k][st]['scores_sha256'];stage_count+=1
                with np.load(held) as score, np.load(fp) as state:
                    assert np.array_equal(score['original_y'],y) and np.array_equal(score['ids'],ids)
                    for n,cand in rec['records'].items():
                        nweights+=1;w=state['W'+n];zz=score['scores'+n];z=calc(av,tx,w)
                        err=float(np.max(np.abs(z-zz)));maxerr=max(maxerr,err);assert err<3e-5,err
                        base_scores=np.load(sd/'parent'/f'held{j}.npz')
                        try: base=base_scores['scores0']
                        finally:base_scores.close()
                        values=components(zz,base,y,j)
                        for group,m in masks(y,j).items():
                            if not m.any():continue
                            for metric,vec in values.items():
                                target=term['cold_scores'][k][st]['budgets'][n]['cold'][group][metric]
                                assert abs(vec[m].mean()-target)<2e-6,(k,j,group,metric)
                        if int(n)==seal['picks'][k][st]['primary']:arrays[s,arm,j]=values
                    if arm.startswith('rls'):
                        mu=int(arm.split('-')[1]);mask=yy//6<=j;ks=train[mask].astype('d')
                        ts=np.linalg.norm(ks@w0.astype('d'),axis=1,keepdims=True)*aim[6*(yy[mask]//6)+(yy[mask]%6+1)%6]
                        solver=np.linalg.solve(np.eye(96)+mu**2*(anchor.T@anchor)+ks.T@ks,
                                     w0.astype('d')+mu**2*anchor.T@(anchor@w0.astype('d'))+ks.T@ts)
                        delta=float(abs(state['last']-solver).max());maxbat=max(maxbat,delta);assert delta<1e-7
                paths.update({f.name:f for f in (fit,fp,held)})
            bundle(release/f'{s}-{arm}.tar',paths)
    ix=np.random.default_rng(83573).integers(len(who),size=(4000,len(who)));assert len(who)==16
    for key,ls in term['paired_actor_contrasts'].items():
        a,b=key.split('_minus_')
        for js,rows in ls.items():
            j=int(js)
            for g,u in rows.items():
                use=masks(y,j)[g];counts=np.array([np.sum(use&(actors==v)) for v in who])
                for metric,r in u.items():
                    d=np.mean([arrays[s,a,j][metric]-arrays[s,b,j][metric] for s in seeds],axis=0)
                    sums=np.array([np.sum(d[use&(actors==v)]) for v in who]);ci=np.quantile(sums[ix].sum(1)/counts[ix].sum(1),[.025,.975])
                    maxci=max(maxci,float(np.max(abs(ci-r['actor_CI95']))));assert abs(d[use].mean()-r['mean'])<2e-6 and maxci<2e-6
    check={'status':'passed','three_parents':3,'weights_stage_files':stage_count,'actual_seed_stage_budget_states':nweights,
           'max_abs_cached_score_error_fp64_against_saved_fp32':maxerr,'max_abs_Woodbury_vs_independent_all_rows_gram_solve':maxbat,
           'max_abs_actor_interval_endpoint_error':maxci,'raw_scores_and_recomputed_held_metrics_verified':True,'terminal_sha256':sha(out/'terminal.json')}
    assert stage_count==162 and nweights==306
    write(release/'independent_verification.json',check)
    for p in [out/'terminal.json',out/'development_seal.json',out/'prepared.json',source/'study_edit.py',source/'rls_core.py',
              source/'PROTOCOL.md',source/'verify_release.py']:
        q=release/p.name
        if not q.exists():os.link(p,q)
        assert sha(q)==sha(p)
    for p in sorted(release.iterdir()):
        if p.name not in ('manifest.json','manifest.part'):files[p.name]=entry(p)
    write(release/'manifest.json',{'terminal_sha256':check['terminal_sha256'],'source_parent_freeze':seal['parent_selection_sha256'],
                    'verified':check,'objects':files})
    print('verified',json.dumps(check),sha(release/'manifest.json'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('parent_root',type=Path);a=p.parse_args()
    run(a.source.resolve(),a.source.resolve()/'run',a.parent_root.resolve())
