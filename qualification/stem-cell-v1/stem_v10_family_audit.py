"""Independent, research-only V9 four-family aggregate audit; never a significance test."""
import hashlib
import json
from pathlib import Path

ROOTS = ('conv-47','conv-48','conv-49','conv-50')
EXPECTED = {'bm25_full':372,'dense_full':223,
 'seed41/frozen':26,'seed41/new_only':15,'seed41/low_lr':11,'seed41/equal_budget_replay':17,
 'seed47/frozen':78,'seed47/new_only':35,'seed47/low_lr':36,'seed47/equal_budget_replay':50,
 'seed53/frozen':9,'seed53/new_only':6,'seed53/low_lr':2,'seed53/equal_budget_replay':6}
SIZES = (190,239,196,204)
# Exact raw V9 source-first post-seal aggregate, immutable original file.
EXPECTED_SOURCE_SHA256 = 'aee4f44188e005b689fec7d472900ea9ad76e11a08ece772a89401fecfdfd544'

def digest(b): return hashlib.sha256(b).hexdigest()

def audit(data, *, original_sha):
    if not isinstance(data,dict) or data.get('schema') != 'hepta.stem.v9.original-minilm-locomo-continual-shadow.v1.postseal-weak-scored':
        raise ValueError('wrong source schema')
    if original_sha != EXPECTED_SOURCE_SHA256:
        raise ValueError('original V9 raw aggregate SHA mismatch')
    if (data.get('original_predictions_sha256') !=
            'df05ec7906d58834cf7856a0dce4dc77f6b639c0a7c910c88d49cb191f1cd01c'
        or data.get('publisher_weak_retrieval_proxy_only') is not True
        or data.get('reader_full_task_answer_calls') != 0
        or data.get('equal_total_lifecycle_compute') is not False
        or data.get('heldout_question_total')!=829 or data.get('heldout_source_family_count')!=4 or
        data.get('independent_calendar_future_windows')!=0 or
        data.get('production_authorized') is not False or
        data.get('stem_winner_verified') is not False or
        data.get('independent_human_task_success') is not None or
        data.get('cross_task_learning_superiority_verified') is not False):
        raise ValueError('misrepresented original source or scientific authority')
    arms=data.get('per_arm_source_root_aggregates')
    if not isinstance(arms,dict) or set(arms)!=set(EXPECTED): raise ValueError('arm census changed')
    totals={}
    rates={}
    for arm,roots in sorted(arms.items()):
        if not isinstance(roots,dict) or set(roots)!=set(ROOTS):raise ValueError('source roots changed')
        total=0
        per=[]
        for k,n in zip(ROOTS,SIZES):
            v=roots[k]
            if not isinstance(v,dict) or set(v)!={'total_questions','unknown_annotation','weak_supported','any_support_top3','all_support_top3'}:
                raise ValueError('source aggregate fields changed')
            if any(type(v[x]) is not int for x in v):raise ValueError('not integer')
            t=v['total_questions'];unknown=v['unknown_annotation'];known=v['weak_supported'];any_=v['any_support_top3'];all_=v['all_support_top3']
            if t!=n or unknown<0 or known!=n-unknown or not (0<=all_<=any_<=known):
                raise ValueError('impossible heldout counts')
            total+=any_;per.append(round(any_/t,8))
        if total!=EXPECTED[arm]:raise ValueError('known original aggregate changed')
        totals[arm]=total;rates[arm]=per
    comparisons={}
    for arm in sorted(EXPECTED):
        if arm in ('bm25_full','dense_full'):continue
        baseline='bm25_full'
        diffs=[round(a-b,8) for a,b in zip(rates[arm],rates[baseline])]
        comparisons[arm]={'weak_hit3_total':totals[arm], 'vs_bm25_count_delta':totals[arm]-totals[baseline],
                          'family_rate_deltas':diffs,'source_families':4,
                          'paired_question_statistics_identifiable':False,
                          'family_level_significance_claim_permitted':False}
        if any(z>0 for z in diffs):raise ValueError('original no-go comparison unexpectedly changed')
    return {'schema':'hepta.stem.v10.family-aggregate-independent-negative.shadow.v1',
            'v9_source_sha256':original_sha, 'family_count':4, 'question_count':829,
            'family_counts':dict(zip(ROOTS,SIZES)), 'weak_hit3_counts':totals,
            'comparisons':comparisons,'frozen_encoder_superiority_verified':False,
            'learned_head_superiority_verified':False,
            'independent_future_windows':0,'human_semantic_task_scores':None,
            'paired_question_significance_computable':False,'production_authorized':False}

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    source=Path(a.source);out=Path(a.output)
    if out.exists() or out.is_symlink():raise FileExistsError('create-only')
    b=source.read_bytes();result=audit(json.loads(b),original_sha=digest(b))
    with out.open('x') as f: f.write(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'questions':result['question_count'],'families':result['family_count'],'superiority':False}))
if __name__=='__main__':main()
