"""Cold-score official and unique-media MELD, using paired dialogue-cluster uncertainty."""
import argparse
import json
from pathlib import Path
import numpy as np
from train import ARMS,SEEDS,Data,digest,measures,atomic

def f1(cm):
    diag=np.diagonal(cm,axis1=-2,axis2=-1)
    return (2*diag/np.maximum(1,cm.sum(-1)+cm.sum(-2))).mean(-1)
def group_cm(labels,z,inverse,groups):
    k=inverse*49+labels*7+z.argmax(1)
    return np.bincount(k,minlength=groups*49).reshape(groups,7,7)
def main(arrays,runs,cold,rung,out):
    manifest=json.loads((cold/'complete.json').read_text());metrics={};summaries={};dev={}
    clean=y=group=inv=None;gcount=0
    for arm in ARMS:
        metrics[arm]={};dev[arm]=[]
        for seed in SEEDS:
            name=f'{arm}-{seed}';file=cold/(name+'.npz');assert digest(file)==manifest[file.name]
            receipt=json.loads((runs/name/f'rung-{rung}.json').read_text());dev[arm].append(receipt['best']['macro_f1'])
            with np.load(file) as item:
                if clean is None:
                    clean=item['clean'];y=item['y'].astype(int);group=item['dialogue'];groups,inv=np.unique(group[clean],return_inverse=True);gcount=len(groups)
                else:assert np.array_equal(y,item['y']) and np.array_equal(group,item['dialogue']) and np.array_equal(clean,item['clean'])
                for v in ['natural','no_text','no_video','no_audio','no_wall','shuffle_wall','no_prices']:
                    if v not in item:continue
                    z=item[v];score=measures(y[clean],z[clean],group[clean])
                    score['official_macro_f1']=measures(y,z,group)['macro_f1']
                    metrics[arm].setdefault(v,{})[seed]=score
                    summaries.setdefault((arm,v),[]).append(group_cm(y[clean],z[clean],inv,gcount))
    source=Data(arrays,'train');priors=np.bincount(source.y[source.clean].astype(int),minlength=7).astype(float);priors/=priors.sum()
    prior=measures(y[clean],np.repeat(np.log(priors[None]+1e-12),clean.sum(),0),group[clean])
    best=max(('attention','gru'),key=lambda a:np.mean(dev[a]))
    pairs=[(('literal','natural'),(o,'natural'),0. if o!=best else -.02) for o in ('smooth','lif',best,'text_attention')]
    pairs += [(('literal','natural'),('literal',v),0.) for v in ('no_audio','no_video','no_text','no_prices','shuffle_wall','no_wall')]
    rng=np.random.default_rng(993682);weights=rng.multinomial(gcount,np.repeat(1./gcount,gcount),size=4000)
    boot={};point={}
    for k in {v for p in pairs for v in p[:2]}:
        arr=np.array(summaries[k]).astype('float64')
        point[k]=float(np.mean(f1(arr.sum(1))))
        curves=[]
        for seed_arr in arr:
            res=weights@seed_arr.reshape(gcount,49)
            curves.append(f1(res.reshape(-1,7,7)))
        boot[k]=np.mean(curves,0)
    result={}
    for left,right,threshold in pairs:
        bs=boot[left]-boot[right]
        key=right[0]+'/'+right[1];lower=float(np.quantile(bs,.05/len(pairs)))
        result[key]=dict(macro_f1_gain=point[left]-point[right],marginal95=np.quantile(bs,[.025,.975]).tolist(),
                         simultaneous_lower=lower,threshold=threshold,passed=bool(lower>threshold))
    arch=all(result[a+'/natural']['passed'] for a in ('smooth','lif',best))
    tri=arch and result['text_attention/natural']['passed'] and any(result['literal/'+v]['passed'] for v in ('no_audio','no_video'))
    atomic(out,dict(rung=rung,official_count=len(y),unique_media_count=int(clean.sum()),clean_dialogue_count=gcount,comparators=metrics,
                    train_prior=prior,dev_mean={a:float(np.mean(v)) for a,v in dev.items()},selected_conventional=best,
                    paired_dialogue_tests=result,architecture_gate=arch,trimodal_gate=tri,
                    notes='Seeds fixed. Dialogue is the resampling unit. Potential shared episodes are separately enumerated in INPUTS.json.'))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('arrays','runs','cold'):p.add_argument(k,type=Path)
    p.add_argument('rung',type=int);p.add_argument('out',type=Path);a=p.parse_args();main(a.arrays,a.runs,a.cold,a.rung,a.out)
