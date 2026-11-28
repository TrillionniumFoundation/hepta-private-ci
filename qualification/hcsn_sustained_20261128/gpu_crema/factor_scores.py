"""Exploratory sentence/emotion decomposition of the fixed 72-prompt cold logits."""
import hashlib
import json
from pathlib import Path
import numpy as np


def logsum(x,axis):return np.logaddexp.reduce(x,axis=axis)


def separate(z,y):
    n=len(y);k=np.arange(n);sent,emotion=np.divmod(y,6);zz=z.astype('float64').reshape(n,12,6)
    ls=logsum(zz,2);le=logsum(zz,1);total=logsum(ls,1);truth=zz[k,sent,emotion]
    joint=total-truth;sentence=total-ls[k,sent];mood=total-le[k,emotion]
    r={'joint_nll':joint,'sentence_nll':sentence,'emotion_given_sentence_nll':ls[k,sent]-truth,
       'emotion_nll':mood,'sentence_given_emotion_nll':le[k,emotion]-truth,
       'sentence_top1':(ls.argmax(1)==sent).astype(float),'emotion_top1':(le.argmax(1)==emotion).astype(float),
       'joint_top1':(zz.reshape(n,-1).argmax(1)==y).astype(float)}
    assert np.allclose(sentence+r['emotion_given_sentence_nll'],joint,atol=1e-12,rtol=0)
    assert np.allclose(mood+r['sentence_given_emotion_nll'],joint,atol=1e-12,rtol=0)
    return r


def ci(d,g):
    actors=np.unique(g);cnt=np.array([np.sum(g==a) for a in actors]);ss=np.array([d[g==a].sum() for a in actors]);ii=np.random.default_rng(66541).integers(len(actors),size=(4000,len(actors)))
    return {'delta':float(np.mean(d)),'actor_ci95':np.quantile(ss[ii].sum(1)/cnt[ii].sum(1),[.025,.975]).tolist()}


def main(root):
    path=root/'cold.npz'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='bcc1748a768e289c6c7c7a7dbd006aeaf830a30a8e8891dc00f041ba6f13fe42'
    with np.load(path,allow_pickle=False) as a:
        y=a['y'];act=a['actor'];r={};comp={}
        for tag in ('updates78','time12'):
            per={}
            for arm in ('literal','smooth','lif','sdpa','ridge'):
                keys=[f'{arm}-{s}-{tag}-normal' for s in (137,311,557)] if arm!='ridge' else ['ridge-normal']
                score=[separate(a[k+'__logits'],y) for k in keys]
                per[arm]={k:np.stack([v[k] for v in score]).mean(0) for k in score[0]}
                r[tag+'_'+arm]={k:float(x.mean()) for k,x in per[arm].items()}
            for other in ('smooth','lif','sdpa','ridge'):
                comp[tag+'_literal_minus_'+other]={k:ci(d-per[other][k],act) for k,d in per['literal'].items()}
    out={'kind':'post-hoc descriptive factorization of preexisting primary endpoints','labels':'class index = 6*sentence index + emotion index','clips':len(y),'seeds':3,'actors':len(np.unique(act)),'scores':r,'paired':comp}
    (root/'factor_scores.json').write_text(json.dumps(out,indent=1)+'\n')
    for tag in ('updates78','time12'):
        for k in ('literal','sdpa','lif','ridge'):
            print(tag,k,{f:round(r[tag+'_'+k][f],4) for f in ('sentence_nll','emotion_given_sentence_nll','emotion_nll','sentence_top1','emotion_top1')})
        print(tag,'literal-SDPA', {k:v for k,v in comp[tag+'_literal_minus_sdpa'].items() if k.endswith('nll')})

if __name__=='__main__':main(Path(__file__).resolve().parent)
