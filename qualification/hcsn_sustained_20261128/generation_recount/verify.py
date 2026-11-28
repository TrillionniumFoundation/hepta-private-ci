"""Recompute held-caption metrics from generated token IDs and the original natural references."""
import functools
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np


@functools.lru_cache(None)
def ngrams(sent,n):
    return Counter(tuple(sent[i:i+n]) for i in range(len(sent)-n+1))


@functools.lru_cache(None)
def subsequence(x,y):
    # Bit-parallel LCS. State bit-count equals longest common subsequence length.
    mask={}
    for j,t in enumerate(y):mask[t]=mask.get(t,0)|(1<<j)
    state=0
    for t in x:
        z=state|mask.get(t,0)
        state=z&~(z-((state<<1)|1))
    return state.bit_count()


def run(root,dest):
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    tpath=root/'generation_terminal.json'
    assert sha(tpath)=='173faf903d32b78dc436cc22a8b2ae7a5d4ab20e50e16a6182383d3aec4911ea'
    t=json.loads(tpath.read_text())
    original=(root/'source-catalog/rows.json').resolve().parent.parent/'raw/original.json'
    choices=[original] if original.is_file() and sha(original)=='5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede' else []
    if not choices:
        choices=[p for p in root.parent.glob('*/*/raw/original.json') if sha(p)=='5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede']
    if not choices:raise FileNotFoundError('original references')
    raw=json.loads(choices[0].read_text())
    refs={k['filename']:[tuple(re.findall('[a-z0-9]+',s['raw'].lower())) for s in k['sentences']] for k in raw['images']}
    sample=next(iter(t['results'].values()))
    with np.load(root/'generation'/sample['score_file']) as f:ids=f['ids'].tolist()
    assert len(set(ids))==964
    refset=[refs[i] for i in ids]
    df=Counter()
    for rs in refset:df.update(set.union(*(set(ngrams(r,n)) for r in rs for n in range(1,5))))
    size=len(ids)
    @functools.lru_cache(None)
    def vec(s,n):
        v={g:v*math.log(size/max(1,df[g])) for g,v in ngrams(s,n).items()}
        return v,math.sqrt(sum(a*a for a in v.values()))
    @functools.lru_cache(None)
    def pair(h,r):
        total=0.
        for n in range(1,5):
            a,na=vec(h,n);b,nb=vec(r,n)
            if na and nb:total+=sum(min(a.get(j,0),v)*v for j,v in b.items())/(na*nb)
        lens=max(0,len(h)-1)-max(0,len(r)-1)
        return 2.5*total*math.exp(-lens*lens/72)
    vocabulary={n:w for w,n in json.loads((root/'vocabulary.json').read_text()).items()};vocabulary[1]='unk'
    arrays={};seen={};worst=0.;worst_ci=0.;tokens=0
    for name,entry in t['results'].items():
        fp=root/'generation'/entry['score_file'];assert sha(fp)==entry['score_sha256']
        if fp in seen:
            arrays[name]=seen[fp];continue
        with np.load(fp,allow_pickle=False) as a:
            assert a['ids'].tolist()==ids
            caption=[tuple(vocabulary[int(j)] for j in row if int(j)!=0) for row in a['tokens']]
            aligned={};segments=[]
            for shift,label in ((0,'aligned'),(1,'shifted')):
                cider=[];rouge=[]
                for i,rs in enumerate(refset):
                    h=caption[(i-shift)%size]
                    cider.append(np.mean([pair(h,ref) for ref in rs]))
                    lcs=[subsequence(h,ref) for ref in rs]
                    precision=max(lcs)/max(1,len(h))
                    recall=max(v/max(1,len(ref)) for v,ref in zip(lcs,rs))
                    rouge.append(2.44*precision*recall/(recall+1.44*precision) if precision and recall else 0.)
                for metric,values in [('cider',cider),('rouge',rouge)]:
                    aligned[label+'_'+metric]=np.asarray(values)
                    worst=max(worst,float(np.max(abs(a[label+'_'+metric]-values))))
            clipped=a['clipped'].sum(0);tot=a['total_ngrams'].sum(0);p=clipped/tot
            bleu=float(math.exp(min(0.,1-a['reference_lengths'].sum()/a['candidate_lengths'].sum())+np.log(p).mean()))
            worst=max(worst,abs(bleu-entry['metrics']['aligned']['bleu4']),
                      abs(float(a['token_loss'].sum()/a['token_counts'].sum())-entry['metrics']['teacher_forced_nll']))
            assert sum(map(len,refset))==4820 and a['token_counts'].sum()==11756
            tokens+=a['tokens'].size
            seen[fp]=arrays[name]=aligned
    ix=np.random.default_rng(415297).integers(size,size=(4000,size))
    for split in ('best','final'):
        for method in ('smooth','lif','sdpa'):
            for met in ('cider','rouge'):
                k='aligned_'+met
                d=np.mean([arrays[f'literal-{s}-{split}'][k]-arrays[f'{method}-{s}-{split}'][k] for s in (109,271,463)],axis=0)
                ci=np.r_[d.mean(),np.quantile(d[ix].mean(1),[.025,.975])]
                want=t['paired_image_deltas'][split]['literal-minus-'+method][met]
                worst_ci=max(worst_ci,float(np.max(abs(ci-want))))
    if max(worst,worst_ci)>1e-6:raise ValueError((worst,worst_ci))
    obj={'source_terminal_sha256':sha(tpath),'source_selection_sha256':sha(root/'selection.json'),
         'actor_free_image_count':size,'human_references':sum(map(len,refset)),
         'distinct_checkpoint_score_files':len(seen),'checkpoint_evaluations':len(arrays),
         'verified_padded_token_slots':tokens,'max_per_image_or_aggregate_error':worst,
         'max_image_bootstrap_reconstruction_error':worst_ci,
         'best_and_final_means':t['averages'],'literal_minus_other':t['paired_image_deltas'],
         'aligned_minus_shifted':t['aligned_minus_shifted'],'baselines':t['baselines']}
    dest.write_text(json.dumps(obj,indent=1)+'\n');print(json.dumps({k:obj[k] for k in ('distinct_checkpoint_score_files','max_per_image_or_aggregate_error','max_image_bootstrap_reconstruction_error','verified_padded_token_slots','best_and_final_means','literal_minus_other')}),flush=True)


if __name__=='__main__':
    run(Path(sys.argv[1]),Path(sys.argv[2]))
