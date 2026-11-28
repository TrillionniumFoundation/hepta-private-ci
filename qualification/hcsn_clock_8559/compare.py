"""Independent score-only speaker-balanced metrics and paired uncertainty from cold logits."""
import argparse
import json
import hashlib
from pathlib import Path
import numpy as np
from scipy.special import logsumexp
SEEDS=(137,311,557)
ARMS=('literal','smooth','fixed','no_feedback','lif','cnn','attention')
VIEWS=('natural','fast','slow','reverse','silent')

def filehash(f):
    with f.open('rb') as h:return hashlib.file_digest(h,'sha256').hexdigest()
def summarize(cold,runs,rung,output,nboot):
    complete=json.loads((cold/'complete.json').read_text())
    arrays={}; reports={}; concordance={};source=None
    for arm in ARMS:
        values={k:[] for k in VIEWS};reports[arm]={}
        dev=[]
        for seed in SEEDS:
            f=cold/f'{arm}-{seed}.npz'
            assert filehash(f)==complete['files'][f.name]
            with np.load(f) as a:
                idx=a['row'];y=a['y'].astype(int);s=a['speaker'].astype(int)
                if source is None:source=np.stack([idx,y,s])
                else:assert np.array_equal(source,np.stack([idx,y,s]))
                for name in VIEWS:
                    z=a[name].astype('float64')
                    logp=z-logsumexp(z,axis=-1,keepdims=True)
                    prob=np.exp(logp);winner=z.argmax(-1)
                    values[name].append(np.stack([winner==y,-logp[np.arange(len(y)),y],prob.max(-1)]))
            dev.append(json.loads((runs/f'{arm}-{seed}'/f'rung-{rung}.json').read_text())['best']['dev_macro'])
        reports[arm]['dev_macro_across_seeds']=float(np.mean(dev))
        for name,series in values.items():
            v=np.stack(series);per=v[:,:2,:].mean(0)
            keys=np.unique(s)
            by=np.stack([per[:,s==i].mean(-1) for i in keys])
            new=np.isin(keys,[4,5])
            # ECE first pools predictions within seed with equal speaker weight, then averages seeds.
            weights=np.zeros(len(y))
            for key in keys:weights[s==key]=1./(len(keys)*np.sum(s==key))
            ece=[]
            for hit,_,confidence in v:
                e=0.
                for lo,hi in zip(np.linspace(0.,1.,11)[:-1],np.linspace(0.,1.,11)[1:]):
                    keep=(confidence>lo)&(confidence<=hi)
                    e+=abs(float(np.sum(weights[keep]*(confidence[keep]-hit[keep]))))
                ece.append(e)
            reports[arm][name]=dict(macro_accuracy=float(by[:,0].mean()),macro_nll=float(by[:,1].mean()),
                      new_speaker_macro=float(by[new,0].mean()),new_speaker_specific={str(k):float(by[i,0]) for i,k in enumerate(keys) if k in (4,5)},
                      speaker_ECE=float(np.mean(ece)),class_half_0_accuracy=float(per[0,y<10].mean()),
                      class_half_1_accuracy=float(per[0,y>=10].mean()))
            arrays[arm,name]=per[0]
    competing=max(['cnn','attention'],key=lambda a:reports[a]['dev_macro_across_seeds'])
    comp=['smooth','lif',competing]
    dif=np.stack([arrays['literal','natural']-arrays[a,'natural'] for a in comp],axis=1)
    rng=np.random.default_rng(455178);speakers=np.unique(s);idxs=[np.flatnonzero(s==k) for k in speakers]
    boot=np.zeros((nboot,len(comp)));base=np.stack([dif[g].mean(0) for g in idxs]).mean(0)
    for i in range(nboot):
        v=[]
        for ix in rng.integers(len(idxs),size=len(idxs)):
            g=idxs[ix];v.append(dif[rng.choice(g,size=len(g),replace=True)].mean(0))
        boot[i]=np.mean(v,0)
    for ix,a in enumerate(comp):
        threshold=0. if ix<2 else -.02
        lower=float(np.quantile(boot[:,ix],.05/3))
        concordance[a]=dict(literal_minus=float(base[ix]),marginal95=np.quantile(boot[:,ix],[.025,.975]).tolist(),
                            bonferroni_one_sided_lower=lower,gating_threshold=threshold,passed=lower>threshold)
    result=dict(sealed_rung=rung,records=len(y),speakers=speakers.tolist(),methods=reports,
                paired_resamples=nboot,quality_comparisons=concordance,
                full_architecture_gate=all(v['passed'] for v in concordance.values()),
                qualification='Conditional on fixed corpus and training seeds; new speakers 4 and 5 reported individually.')
    output.write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('cold',type=Path);p.add_argument('runs',type=Path);p.add_argument('rung',type=int);p.add_argument('out',type=Path)
    p.add_argument('--boot',type=int,default=4000)
    a=p.parse_args();summarize(a.cold,a.runs,a.rung,a.out,a.boot)
