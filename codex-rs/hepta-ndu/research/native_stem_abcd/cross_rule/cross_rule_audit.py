"""Read-only R10 candidate corroboration; not a rigorous numerical certificate."""
import argparse, csv, hashlib, json
from pathlib import Path
import numpy as np

TARGET=.04850
AGREEMENT=1e-8

def analyze(rows):
    if len(rows)!=96 or len({r['name'] for r in rows})!=96:
        raise ValueError('complete R10 census required')
    output=[]
    for r in rows:
        vals={k:float(r[k]) for k in ('cc17','gl9','terminal_cc5','terminal_cc9')}
        if not np.isfinite(list(vals.values())).all(): raise ValueError('nonfinite input')
        cc5,cc9,cc17,gl9=(vals[k] for k in ('terminal_cc5','terminal_cc9','cc17','gl9'))
        legacy=max(cc5,cc9)<=TARGET and abs(cc5-cc9)<=1e-6
        if legacy!=(r['qualified']=='True'): raise ValueError('historical gate mismatch')
        spread=max(cc9,cc17,gl9)-min(cc9,cc17,gl9)
        corroborated=max(cc9,cc17,gl9)<=TARGET and spread<=AGREEMENT
        output.append(dict(name=r['name'],width=int(r['width']),seed=int(r['seed']),
                           method=r['method'],monitor=r['monitor'],schedule=r['schedule'],
                           legacy=legacy,high_order_corroborated=corroborated,
                           legacy_rejection_with_support=corroborated and not legacy,
                           spread=spread,cc5=cc5,cc9=cc9,cc17=cc17,gl9=gl9))
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    with args.input.open(newline='') as stream: rows=list(csv.DictReader(stream))
    data=analyze(rows)
    with (args.out/'CASES.csv').open('x',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    counts=[]
    for width in (64,256):
        for schedule in ('fixed_gl5','stage_gl3_gl5'):
            for method in ('adam','lbfgs','adjoint_ncg','ad_ncg'):
                cohort=[r for r in data if (r['width'],r['schedule'],r['method'])==(width,schedule,method)]
                if len(cohort)!=6: raise ValueError('incomplete factorial cohort')
                counts.append(dict(width=width,schedule=schedule,method=method,denominator=6,
                                   historic_pass=sum(r['legacy'] for r in cohort),
                                   corroborated=sum(r['high_order_corroborated'] for r in cohort)))
    with (args.out/'GROUPS.csv').open('x',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(counts[0]));w.writeheader();w.writerows(counts)
    receipt=dict(rows=96,original_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
        historic_pass=sum(r['legacy'] for r in data),
        high_order_corroborated=sum(r['high_order_corroborated'] for r in data),
        historic_rejected_but_corroborated=sum(r['legacy_rejection_with_support'] for r in data),
        max_high_order_spread=max(r['spread'] for r in data),
        rigorous_quadrature_certificate=False,trained_models=0,changed_historic_decisions=0)
    (args.out/'RECEIPT.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps(receipt,sort_keys=True))
if __name__=='__main__': main()
