"""Deterministic local P1 P0--P6 NO_GO observational panel, not training."""
import argparse
import hashlib
import json
import math
from .contextual_rank import normalized_features, rank_receipt


def panel():
    rows=[]
    for log_ratio in (.1,.4,.7):
        old=normalized_features(log_ratio)
        for T in (1e-5,.2,1.,100.):
            for log_k in (-1.5,1.5):
                receipt=rank_receipt(log_ratio,log_k,math.log(T))
                rows.append(dict(log_ratio=log_ratio,log_k=log_k,horizon=T,
                                 old_normalized_channels=list(old),
                                 new_probability=receipt.probability,
                                 new_log_time_derivative=receipt.log_time_derivative,
                                 mathematical_rank_three=receipt.mathematical_rank_three,
                                 f64_conditioning_accepted=receipt.f64_conditioning_accepted,
                                 independent_risk_information=False,
                                 causal_quality_gain_proven=False))
    return dict(schema='hcsn-p1-contextual-time-rank-v1',rows=rows,
                parent_pr=4527,parent_head='039c31aea3d0b359f602367b27d41662f8f75caf',
                scope='bounded scalar GBM, no coupled HX/learned task/independent risk latent',
                posthoc_observational_panel=True,
                p0_p6_all_closed=False,production_activation=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    p=panel()
    raw=json.dumps(p,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    with open(args.output,'wb') as f: f.write(raw+b'\n')
    print(json.dumps(dict(rows=len(p['rows']),canonical_payload_sha256=hashlib.sha256(raw).hexdigest(),
                          numerical_conditioning_refused=sum(not x['f64_conditioning_accepted'] for x in p['rows']),
                          all_scientific_blockers_closed=False),sort_keys=True))

if __name__=='__main__':main()
