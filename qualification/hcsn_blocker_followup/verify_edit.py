"""Check frozen direct edits, selection, paired transfer and finite-sample capacity."""
import argparse
import json
from pathlib import Path
import numpy as np
from . import experiment as ex,metrics,readout_edit as edit


def verify(raw,old,out):
    base=ex.read(out/'fit.json')['full-svd-.1'];seal=ex.read(out/'edit_seal.json')
    test=ex.read(out/'edit_test.json'); source_names=['train','dev','test']
    panels={s:ex.panel(raw,old,s)[0] for s in source_names}
    count=0
    stats={}
    for algorithm in ('lp','gradient'):
        rows=seal['rows'][algorithm]
        rank=lambda r:(round(rows[r]['dev']['utility'],12),round(rows[r]['dev']['worst_delta_free'],12),-float(r))
        if max(rows,key=rank)!=seal['selected'][algorithm]:raise ValueError('bad DEV selection')
        for radius,row in rows.items():
            d=np.array(row['delta'])
            if np.linalg.norm(d,ord=1)>float(radius)+1e-7:raise ValueError('norm')
            for split,p in panels.items():
                x=ex.features(p)
                z=np.clip((x-np.asarray(base['mean']))/base['std'],-5,5)
                predicted=(z@(np.asarray(base['beta'])+d[:-1])+base['bias']+d[-1])
                f=p['scores'][:,0].argmax(-1)==p['target'];c=p['read_scores'][:,0].argmax(-1)==p['target']
                if split=='train':
                    margin=.10-np.sign(c.astype(float)-f.astype(float)-.30)*(predicted-.30)
                    errors=np.maximum(0.,margin)*abs(c.astype(float)-f.astype(float)-.30)
                    objective=np.mean([errors[p['group']==g].mean() for g in set(p['group'])])+1e-5*abs(d).sum()
                    if abs(objective-row['check']['objective'])>1e-8:raise ValueError('train hinge')
                buy=predicted>.30;v=np.where(buy,c-.30,f);actual=row[split] if split!='test' else test['rows'][algorithm][radius]
                for g in np.unique(p['group']):
                    if abs(v[p['group']==g].mean()-actual['sources'][str(g)]['value'])>1e-12:raise ValueError('source payoff')
                count+=len(v)
    primary=test['rows']['lp'][seal['selected']['lp']]
    for key,ref in [('base',test['rows']['lp']['0.0']),('gradient',test['rows']['gradient'][seal['selected']['gradient']])]:
        diffs=[s['value']-ref['sources'][g]['value'] for g,s in primary['sources'].items()]
        stats[key]={'mean':float(np.mean(diffs)),'worst':min(diffs),'p':metrics.sign_p(diffs)}
    return {'passed':True,'split_decisions':count,'selected_lp_contrasts':stats,
            'lp_transfer_adopted':primary['adopt'] and min(s['mean'] for s in stats.values())>=.03
                and max(s['p'] for s in stats.values())<=.05 and min(s['p'] for s in stats.values())<=.025
                and min(s['worst'] for s in stats.values())>=-.05}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','old','out'):p.add_argument(k,type=Path)
    a=p.parse_args();print(json.dumps(verify(a.root,a.old,a.out),indent=2))
