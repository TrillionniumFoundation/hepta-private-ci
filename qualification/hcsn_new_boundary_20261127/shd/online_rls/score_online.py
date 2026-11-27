"""Terminal cold scoring plus source-local signed feedback verification."""
from pathlib import Path
import json,sys
import numpy as np
from online import *
from confirm import canonical,d_ci
from verify_speech import lower as direct_lower, upper as direct_upper
def main():
    seal=json.loads((HERE/'SEAL.json').read_text());assert all(sha(HERE/p)==v for p,v in seal['sha256'].items())
    out=HERE/'cold';out.mkdir(exist_ok=True);te=canonical('test',splits('test'));dv=splits('dev');L=table();rows={};audit={};times={};gate={};allmax=0;allclass=0;total=0;grad={}
    for seed in (409,571,647):
        s=dict(np.load(CROSS/'fits'/str(seed)/'parent.npz'));HOLD={k:lower(d[0],s,L) for k,d in te.items()};exact={k:direct_lower(d[0],s) for k,d in te.items()};base={k:summarize(logits(h,s,L),te[k]) for k,h in HOLD.items()}
        # Check implemented BP vs full nonlinear central difference on 11 random directions.
        hk=lower(dv['gsc'][0][:1],s,L)[0];W=s['w2'].astype('f8');yy=int(dv['gsc'][1][0]);g=gradient(hk,W,s,L,y=yy);rng=np.random.default_rng(seed);vals=[]
        def ce(w):
            z=logits(hk[None].astype('f8'),s,L,w)[0];zz=softmax(z);return -np.log(zz[yy])
        for i in range(11):
            v=rng.normal(size=W.shape);v/=np.linalg.norm(v);e=1.e-5;n=(ce(W+e*v)-ce(W-e*v))/(2*e);a=(g*v).sum();vals.append([float(n),float(a)])
        grad[seed]=vals
        for arm in ('KEEP','full','orth','noanchor','shuffled','feedback','Adam','LoRA'):
            d=HERE/'fits'/str(seed)/arm;fit=json.loads((d/'fit.json').read_text());w=np.load(d/'W2.npy');key=f'{seed}-{arm}';record={};per={};store={}
            for k,h in HOLD.items():
                z=logits(h,s,L,w);z64=direct_upper(exact[k],s,w);_,y,sp,ids=te[k];raw=summarize(z,te[k])
                delta=d_ci(raw['by_speaker'],base[k]['by_speaker']);record[k]={'macro':raw['macro'],'by_speaker':raw['by_speaker'],'delta':delta};err=float(abs(z-z64).max());diff=int((z.argmax(1)!=z64.argmax(1)).sum())
                allmax=max(allmax,err);allclass+=diff;total+=z.size;per[k]={'max_diff':err,'argmax_change':diff}
                for label,v in [('scores',z),('y',y),('speaker',sp),('id',ids)]:store[k+'_'+label]=v
            np.savez_compressed(out/(key+'.npz'),**store);rows[key]=record;audit[key]=per
            gate[key]=bool(record['gsc']['delta']['d']>=.02 and record['gsc']['delta']['lo']>=0 and min(record[k]['delta']['d'] for k in ('arabic','fsdd'))>=-.0200001)
            stat=fit['front'];times[key]={'wall_s':fit['elapsed_s'],'selected':fit['selected'],'early_retention':fit['history'][-1]['new_previously_seen_first_cohort']-fit['history'][0]['new_previously_seen_first_cohort'] if fit['history'] else 0.,'batch_equiv_max':max((z['audited']['online_vs_batch_coordinate_max'] for z in stat),default=0.),'candidate_count':len(stat)+1}
    agg={}
    for arm in ('KEEP','full','orth','noanchor','shuffled','feedback','Adam','LoRA'):
        agg[arm]={}
        for k in te:
            measures=[rows[f'{s}-{arm}'][k] for s in (409,571,647)];bas=[rows[f'{s}-KEEP'][k] for s in (409,571,647)]
            def mean(c):return {p:float(np.mean([v['by_speaker'][p] for v in c])) for p in c[0]['by_speaker']}
            agg[arm][k]={'macro':float(np.mean([v['macro'] for v in measures])),'paired':d_ci(mean(measures),mean(bas))}
    dump(HERE/'result.json',dict(rows=rows,agg=agg,times=times,gate=gate,gradient_control=grad,independent=audit,verified_logits=total,max_fp64_diff=allmax,changed_class=allclass,cold_sha={p.name:sha(p) for p in out.glob('*.npz')}))
    for arm,z in agg.items():print(arm,[(k,round(v['paired']['d']*100,2)) for k,v in z.items()],[gate[f'{s}-{arm}'] for s in (409,571,647)],flush=True)
if __name__=='__main__':main()
