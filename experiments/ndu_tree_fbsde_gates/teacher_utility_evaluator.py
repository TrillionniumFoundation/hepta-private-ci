"""Independent expected-task-utility score for already sealed synthetic Cell Heads.

Never opens training code/models or future hidden labels. The synthetic public law
allows a cheap exact Bellman oracle; this is not learned stochastic NDU efficacy.
"""
from __future__ import annotations
import argparse
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path

ARMS=('no_search','fixed_depth_1','exact_tree','frozen_gate','cheap_linear','learned_gate')


def _decode(path, sha):
    payload=Path(path).read_bytes()
    if hashlib.sha256(payload).hexdigest()!=sha:raise ValueError('sealed source/decision digest drift')
    def _unique(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('duplicate evidence key')
            d[k]=v
        return d
    return json.loads(payload,object_pairs_hook=_unique,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))


def _q(s):
    if type(s) is not str or len(s)>64:raise ValueError('canonical bounded fraction')
    try:p=Q(s)
    except (ValueError,ZeroDivisionError):raise ValueError('invalid rational') from None
    if str(p)!=s:raise ValueError('noncanonical fraction')
    return p


def _values(row):
    if type(row) is not dict or set(row)!={'case_id','group_id','observed_at','split','prior','cost'} or row['split']!='future':
        raise ValueError('future labels/source contamination')
    if type(row['prior']) is not list or len(row['prior'])!=2 or type(row['cost']) is not list or len(row['cost'])!=2:
        raise ValueError('two-bit public state required')
    p=list(map(_q,row['prior']));c=list(map(_q,row['cost']))
    if any(not 0<v<1 for v in p) or any(not 0<=v<=1 for v in c):raise ValueError('out-of-domain law')
    return (abs(2*p[0]*p[1]-1),1-p[0]+p[0]*abs(2*p[1]-1)-c[0],
            1-p[1]+p[1]*abs(2*p[0]-1)-c[1]),c


def evaluate(future_path, future_sha, seal_path, seal_sha):
    rows=_decode(future_path,future_sha);seal=_decode(seal_path,seal_sha)
    if type(rows) is not list or len(rows)!=160 or seal.get('schema')!='hepta.ndu-tree.teacher-shadow-predictions.v1' or seal.get('authority')!='DENY_ALL':
        raise ValueError('fixed research study identity required')
    if any(seal.get(flag) is not False for flag in ('production_accepted','real_pretrained_encoder_executed','global_stochastic_fbsde_solved','independent_natural_outcomes_observed')):
        raise ValueError('unsupported capability claim')
    import json as _json
    def canon(v):return hashlib.sha256(_json.dumps(v,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if seal.get('future_source_digest')!=canon(rows):raise ValueError('future source binding mismatch')
    preds=seal.get('predictions')
    if type(preds) is not dict or set(preds)!={'frozen_gate','cheap_linear','learned_gate'}:raise ValueError('required no-change / trained controls')
    ids=set();groups=set();out={name:[] for name in ARMS};counts={name:0 for name in ARMS};cost={name:Q(0) for name in ARMS}
    for row in rows:
        case=row['case_id'];group=row['group_id']
        if type(case) is not str or type(group) is not str or type(row['observed_at']) is not int or row['observed_at']<10000 or case in ids or group in groups or group!=canon([row['prior'],row['cost']]):
            raise ValueError('future group/time/identity reuse')
        ids.add(case);groups.add(group)
        v,c=_values(row)
        best_observe=1 if v[1]>=v[2] else 2
        exact=max(range(3),key=lambda i:(v[i],-i))
        picks={'no_search':0,'fixed_depth_1':1,'exact_tree':exact}
        for arm in ('frozen_gate','cheap_linear','learned_gate'):
            arm_pred=preds[arm]
            if type(arm_pred) is not dict or case not in arm_pred or type(arm_pred[case]) is not int or not 0<=arm_pred[case]<8:
                raise ValueError('missing/malformed future action')
            picks[arm]=best_observe if arm_pred[case]==1 else 0
        for name,act in picks.items():
            out[name].append(v[act]);counts[name]+=int(act!=0)
            if act:cost[name]+=c[act-1]
    for arm,values in preds.items():
        if set(values)!=ids:raise ValueError('extra/missing sealed predictions')
    oracle=sum(out['exact_tree'],Q(0))/len(rows)
    arms={}
    for name,arr in out.items():
        mean=sum(arr,Q(0))/len(arr)
        arms[name]={'expected_utility':float(mean),'expected_regret_to_exact_tree':float(oracle-mean),
                    'inspection_count':counts[name],'mean_modelled_inspection_cost':float(cost[name]/len(rows)),
                    'reasoning_training_cpu_ns':seal['gated_fit_cpu_ns'] if name=='learned_gate' else seal['linear_fit_cpu_ns'] if name=='cheap_linear' else 0,
                    'physical_encoder_forward_count':0}
    return {'schema':'hepta.ndu-tree.synthetic-utility-after-seal.v1',
            'future_source_sha256':future_sha,'prediction_seal_sha256':seal_sha,'n':len(rows),'arms':arms,
            'all_arms_same_predeclared_public_law':True,
            'real_pretrained_model_utility':False,'independent_external_outcome':False,
            'ndu_stochastic_fbsde_qualified':False,'p3_qualified':False,'p5_qualified':False,
            'production_accepted':False,'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--future-file',required=True);p.add_argument('--future-sha256',required=True)
    p.add_argument('--seal-file',required=True);p.add_argument('--seal-sha256',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args();result=evaluate(a.future_file,a.future_sha256,a.seal_file,a.seal_sha256)
    with Path(a.output).open('x',encoding='utf-8') as f:
        json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({'output':a.output,'n':result['n'],'p3_qualified':False},sort_keys=True))

if __name__=='__main__':main()
