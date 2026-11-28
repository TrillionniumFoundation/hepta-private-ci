"""Reconstruct external six-emotion performance from original 72-way HCSN clip scores."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def lse(x,axis):
    m=x.max(axis=axis,keepdims=True)
    return np.squeeze(m+np.log(np.exp(x-m).sum(axis=axis,keepdims=True)),axis=axis)


def scores(z,y):
    ell=lse(z,1)-z[np.arange(len(y)),y]
    correct=(z.argmax(1)==y).astype(float)
    return {'nll':float(ell.mean()),'top1':float(correct.mean()),
            'balanced_accuracy':float(np.mean([correct[y==i].mean() for i in range(6)]))},ell,correct


def recount(root,kind):
    folder=root/('scores-'+kind)
    term=json.loads((folder/'terminal.json').read_text())
    prep=json.loads((root/'prepared.json').read_text())
    models=json.loads((folder/'source_models.json').read_text())
    if sha(root/'external.npz')!=prep['prepared_sha256'] or sha(folder/'source_models.json')!=term['source_selection_sha256']:
        raise ValueError('external tensor or source models mismatch')
    with np.load(root/'external.npz',allow_pickle=False) as d:names=d['ids']; y=d['y'].astype(int)
    actor=np.array([int(k.rsplit('-',1)[1]) for k in names])
    if len(set(actor))!=24 or np.bincount(actor)[1:].tolist()!=[44]*24:raise ValueError('external population')
    actor_idx=np.random.default_rng(413126).integers(24,size=(4000,24))
    def interval(v):
        by=np.array([v[actor==i].mean() for i in range(1,25)])
        return np.r_[v.mean(),np.quantile(by[actor_idx].mean(1),[.025,.975])]
    groups={};vectors={};errors=[]; logit_count=0
    for key,record in term['models'].items():
        path=folder/(key+'.npz')
        if sha(path)!=record['external_scores_sha256'] or sha(Path(models[key]['path']))!=record['weight_sha256']:
            raise ValueError('external score or parent weights changed')
        arm,tag,seed=key.rsplit('-',2); condition=arm+'-'+tag
        with np.load(path,allow_pickle=False) as z:
            assert np.array_equal(z['ids'],names) and np.array_equal(z['labels'],y)
            raw=z['source_gallery'].astype('float64')
            emotion=lse(raw.reshape(len(y),12,6),1)
            errors.append(float(abs(emotion-z['emotion_logits']).max()));logit_count+=raw.size
        m,l,h=scores(emotion,y)
        errors.extend(abs(m[k]-record['metrics'][k]) for k in m)
        groups.setdefault(condition,[]).append(m);vectors[condition,seed]=l,h
    references=sorted(set(k.rsplit('-',1)[1] for k in groups))
    all_pairs={}
    for cond in groups:
        arm,tag=cond.rsplit('-',1)
        ref=('same_site_bp' if kind=='full' else 'sdpa')+'-'+tag
        summary={k:float(np.mean([m[k] for m in groups[cond]])) for k in ('nll','top1','balanced_accuracy')}
        errors.extend(abs(v-term['means'][cond][k]) for k,v in summary.items())
        pairs={}
        for i,metric in enumerate(('nll','top1')):
            v=np.mean([vectors[cond,str(s)][i]-vectors[ref,str(s)][i] for s in (137,311,557)],axis=0)
            pairs[metric]=interval(v).tolist();errors.append(float(np.max(abs(np.asarray(pairs[metric])-term['against_reference'][cond][metric]))))
        all_pairs[cond]=pairs
    with np.load(folder/'controls.npz',allow_pickle=False) as c:
        assert np.array_equal(c['ids'],names) and np.array_equal(c['y'],y)
        for name,met in term['controls'].items():
            m,_,_=scores(c[name],y);errors.extend(abs(m[k]-met[k]) for k in m)
    if max(errors)>1e-10 or logit_count!=term['actual_full_gallery_logits']:raise ValueError(max(errors))
    return {'group':kind,'terminal_sha256':sha(folder/'terminal.json'),'external_sha256':sha(root/'external.npz'),
            'selection_sha256':term['source_selection_sha256'],'verified_models':len(models),'gallery_logits':logit_count,
            'actors':24,'clips':len(names),'class_counts':np.bincount(y).tolist(),'maximum_discrepancy':max(errors),
            'means':term['means'],'against_reference':all_pairs,'controls':term['controls']}


if __name__=='__main__':
    root=Path(sys.argv[1]);dest=Path(sys.argv[2]);results={}
    for k in sys.argv[3:]:results[k]=recount(root,k)
    dest.write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results),flush=True)
