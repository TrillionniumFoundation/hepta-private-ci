"""Fail-closed independent video source eligibility gate (standard library only).

This gate checks identities and partition leakage, not model performance, licensing,
pretraining-cleanliness, or probabilistic independence. Run BEFORE label access.
"""
import argparse
import hashlib
import json
from pathlib import Path

class SourceGateError(ValueError):
    pass

def _digest(x):
    if not isinstance(x, str) or len(x) != 64 or any(c not in '0123456789abcdef' for c in x):
        raise SourceGateError('noncanonical sha256 identity')
    return x

def verify(plan, *, expected_prior_sha256=None):
    if not isinstance(plan, dict) or set(plan) != {'schema','prior_source_ids','candidate_sources','candidate_revision','candidate_repository'}:
        raise SourceGateError('exact immutable independent-video-plan.v1 required')
    if plan['schema'] != 'hepta.independent-video-source-gate.v1':
        raise SourceGateError('unsupported source plan schema')
    prior=plan['prior_source_ids']
    candidates=plan['candidate_sources']
    if not isinstance(prior,list) or not 10 <= len(prior) <= 10000 or len(prior)!=len(set(prior)):
        raise SourceGateError('bounded unique prior source inventory required')
    old=set(map(_digest,prior))
    if expected_prior_sha256 is not None:
        canonical=json.dumps(sorted(old),separators=(',',':'),ensure_ascii=True).encode()
        if hashlib.sha256(canonical).hexdigest() != _digest(expected_prior_sha256):
            raise SourceGateError('prior inventory did not match externally pinned identity')
    if not isinstance(candidates,list) or not 6 <= len(candidates) <= 1000:
        raise SourceGateError('bounded future source cohort required')
    if not isinstance(plan['candidate_repository'],str) or not plan['candidate_repository'] or len(plan['candidate_repository'])>200:
        raise SourceGateError('source repository required')
    revision=plan['candidate_revision']
    if not isinstance(revision,str) or len(revision)!=40 or any(c not in '0123456789abcdef' for c in revision):
        raise SourceGateError('immutable commit required')
    seen_ids=set(); seen_media=set(); groups={'train':set(),'calibration':set(),'holdout':set()}
    for row in candidates:
        if not isinstance(row,dict) or set(row)!={'source_id','media_sha256','split','group_id'}:
            raise SourceGateError('source identities, not labels or predictions, required')
        identity=_digest(row['source_id']); media=_digest(row['media_sha256'])
        if identity in old or identity in seen_ids or media in seen_media:
            raise SourceGateError('reused or duplicate source/media')
        group=row['group_id']
        if not isinstance(group,str) or not group or len(group)>200 or row['split'] not in groups:
            raise SourceGateError('bounded source group and split required')
        seen_ids.add(identity); seen_media.add(media); groups[row['split']].add(group)
    if any(len(x)<2 for x in groups.values()):
        raise SourceGateError('at least two separate source groups per split required')
    if any(groups[a] & groups[b] for a,b in [('train','calibration'),('train','holdout'),('calibration','holdout')]):
        raise SourceGateError('source-family overlap across train/calibration/holdout')
    return {'schema':'hepta.independent-video-source-preflight.v1','eligible_by_identity':True,
        'prior_count':len(old),'candidate_count':len(candidates),
        'group_counts':{k:len(v) for k,v in groups.items()},
        'not_checked':['publisher bytes','licensing','semantic similarity','pretraining contamination','model quality','population independence'],
        'independent_quality_established':False,'production_accepted':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--prior-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    plan=json.loads(args.plan.read_text())
    verdict=verify(plan,expected_prior_sha256=args.prior_sha256)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(verdict,f,sort_keys=True,indent=2)
        f.write('\n')
if __name__=='__main__': main()
