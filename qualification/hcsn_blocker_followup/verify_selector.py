"""Independent, row-level replay of registration, calibration and held-out purchasing."""
import argparse
import json
import math
from pathlib import Path
from statistics import mean


def verify(root):
    sel=json.loads((root/'selection.json').read_text())
    test=json.loads((root/'test.json').read_text())
    dev=json.loads((root/'train_dev_traces.json').read_text())
    checked, intervals = 0,0
    for stage,tr,results in [('train',dev['train_out_of_source'],sel['train_out_of_source']),
                             ('dev',dev['dev'],sel['dev']),
                             ('test',json.loads((root/'test_traces.json').read_text()),test['metrics'])]:
        labels=tr['target']; groups=tr['group']
        if len(tr['query_id'])!=len(set(tr['query_id'])):raise ValueError('duplicate query')
        for policy,actual in results.items():
            learned='/' in policy
            name,reserve=policy.split('/') if learned else (policy,0.)
            gtab={};bought=dict(rescue=0,harm=0,already_right=0,both_wrong=0)
            cal={i:[] for i in range(4)}
            for i,(label,g) in enumerate(zip(labels,groups,strict=True)):
                f=int(label==tr['free_answer'][i]); p=int(label==tr['paid_answer'][i])
                gain=tr['predicted_gain'][name][i] if learned else 0.
                buy=int(gain>.30+float(reserve)) if learned else int(name=='paid')
                value=(p-.30) if buy else f
                hits=p if buy else f
                gtab.setdefault(g,[]).append((value,hits,value-f,value-(p-.30)))
                if buy:bought[['both_wrong','rescue','harm','already_right'][2*f+p]]+=1
                if learned:
                    b=sum(gain>edge for edge in (0.,.30,.50))
                    cal[b].append((g,p-f-.30))
                checked+=1
            means={g:[mean(col) for col in zip(*rows)] for g,rows in gtab.items()}
            for j,k in enumerate(['utility','r1','delta_free','delta_paid']):
                assert math.isclose(mean(v[j] for v in means.values()),actual[k],abs_tol=1e-12)
            assert bought==actual['bought']
            for g,row in means.items():
                for j,k in enumerate(('value','accuracy','delta_free','delta_paid')):
                    assert abs(row[j]-actual['sources'][g][k])<1.e-12
            pvalues=[]
            for j in (2,3):
                d=[v[j] for v in means.values() if abs(v[j])>1.e-12]
                n=len(d); k=sum(v>0 for v in d); pvalues.append(sum(math.comb(n,a) for a in range(k,n+1))*2.**-n)
            assert pvalues==actual['one_sided_sign_p']
            if learned:
                for b,q in enumerate(actual['calibration']):
                    rows=cal[b]; assert len(rows)==q['n']
                    if rows:
                        w=[1/len(gtab[g]) for g,v in rows]
                        assert abs(sum(v*u for (g,v),u in zip(rows,w))/sum(w)-q['actual_net'])<1.e-12
                    intervals+=1
        if stage=='test':
            assert test['primary']==sel['primary'] and test['active']==sel['active']
    return {'passed':True,'row_decisions':checked,'calibration_bins':intervals}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    print(json.dumps(verify(p.parse_args().root),indent=2))
