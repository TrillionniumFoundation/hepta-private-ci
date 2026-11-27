"""Single cold evaluation after all candidate parameters were hashed."""
from core import *
from collections import defaultdict
import os, subprocess
def canonical(part,tab):
    rows=list(tab['arabic']);raw=rows[3].astype(int);div=220 if part=='test' else 660
    rows[2]=np.array([('official_test' if part=='test' else 'official_train')+'-'+str(int(i)%div//10) for i in raw])
    return {**tab,'arabic':tuple(rows)}
def d_ci(a,b):
    x=np.array([a[k]-b[k] for k in sorted(a)]);n=len(x)
    ra=np.random.default_rng(8831+n)
    if n<=4:
        import itertools
        draw=np.array(list(itertools.product(range(n),repeat=n)))
    else: draw=ra.integers(n,size=(10000,n))
    z=x[draw].mean(1)
    return dict(d=float(x.mean()),lo=float(np.quantile(z,.025)),hi=float(np.quantile(z,.975)),people=n)
def run():
    seal=json.loads((HERE/'SEAL.json').read_text())
    for k,v in seal['sha256'].items():assert sha(HERE/k)==v,k
    tab={p:canonical(p,splits(p)) for p in ('train','dev','test')};te=tab['test'];L=table();out=HERE/'cold';out.mkdir(exist_ok=True)
    domains=('fsdd','arabic','gsc');src={}
    for k in domains:
        people={p:set(tab[p][k][2].tolist()) for p in tab}
        assert not(people['train']&people['dev'] or people['test']&(people['train']|people['dev']))
        src[k]={p:{'recordings':len(tab[p][k][1]),'speakers':len(people[p])} for p in tab}
    allobs={};pairs={};gate={};times={};interventions={}
    for seed in (409,571,647):
        d=HERE/'fits'/str(seed);s=dict(np.load(d/'parent.npz'))
        hidden={k:lower(te[k][0],s,L) for k in domains}
        parent={k:summarize(logits(h,s,L),te[k]) for k,h in hidden.items()}
        interventions[seed]={}
        for cond in ('normal','cut_both','entry_only','post_only','permute_samples'):
            condtab={}
            for k,h in hidden.items():
                hh=h.copy()
                if cond=='cut_both':hh.fill(0)
                elif cond=='entry_only':hh[:,:,H:]=0
                elif cond=='post_only':hh[:,:,:H]=0
                elif cond=='permute_samples':hh=hh[np.random.default_rng(511).permutation(len(hh))]
                condtab[k]=small({k:summarize(logits(hh,s,L),te[k])})[k]
            interventions[seed][cond]=condtab
        for arm in ('KEEP','random','gen','white','shuffled','Adam','LoRA'):
            fit=json.loads((d/arm/'fit.json').read_text())
            for route in ('point','confidence'):
                w=np.load(d/arm/(route+'.npz'))['w2']
                assert sha(d/arm/(route+'.npz'))==fit['checkpoints'][route]
                dest=out/f'{seed}-{arm}-{route}.npz';stores={};result={}
                for k,h in hidden.items():
                    z=logits(h,s,L,w);_,y,p,id=te[k]
                    for suff,arr in [('scores',z),('y',y),('speaker',p),('id',id)]:stores[k+'_'+suff]=arr
                    result[k]=summarize(z,te[k])
                np.savez_compressed(dest,**stores)
                tag=f'{seed}-{arm}-{route}';allobs[tag]=result
                pairs[tag]={k:d_ci(result[k]['by_speaker'],parent[k]['by_speaker']) for k in domains}
                diff=pairs[tag];gate[tag]=bool(diff['gsc']['d']>=.02 and diff['gsc']['lo']>=0 and all(diff[k]['d']>=-.02000001 for k in ('fsdd','arabic')))
            times[f'{seed}-{arm}']={'fit_recorded_s':fit['wall_s'],'cpu_s':fit['cpu_s'],'rss_kib':fit['peak_rss_kib'],'probes':fit['grouped_probe_upper_forward_examples'],'train_backward':fit['baseline_train_backward_examples']}
    matched={}
    for seed in (409,571,647):
        d=HERE/'fits'/str(seed);f={arm:json.loads((d/arm/'fit.json').read_text()) for arm in ('gen','white','random','Adam','LoRA')}
        for route,key in [('point','retained_point'),('confidence','retained_confidence')]:
            bestarm=max(('Adam','LoRA'),key=lambda arm:f[arm]['dev'][route]['gsc']['macro']);target=f[bestarm]['dev'][route]
            rec={'target':bestarm,'gsc_macro':target['gsc']['macro'],'old_thresholds':'prespecified each parent minus two points','arms':{}}
            for arm,r in f.items():
                hit=[row['elapsed_s'] for row in r['front'] if row[key] and row['dev']['gsc']['macro']>=target['gsc']['macro']-1e-10]
                rec['arms'][arm]=min(hit) if hit else None
            matched[f'{seed}-{route}']=rec
    avg={}
    for arm in ('KEEP','random','gen','white','shuffled','Adam','LoRA'):
        for route in ('point','confidence'):
            kk=f'{arm}-{route}';avg[kk]={}
            for d in domains:
                vals=[allobs[f'{seed}-{arm}-{route}'][d] for seed in (409,571,647)]
                old=[allobs[f'{seed}-KEEP-{route}'][d] for seed in (409,571,647)]
                def means(ms):
                    ppl=ms[0]['by_speaker'];return {p:float(np.mean([z['by_speaker'][p] for z in ms])) for p in ppl}
                avg[kk][d]={'absolute_macro':float(np.mean([s['macro'] for s in vals])),'pooled':d_ci(means(vals),means(old))}
    dump(HERE/'results.json',dict(split=src,cold=allobs,by_seed=pairs,gate=gate,arm_means=avg,times=times,quality_matched_dev=matched,barrier_interventions=interventions,cold_files={f.name:sha(f) for f in out.glob('*.npz')},**use()))
    for k in ('gen-point','white-point','random-point','Adam-point','LoRA-point','gen-confidence'):
        print(k,[(d,round(v['absolute_macro']*100,2),round(v['pooled']['d']*100,2)) for d,v in avg[k].items()],flush=True)
if __name__=='__main__':run()
