"""Separate-process E6 numeric report reviewer; cannot attest a hostile process.

Independent recomputation of samples and physical accounting. Research-only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


class ReviewError(ValueError):
    pass


def require(ok,msg):
    if not ok:
        raise ReviewError(msg)


def audit(inputs):
    require(type(inputs) is list and len(inputs)==4,'all four scales required')
    results={}
    for r in inputs:
        require(type(r) is dict and r.get('schema')=='hepta.e6.paired-synthetic-physical-cost.v1'
                and r.get('authority')=='DENY_ALL'
                and r.get('production_accepted') is False
                and r.get('qualified_final_use') is False
                and r.get('real_pretrained_forward_count')==0
                and r.get('p95_p99_latency_qualified') is False
                and r.get('full_end_to_end_cost_qualified') is False
                and r.get('physical_cell_head_tensors_used') is True
                and r.get('all_observed_outputs_identical') is True,
                'bad physical-measurement claims')
        n=r.get('cells')
        group=r.get('source_groups_requested')
        trials=r.get('trials')
        require(type(n) is int and n in (64,256,1024,4096) and n not in results
                and type(group) is int and 1<=group<=n
                and type(trials) is int and 1<=trials<=100
                and type(r.get('scope_split')) is bool
                and type(r.get('logits_sha256')) is str and len(r['logits_sha256'])==64
                and r.get('head_bank_trainable_weight_bytes')==n*9744*4,
                'invalid scale/weight/count/canonical digest')
        require(type(r.get('arms')) is dict and set(r['arms'])=={'cached','no_feature_reuse'},
                'baseline control missing')
        # Scope+group pair count must be checked exactly rather than inferred
        # solely from group count: odd/even group parity can differ at group=n.
        unique=len({('demo_scope_B' if r['scope_split'] and i%2 else 'demo_scope_A',i%group)
                    for i in range(n)})
        for name,record in r['arms'].items():
            require(type(record) is dict,'invalid raw arm')
            count=unique if name=='cached' else n
            require(record.get('synthetic_encoder_invocations_per_trial')==count
                    and record.get('head_forwards_per_trial')==n
                    and record.get('authorized_uses_per_trial')==n,
                    'invented reuse or Cell invocations')
            ws=record.get('observed_batch_wall_ns')
            cs=record.get('observed_process_cpu_ns')
            rs=record.get('observed_maxrss_kib')
            require(type(ws) is list and type(cs) is list and type(rs) is list
                    and len(ws)==len(cs)==len(rs)==trials and
                    all(type(x) is int and 0<x<2**60 for x in ws+cs)
                    and all(x is None or type(x) is int and x>0 for x in rs),
                    'missing measured raw work')
            require(record.get('median_batch_wall_ns')==int(statistics.median(ws))
                    and record.get('min_batch_wall_ns')==min(ws)
                    and record.get('max_batch_wall_ns')==max(ws)
                    and record.get('median_process_cpu_ns')==int(statistics.median(cs))
                    and record.get('process_maxrss_kib_last_trial')==rs[-1],
                    'tampered reported statistics')
        results[n]={'requested_groups':group,'actual_scope_bound_groups':unique,
                    'tested_trials':trials,'actual_head_forwards_per_trial':n,
                    'synthetic_cached_calls':r['arms']['cached']['synthetic_encoder_invocations_per_trial'],
                    'synthetic_nonreuse_calls':r['arms']['no_feature_reuse']['synthetic_encoder_invocations_per_trial'],
                    'cached_median_batch_wall_ns':r['arms']['cached']['median_batch_wall_ns'],
                    'nonreuse_median_batch_wall_ns':r['arms']['no_feature_reuse']['median_batch_wall_ns'],
                    'shared_observed_logits_hash':r['logits_sha256']}
    require(set(results)=={64,256,1024,4096},'four measured Cell cohorts incomplete')
    return {'schema':'hepta.e6.independent-paired-physical-review.v1',
            'authority':'DENY_ALL','physical_cohorts':{str(k):v for k,v in sorted(results.items())},
            'total_new_real_pretrained_encoder_forwards':0,
            'recomputed_raw_summary_statistics':True,
            'original_evidence_authenticity_independently_attested':False,
            'end_to_end_model_latency_p99_proven':False,'production_accepted':False}


def load(path):
    raw=Path(path).read_bytes()
    if len(raw)>10_000_000:
        raise ReviewError('bounded physical report required')
    def unique(ps):
        d={}
        for k,v in ps:
            if k in d:
                raise ReviewError('duplicate JSON key')
            d[k]=v
        return d
    r=json.loads(raw,object_pairs_hook=unique,
                 parse_constant=lambda _: (_ for _ in ()).throw(ReviewError('nonfinite JSON')))
    return r


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',nargs=4,required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    scored=audit([load(p) for p in args.inputs])
    with Path(args.output).open('x',encoding='utf-8') as f:
        json.dump(scored,f,sort_keys=True,separators=(',',':'),allow_nan=False)
        f.write('\n')
    print(json.dumps({'scored_scales':len(scored['physical_cohorts']),
                      'production_accepted':False},sort_keys=True))


if __name__=='__main__':
    main()
