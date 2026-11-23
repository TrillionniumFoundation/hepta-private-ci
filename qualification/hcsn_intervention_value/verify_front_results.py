from pathlib import Path
import json
import numpy as np

def validate(folder):
    p=Path(folder); seal=json.loads((p/'frontend_seal.json').read_text())
    if seal['selected'] is None:
        return {'no_frontend_qualified':True}
    panel=json.loads((p/'panels.json').read_text())[seal['selected']]
    output={}
    for sp in ('train','dev'):
        with np.load(p/(sp+'.npz'),allow_pickle=False) as z:
            y=z['target']; dt=z['dt']; labels=z['group']; fs=z['scores']; rs=z['read_scores']
        stats=[]
        for n in range(len(y)):
            t=0.; free=[]; paid=[]
            for j in range(6):
                t+=dt[n,j] if j else 0
                d=np.exp(-.2*t)
                f=bool(fs[n,j].argmax()==y[n]); r=bool(rs[n,j].argmax()==y[n])
                free.append(d*f-2*(1-d));paid.append(d*(r-.3)-2*(1-d))
            stats.append([max(max(free),max(paid))-max(free),max(max(free),max(paid))-max(free[0],paid[0])])
        stats=np.asarray(stats); grouped=np.array([stats[labels==g].mean(axis=0) for g in sorted(set(labels))])
        expected=panel[sp]
        np.testing.assert_allclose(grouped.mean(0),[expected['paid_gain_mean'],expected['wait_gain_mean']],atol=1e-12)
        assert int((grouped[:,0]>1e-12).sum())==expected['paid_positive_groups'] and expected['eligible']
        output[sp]={'groups':len(grouped),'paid_gain':float(grouped.mean(0)[0]),'wait_gain':float(grouped.mean(0)[1])}
    return output

if __name__=='__main__':
    import sys
    print(json.dumps(validate(sys.argv[1]),indent=2))
