"""Compute image-cluster intervals from per-token cross entropy of independently frozen predictors."""
import argparse
from pathlib import Path
import numpy as np
from caption_data import read,sha,write
from cold import ARMS,SEEDS,STEPS

DOMAINS=('test','old_test')


def score(fresh,models,cold,out):
    seal=read(cold/'seal.json');timing={};observed={};counts={};choices={}
    acquisition=read(fresh/'data.json')['acquisition_and_preparation_s']
    for arch in ('literal','smooth'):
        for seed in SEEDS:
            key=f'{arch}-{seed}';root=cold/key
            complete=read(root/'complete.json')
            assert complete['seal']==sha(cold/'seal.json') and complete['targets']==sha(root/'targets.npz')
            with np.load(root/'targets.npz') as yr: labels={dom:yr[dom+'_y'] for dom in DOMAINS}
            meta=read(models/key/'parent.json')
            for method in ARMS:
                path=models/key/(method+'.json');fit=read(path) if method!='keep' else None
                for b in STEPS:
                    name=None if not fit else fit['picks'][str(b)]['choice']['sha']
                    digest=name or 'keep'
                    result=root/(digest+'.npz');timer=read(root/(digest+'.json'))
                    assert sha(result)==timer['sha']
                    with np.load(result) as raw:
                        for dom in DOMAINS:
                            y=labels[dom]
                            for metric,mask,values in [('all',y!=0,raw[dom]),('known',y>=4,raw[dom]),('shifted',y!=0,raw[dom+'_shifted'])]:
                                observed[arch,seed,method,b,dom,metric]=(values*mask).sum(1)
                                counts[dom,metric]=mask.sum(1)
                    search=fit['picks'][str(b)]['actual_upper_wall'] if fit else 0.
                    # Loading cost is measured once per process. If this invocation produced baseline,
                    # its initial loading already contains the one-time parent-development evaluation.
                    load=fit['setup']['wall'] if fit else 0.
                    baseline=meta['wall']
                    extra=max(0.,load-baseline) if fit and fit.get('setup_measured_parent_eval',False) else load
                    warm=search+extra+baseline+timer['wall']
                    timing[arch,seed,method,b]={'attempt':search,'cold_eval':timer['wall'],'setup':extra,'baseline_dev':baseline,
                          'warm':warm,'with_common':warm+meta['source_train_wall']+acquisition}
                    choices[arch,seed,method,b]=digest
    seeds=list(SEEDS)
    summaries={};boots={};absvals={}
    for dom in DOMAINS:
        n=len(counts[dom,'all']);rng=np.random.default_rng(3928559 if dom=='test' else 3928560)
        shape=(10000,n);images=rng.integers(n,size=shape,dtype=np.int16)
        for metric in ('all','known','shifted'):
            cnt=counts[dom,metric]
            d=cnt[images].sum(1)
            keys=[(arch,m,b,dom,metric) for arch in ('literal','smooth') for m in ARMS for b in STEPS]
            # Thirty-two bootstrap replicates at a time keeps memory bounded across all methods.
            fields=np.stack([np.stack([observed[arch,s,m,b,dom,metric] for s in SEEDS]) for arch,m,b,_,_ in keys])
            seedmeans=fields.sum(-1)/cnt.sum();mats=fields.mean(1)
            draws=np.empty((len(keys),len(images)))
            for j in range(0,len(images),32):
                draws[:,j:j+32]=mats[:,images[j:j+32]].sum(-1)/d[None,j:j+32]
            for i,k in enumerate(keys):boots[k]=draws[i];absvals[k]=seedmeans[i]
    def diff(a,b):
        d=(absvals[a]-absvals[b]);samples=boots[a]-boots[b]
        return dict(seeds=d.tolist(),mean=float(d.mean()),ci=np.quantile(samples,[.025,.975]).tolist())
    table=[]
    for arch in ('literal','smooth'):
        for m in ARMS:
            for b in STEPS:
                def k(method,dom,metric='all',budget=b):return (arch,method,budget,dom,metric)
                new=diff(k('keep','test'),k(m,'test'));known=diff(k('keep','test','known'),k(m,'test','known'))
                old=diff(k(m,'old_test'),k('keep','old_test'));img=diff(k(m,'test','shifted'),k(m,'test'))
                checks=(np.array(new['seeds'])>=.05)&(np.array(known['seeds'])>=.03)&(np.array(old['seeds'])<=.03)
                comps={r:diff(k(m,'test'),k(r,'test')) for r in ('bp','lora','unigram','tied','joint','wrong')}
                gains=boots[k('keep','test')]-boots[k(m,'test')];other='smooth' if arch=='literal' else 'literal'
                otherg=boots[(other,'keep',b,'test','all')]-boots[(other,m,b,'test','all')]
                phys=(gains-otherg)
                row=dict(arch=arch,arm=m,budget=b,gain_new=new,gain_known=known,old_increase=old,
                     image_shuffle_increase=img,new_nll_vs=comps,other_law_change_ci=np.quantile(phys,[.025,.975]).tolist(),
                     raw={dom:{g:absvals[k(m,dom,g)].tolist() for g in ('all','known','shifted')} for dom in DOMAINS},
                     seeds_pass=int(checks.sum()),gate=bool(checks.all() and min(new['ci'][0],known['ci'][0])>0),
                     img_gate=bool(min(img['seeds'])>=.01 and img['ci'][0]>0),
                     clocks=[timing[arch,s,m,b] for s in SEEDS],chosen=[choices[arch,s,m,b] for s in SEEDS])
                table.append(row);summaries[arch,m,b]=row
    fronts=[]
    for arch in ('literal','smooth'):
        for m in ('tied','joint','flow'):
            rows=[summaries[arch,m,b] for b in STEPS if summaries[arch,m,b]['gate'] and summaries[arch,m,b]['new_nll_vs']['unigram']['ci'][1]<0]
            edit=rows[0] if rows else None
            for comp in ('bp','lora'):
                ref=next((summaries[arch,comp,b] for b in STEPS if summaries[arch,comp,b]['gate']),None)
                decision={'arch':arch,'editor':m,'comparator':comp,'editor_rung':edit['budget'] if edit else None,
                          'comparator_rung':ref['budget'] if ref else None}
                if ref and edit:
                    ne=diff((arch,m,edit['budget'],'test','all'),(arch,comp,ref['budget'],'test','all'))
                    r={key:np.median([c[key] for c in edit['clocks']])/np.median([c[key] for c in ref['clocks']]) for key in ('warm','with_common')}
                    decision.update(ratios=r,difference=ne,supported=bool(r['with_common']<=.8 and ne['ci'][1]<=.02))
                else:decision.update(supported=False,reason='absent preregistered qualifying arm')
                fronts.append(decision)
    write(out,{'rows':table,'matched':fronts,'seal':sha(cold/'seal.json'),'bootstrap_unit':'image','draws':10000})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for n in ('fresh','models','cold','out'):parser.add_argument(n,type=Path)
    a=parser.parse_args();score(a.fresh,a.models,a.cold,a.out)
