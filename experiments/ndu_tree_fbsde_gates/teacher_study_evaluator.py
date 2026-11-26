"""Separate process for sealed synthetic teacher scoring, no training imports."""
from __future__ import annotations
import argparse
import hashlib
import json
from fractions import Fraction as Q
from global_consistency import belief_tree


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _digest(obj):
    return _sha(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode())


def _load(path,sha):
    with open(path,'rb') as f: raw=f.read()
    if _sha(raw)!=sha: raise ValueError('source or predictions changed after seal')
    return json.loads(raw,parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
                      object_pairs_hook=_unique)


def _unique(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise ValueError('duplicate JSON key')
        out[k]=v
    return out


def evaluate(future_path,future_sha,seal_path,seal_sha):
    future=_load(future_path,future_sha)
    seal=_load(seal_path,seal_sha)
    if not isinstance(future,list) or len(future)!=160 or seal.get('schema')!='hepta.ndu-tree.teacher-shadow-predictions.v1':
        raise ValueError('registered fixed 160-case future cohort required')
    if seal.get('future_source_digest')!=_digest(future):
        raise ValueError('future source identities mismatch')
    if seal.get('authority')!='DENY_ALL' or any(seal.get(k) is not False for k in
       ('production_accepted','real_pretrained_encoder_executed',
        'independent_natural_outcomes_observed','global_stochastic_fbsde_solved')):
        raise ValueError('unsupported capability or model claim')
    predictions=seal.get('predictions')
    if type(predictions) is not dict or set(predictions)!= {'learned_gate','frozen_gate','cheap_linear'}:
        raise ValueError('all three controls are mandatory')
    ids=set();groups=set();expected={}
    for row in future:
        if type(row) is not dict or set(row)!={'case_id','group_id','observed_at','split','prior','cost'} or row['split']!='future' or type(row['observed_at']) is not int or row['observed_at']<10000:
            raise ValueError('invalid future source-only case')
        if row['case_id'] in ids or row['group_id'] in groups or row['group_id']!=_digest([row['prior'],row['cost']]):
            raise ValueError('reused/unbound evidence source')
        ids.add(row['case_id']);groups.add(row['group_id'])
        if len(row['prior'])!=2 or len(row['cost'])!=2:
            raise ValueError('two-bit law only')
        # Scorer reads frozen future inputs for the FIRST time after file-hash check.
        p=tuple(Q(s) for s in row['prior']);c=tuple(Q(s) for s in row['cost'])
        if any(not Q(0)<x<1 for x in p) or any(not 0<=x<=1 for x in c):
            raise ValueError('model law outside domain')
        expected[row['case_id']]=int(belief_tree(p,c)['action'].startswith('observe_'))
    scored={}
    for name,v in predictions.items():
        if type(v) is not dict or set(v)!=ids or any(type(z) is not int or not 0<=z<8 for z in v.values()):
            raise ValueError('missing/malformed sealed arm')
        scored[name]=sum(v[k]==y for k,y in expected.items())/len(expected)
    gated=predictions['learned_gate'];linear=predictions['cheap_linear']
    recovered=sum(gated[k]==y and linear[k]!=y for k,y in expected.items())
    lost=sum(gated[k]!=y and linear[k]==y for k,y in expected.items())
    return {
        'schema':'hepta.ndu-tree.synthetic-teacher-scorer.v1',
        'gated_vs_linear_recovered_cases':recovered,
        'gated_vs_linear_lost_cases':lost,
        'synthetic_teacher_positive_cases':sum(expected.values()),
        'sealed_predictions_sha256':seal_sha,
        'sealed_future_inputs_sha256':future_sha,
        'synthetic_future_cases':len(expected),
        'teacher_agreement_by_arm':scored,
        'gated_train_cpu_ns':seal['gated_fit_cpu_ns'],
        'linear_train_cpu_ns':seal['linear_fit_cpu_ns'],
        'same_optimizer_steps_not_equal_work':True,
        'actual_pretrained_encoder_executed':False,
        'external_natural_task_utility':False,
        'stochastic_ndu_efficacy':False,
        'production_accepted':False,
        'authority':'DENY_ALL',
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--future-file',required=True)
    p.add_argument('--future-sha256',required=True)
    p.add_argument('--seal-file',required=True)
    p.add_argument('--seal-sha256',required=True)
    p.add_argument('--output',required=True)
    x=p.parse_args()
    result=evaluate(x.future_file,x.future_sha256,x.seal_file,x.seal_sha256)
    with open(x.output,'x',encoding='utf8') as f:
        json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({'result':x.output,'teacher_agreement':result['teacher_agreement_by_arm']},sort_keys=True))

if __name__=='__main__':main()
