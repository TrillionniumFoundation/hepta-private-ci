"""Git-only 120 frozen-weight R22 certificate readout, no R21 binary ZIP needed."""
import argparse,csv,hashlib,json
from pathlib import Path
from fractions import Fraction as F
import numpy as np
from centered import old

def read_csv(p):
    with open(p,newline='') as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==120 and len({x['name'] for x in rows})==120
    return {x['name']:x for x in rows}

def emit(legacy,evidence,out):
    legacy=Path(legacy);evidence=Path(evidence);out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    index=read_csv(legacy/'WEIGHTS_HEX.csv')
    historical=read_csv(legacy/'SCORES.csv')
    assert index.keys()==historical.keys()
    bounds={}
    for n in (2,3,4):
      for mode in ('legacy','hybrid'):
        obj=json.loads((evidence/f'w{n}-{mode}/CERTIFICATE.json').read_text())
        assert (obj['width'],obj['mode'],obj['node_cap'],obj['threshold'])==(n,mode,4000,'1/100')
        bounds[n,mode]=F(obj['global_lower'])
    records=[]
    for name,x in sorted(index.items()):
        original=historical[name];n=int(x['width'])
        parts=x['binary64_hex_vector'].split('|')
        theta=np.asarray([float.fromhex(s) for s in parts],dtype='<f8')
        assert len(theta)==n and hashlib.sha256(theta.tobytes()).hexdigest()==x['tensor_sha256']
        pt=tuple((F(float(v)),F(float(v))) for v in theta)
        cost_l,cost_u=old.cost_bounds(pt)
        old_l,new_l=bounds[n,'legacy'],bounds[n,'hybrid']
        g0=max(F(0),cost_u-old_l);g1=max(F(0),cost_u-new_l)
        assert abs(float(g0)-float(original['strict_excess_upper']))<1e-10
        assert (g0<=old.TARGET)==(original['strict_quality']=='True')
        records.append(dict(name=name,parameters=n,seed=int(original['seed']),method=original['method'],
            inherited_R21_classification=original['strict_quality'],old_certified=g0<=old.TARGET,
            new_certified=g1<=old.TARGET,changed_proof_only=g1<=old.TARGET and g0>old.TARGET,
            final_tensor_sha256=x['tensor_sha256'],strict_point_upper=float(cost_u),
            old_global_lower=float(old_l),new_global_lower=float(new_l),
            old_strict_gap=float(g0),new_strict_gap=float(g1),
            originally_recorded_cost=original['cost_float'],refit=False,
            original_fit_cpu=original['fit_cpu'],old_update_count=original['updates']))
    with (out/'SCORES.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    s={n:dict(old=sum(r['old_certified'] for r in records if r['parameters']==n),
               improved=sum(r['new_certified'] for r in records if r['parameters']==n)) for n in (2,3,4)}
    assert s=={2:dict(old=20,improved=20),3:dict(old=0,improved=19),4:dict(old=0,improved=0)}
    receipt=dict(schema='hepta.ndu.r22.git-only-readout.v1',total=120,refits=0,
        parent_hex_sha256=hashlib.sha256((legacy/'WEIGHTS_HEX.csv').read_bytes()).hexdigest(),
        parent_scores_sha256=hashlib.sha256((legacy/'SCORES.csv').read_bytes()).hexdigest(),
        by_width=s,original_successes=20,enhanced_successes=39,newly_certified=19)
    (out/'READOUT.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps(receipt,sort_keys=True))
    return receipt
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--legacy',type=Path,required=True)
    p.add_argument('--proof-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();emit(a.legacy,a.proof_root,a.out)
