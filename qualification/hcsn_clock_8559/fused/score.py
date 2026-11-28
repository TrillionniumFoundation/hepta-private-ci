"""Score native-trained weights in both engines, stratifying by real held-out speaker."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.special import logsumexp
SEEDS=(137,311,557)
VIEWS=('natural','fast','slow','reverse','silent')
def pack(root,name):
    f=root/(name+'.npz');c=json.loads((root/(name+'.json')).read_text())
    with f.open('rb') as h:assert hashlib.file_digest(h,'sha256').hexdigest()==c['score_sha256']
    with np.load(f) as a:return c,{k:a[k] for k in a.files}
def main(ref,native,out,comparison=None):
    data={};by={};rows={};replica=[]
    for name in VIEWS:
        by[name]={}
    for seed in SEEDS:
        ident=f'literal-{seed}';cr,z=pack(ref,ident);cn,n=pack(native,ident)
        assert cr['checkpoint_sha256']==cn['checkpoint_sha256']
        y=z['y'];speaker=z['speaker']
        for k in ('row','y','speaker'):assert np.array_equal(z[k],n[k])
        for v in VIEWS:
            a=z[v].astype('float64');b=n[v].astype('float64')
            hit=(a.argmax(1)==y).astype(float);nll=logsumexp(a,axis=1)-a[np.arange(len(y)),y]
            per={str(s):[float(hit[speaker==s].mean()),float(nll[speaker==s].mean())] for s in np.unique(speaker)}
            by[v][str(seed)]=dict(speaker_macro_accuracy=float(np.mean([r[0] for r in per.values()])),
                speaker_macro_nll=float(np.mean([r[1] for r in per.values()])),by_speaker=per,
                max_engine_logit_delta=float(np.abs(a-b).max()),predictions_disagree=int(np.sum(a.argmax(1)!=b.argmax(1))))
            if v=='natural':data[seed]=hit
        replica.append(dict(seed=seed,reference_times=cr['forward_wall_s'],native_times=cn['forward_wall_s']))
    result=dict(seed_metrics=by,engine_cold_wall=replica,source='Both new engines reload the same sealed native-trained weights.')
    if comparison:
        boards={};groups=[np.flatnonzero(speaker==g) for g in np.unique(speaker)]
        for other in ('literal','smooth','lif','cnn','attention'):
            differences=[]
            for seed in SEEDS:
                _,a=pack(comparison,f'{other}-{seed}')
                assert np.array_equal(z['row'],a['row']) and np.array_equal(speaker,a['speaker'])
                differences.append(data[seed]-(a['natural'].argmax(1)==y).astype(float))
            d=np.mean(differences,axis=0);random=np.random.default_rng(61083)
            draws=[]
            for _ in range(4000):
                sel=random.integers(len(groups),size=len(groups))
                draws.append(np.mean([d[random.choice(groups[i],len(groups[i]),replace=True)].mean() for i in sel]))
            boards[other]=dict(point=float(np.mean([d[g].mean() for g in groups])),interval95=np.quantile(draws,[.025,.975]).tolist())
        result['native_trained_minus_original_arm_at_same_budget']=boards
    out.write_text(json.dumps(result,indent=1)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('reference','native','out'):p.add_argument(k,type=Path)
    p.add_argument('--compare',type=Path);a=p.parse_args();main(a.reference,a.native,a.out,a.compare)
