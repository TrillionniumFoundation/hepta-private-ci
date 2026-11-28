"""Speaker-level robustness beyond the preregistered bootstrap, from immutable logits alone."""
import argparse
import itertools
import json
import hashlib
from pathlib import Path
import numpy as np
from scipy.special import logsumexp
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def examine(scores,output):
    source=None;arms={};part=json.loads((scores/'complete.json').read_text())['files']
    for n,expected in sorted(part.items()):
        f=scores/n;assert sha(f)==expected
        arm,seed=f.stem.rsplit('-',1)
        with np.load(f) as x:
            m=np.stack([x[k] for k in ('row','y','speaker')]); y=m[1].astype(int)
            if source is None:source=m
            else:assert np.array_equal(source,m)
            observation={}
            for k in ('natural','fast','slow','silent','reverse'):
                z=x[k].astype('float64');h=(z.argmax(-1)==y).astype(float)
                loss=logsumexp(z,axis=-1)-z[np.arange(len(y)),y]
                observation[k]=np.stack([h,loss],-1)
            arms.setdefault(arm,[]).append(observation)
    speaker=source[2];groups=np.unique(speaker);rows={};other=[a for a in arms if a!='literal']
    for arm in arms:
        draws=arms[arm];per={}
        for view in draws[0]:
            observed=np.mean([q[view] for q in draws],0)
            per[view]=np.stack([np.mean(observed[speaker==sp],0) for sp in groups])
        rows[arm]=per
    results={}
    for arm in other:
        delta=rows['literal']['natural']-rows[arm]['natural']
        loo=np.stack([np.delete(delta,i,0).mean(0) for i in range(len(groups))])
        signp=[]
        if len(groups)<=18:
            permutations=np.array(list(itertools.product((-1.,1.),repeat=len(groups))))
            times=permutations@delta/len(groups)
            signp=(np.abs(times)>=np.abs(delta.mean(0))-1e-12).mean(0).tolist()
        results[arm]=dict(speaker=list(map(int,groups)),paired_accuracy_nll_delta=delta.tolist(),
                          mean=delta.mean(0).tolist(),leave_one_speaker_min=loo.min(0).tolist(),leave_one_speaker_max=loo.max(0).tolist(),
                          fraction_speakers_with_positive_accuracy_gain=float(np.mean(delta[:,0]>0)),exact_speaker_signflip_two_sided=signp)
    report=dict(tally={a:len(v) for a,v in arms.items()},comparisons=results,
                caveat='Sign randomization is conditional on exchangeability/symmetry of group differences and fixed trained seeds. Positive accuracy and negative NLL favor the literal model. Only two identities are genuinely new speakers.')
    output.write_text(json.dumps(report,indent=1)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cold',type=Path);p.add_argument('out',type=Path);a=p.parse_args();examine(a.cold,a.out)
