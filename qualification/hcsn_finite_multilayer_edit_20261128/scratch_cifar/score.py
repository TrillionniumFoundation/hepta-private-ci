"""Compute strict matched-quality frontiers from cold per-image predictions at every finite budget."""
import argparse
import json
from pathlib import Path
import numpy as np
from cold import BUDGETS,METHODS,SEEDS,sha


def read(path):return json.loads(path.read_text())


def run(a):
    seal=read(a.work/'seal.json');registry=seal['models'];data=read(a.data/'data.json')
    with np.load(a.data/'test_targets.npz') as f:
        labels={'fine':f['fine'],'coarse':f['coarse']}
    count={m:np.bincount(x) for m,x in labels.items()};classes={m:len(n) for m,n in count.items()}
    memo={};cost={};chosen={};stats={};keyset=[]
    for arch,methods in METHODS.items():
        for method in methods:
            for b in BUDGETS:
                key=(arch,method,b)
                true=[];readouts=[];timers=[];decisions=[];valid=True
                for seed in SEEDS:
                    tag=f'{arch}-{seed}-{method}';dest=a.work/tag
                    assert read(dest/'complete.json')['seal']==sha(a.work/'seal.json')
                    rec=read(a.fits/tag/'result.json')['picks'][str(b)]
                    if rec['choice'] is None:
                        valid=False;break
                    digest=rec['choice']['sha']
                    if (tag,digest) not in memo:
                        f=dest/(digest+'.npz');t=read(dest/(digest+'.json'))
                        assert sha(f)==t['evidence']
                        with np.load(f) as nz:
                            obs=np.stack([nz[m]==labels[m] for m in ('fine','coarse')]).astype('float32')
                            nll=float(nz['nll'].mean())
                        memo[tag,digest]=(obs,nll,t)
                    obs,nll,t=memo[tag,digest];true.append(obs);readouts.append(nll)
                    timers.append(dict(fit_cpu=rec['bounds'][0],fit_wall=rec['bounds'][1],eval_wall=t['wall'],
                                with_data=data['wall']+rec['bounds'][1]+t['wall'],warm=rec['bounds'][1]+t['wall']))
                    decisions.append({'sha':digest,'source':rec['choice']['detail'],'writes':rec['writes']})
                if valid:
                    stats[key]={'true':np.stack(true),'nll':readouts};cost[key]=timers;chosen[key]=decisions;keyset.append(key)
    fine=labels['fine'];coarse=labels['coarse'];n=len(fine)
    positions=[np.flatnonzero(fine==i) for i in range(100)]
    fresh={}
    for nm,metric in enumerate(('fine','coarse')):
        cond=np.stack([stats[k]['true'][:,nm] for k in keyset])
        vec=cond.mean(1)
        # The official test is nearly balanced after exact-byte deduplication.
        # Condition on its fine strata. Normalize macro scores per original true class.
        multiply=1/(classes[metric]*count[metric][labels[metric]])
        scores=(cond*multiply).sum(-1)
        scaled=(vec*multiply).astype('float32')
        rng=np.random.default_rng(8559)
        results=np.empty((len(keyset),10000),'float64')
        for start in range(0,10000,50):
            draws=np.zeros((50,n),dtype='float32')
            for idx in positions:
                draws[:,idx]=rng.multinomial(len(idx),np.full(len(idx),1/len(idx)),size=50)
            results[:,start:start+50]=scaled@draws.T
        for i,k in enumerate(keyset):
            fresh[k,metric]=dict(seeds=scores[i],boot=results[i])
    def diff(x,y,metric):
        dx=fresh[x,metric];dy=fresh[y,metric];seeds=dx['seeds']-dy['seeds'];batched=dx['boot']-dy['boot']
        return dict(seeds=seeds.tolist(),point=float(seeds.mean()),ci=np.quantile(batched,[.025,.975]).tolist())
    tables=[];index={}
    for key in keyset:
        arch,method,b=key
        row={'arch':arch,'method':method,'rung':b,'nll':stats[key]['nll'],'choices':chosen[key],'times':cost[key]}
        for metric in ('fine','coarse'):
            v=fresh[key,metric];row[metric]={'seeds':v['seeds'].tolist(),'macro':float(v['seeds'].mean()),
                                            'ci':np.quantile(v['boot'],[.025,.975]).tolist()}
        refs={m:(arch,m,b) for m in ('rf','raw','bp','fp','wrong') if (arch,m,b) in stats}
        if arch=='literal':
            refs.update({f'smooth_{method}':('smooth',method,b)} if ('smooth',method,b) in stats else {})
            dense='bp' if method=='bp' else 'rf' if method=='rf' else 'raw' if method=='raw' else 'fp'
            if ('dense',dense,b) in stats:refs['dense_matched']=('dense',dense,b)
        row['paired']={k:{metric:diff(key,val,metric) for metric in ('fine','coarse')} for k,val in refs.items()}
        controls=[r['fine'] for arm,r in row['paired'].items() if arm in ('rf','raw')]
        per=(fresh[key,'fine']['seeds']>=.15)&(fresh[key,'coarse']['seeds']>=.35)
        for ctrl in controls:per&=np.asarray(ctrl['seeds'])>=.02
        row['per_seed_pass']=per.tolist()
        row['quality_gate']=bool(per.all() and len(controls)==2 and min(x['ci'][0] for x in controls)>0)
        tables.append(row);index[key]=row
    curves=[]
    for arch in ('literal','smooth','dense'):
        for method in ('boundary','fp'):
            if method not in METHODS[arch]:continue
            a0=next((index[k] for b in BUDGETS if (k:=(arch,method,b)) in index and index[k]['quality_gate']),None)
            b0=next((index[k] for b in BUDGETS if (k:=(arch,'bp',b)) in index and index[k]['quality_gate']),None)
            row=dict(arch=arch,method=method,first_local=a0['rung'] if a0 else None,first_bp=b0['rung'] if b0 else None)
            if a0 and b0:
                edit=(arch,method,a0['rung']);bp=(arch,'bp',b0['rung'])
                delta={nm:diff(edit,bp,nm) for nm in ('fine','coarse')}
                ratios={clock:float(np.median([m[clock] for m in cost[edit]])/np.median([m[clock] for m in cost[bp]])) for clock in ('warm','with_data')}
                row.update(physical_minus_bp=delta,ratio=ratios,passed=bool(ratios['with_data']<=.8 and delta['fine']['ci'][0]>=-.02 and delta['coarse']['ci'][0]>=-.03))
            else:row.update(passed=False,reason='no matched qualifying outcome')
            curves.append(row)
    a.out.write_text(json.dumps({'results':tables,'curves':curves,'seal':sha(a.work/'seal.json'),'fine_counts':count['fine'].tolist(),
                          'coarse_counts':count['coarse'].tolist(),'bootstrap':'10000 image-cluster draws within original true fine classes'},indent=1,allow_nan=False)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('data','fits','work','out'):p.add_argument(n,type=Path)
    run(p.parse_args())
