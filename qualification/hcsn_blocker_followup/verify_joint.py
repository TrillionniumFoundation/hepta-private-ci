"""Verify the two convex combinations directly from released audio and outcome rows."""
import argparse
from fractions import Fraction
import json
from pathlib import Path

from . import experiment as ex


def verify(raw,old,fit,report):
    weights=ex.read(fit/'fit.json')['full-svd-.1']
    inputs={}
    for split in ('train','dev','test'):
        data,_=ex.panel(raw,old,split)
        means,scales=weights['mean'],weights['std']
        for i,f in enumerate(ex.features(data)):
            label=data['target'][i]
            rescue=(data['read_scores'][i,0].argmax()==label and data['scores'][i,0].argmax()!=label)
            values=[max(-5.,min(5.,(v-m)/s)) for v,m,s in zip(f,means,scales,strict=True)]
            inputs[str(data['query_id'][i])]=(split,str(data['group'][i]),bool(rescue),[Fraction(float(v)) for v in values])
    exact={}
    for name,record in ex.read(report)['panels'].items():
        if record['separation']['feasible']:continue
        parts=record['signed_support']; splits=name.split('+')
        sides={True:[Fraction(0)]*18,False:[Fraction(0)]*18}
        mass={True:Fraction(0),False:Fraction(0)};seen=set()
        for row in parts:
            q=row['query'];split,group,rescue,features=inputs[q];w=Fraction(row['positive_rational_weight'])
            if q in seen or split not in splits or group!=row['source'] or rescue!=row['rescue'] or w<=0:
                raise ValueError('mismatched support')
            seen.add(q);mass[rescue]+=w
            for j,v in enumerate(features):sides[rescue][j]+=w*v
        if mass[True]!=Fraction(1,2) or mass[False]!=Fraction(1,2) or sides[True]!=sides[False]:
            raise ValueError('convex combinations differ')
        exact[name]={'support_queries':len(seen),'matching_rational_coordinates':18,'each_class_mass':'1/2'}
    return {'passed':True,'panels':exact}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('raw','old','fit','report'):p.add_argument(k,type=Path)
    a=p.parse_args();print(json.dumps(verify(a.raw,a.old,a.fit,a.report),indent=2))
