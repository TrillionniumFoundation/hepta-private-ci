"""Source-only refusal gate for committed sanitized V13 historical observations.

This never opens original LoCoMo answers, unredacted rankings, or pretrained
weights. It validates arithmetic & explicit negative scientific authority.
"""
import argparse
from hashlib import sha256
import json
import re
from pathlib import Path

ARMS=("bm25","phrase","coverage","char","phrase_char","char_only")
CORPUS="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
FAMILY={"conv-47":190,"conv-48":239,"conv-49":196,"conv-50":204}
PRIOR={"conv-47":76,"conv-48":124,"conv-49":91,"conv-50":81}
DELTA={"conv-47":3,"conv-48":-1,"conv-49":2,"conv-50":7}

def d(x):
    return sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def require(predicate,reason):
    if not predicate:raise ValueError(reason)

def gate(report,review):
    require(type(report)==dict and type(review)==dict,"report objects")
    require(report.get('schema')=='hepta.stem.v13.cheap-original-retrieval.shadow.v1.public-negative.v1','report schema')
    require(review.get('schema')=='hepta.stem.v13.independent-original-source-review.v1','review schema')
    require(report.get('original_dataset_sha256')==CORPUS==review.get('original_corpus_sha256'),'source identity')
    require(report.get('primary_precommitted')=='phrase_char' and report.get('fixed_arms')==list(ARMS),'frozen arms')
    require(report.get('heldout_question_count')==829 and report.get('total_questions')==1986,'denominators')
    require(report.get('independent_heldout_source_groups')==4 and report.get('publisher_unknown_heldout')==7,'independent groups or unknowns')
    require(review.get('independent_recounted_questions')==1986 and review.get('rechecked_original_bm25_questions')==829,'independent physical recount')
    require(review.get('publisher_unknown_heldout')==7 and review.get('source_independent_heldout_roots')==4,'review denominator')
    require(report.get('source_sha256')==review.get('source_sha256') and report.get('raw_rank_sha256')==review.get('routes_sha256'),'material pins')
    require(review.get('score_sha256')==d(report),'independent score digest mismatch')
    require(review.get('audit_status')=='COUNTS_CONSISTENT_NOT_MODEL_SUPERIORITY','false certification')
    require(review.get('semantic_correctness') is None and review.get('model_training_executed') is False and review.get('production_authorized') is False,'review invented task proof')
    require(report.get('per_arm') and set(report['per_arm'])==set(ARMS),'missing arms')
    seen=report['per_arm']
    for a in ARMS:
        row=seen[a]
        require(row.get('heldout_any_hit3')>=0 and row.get('heldout_any_hit3')<=829,'hit3 bounded')
        require(row.get('heldout_any_hit3')<=row.get('heldout_any_hit16')<=row.get('heldout_any_hit32')<=829,'cumulative ceiling')
        require(row.get('heldout_all_hit3')<=row.get('heldout_any_hit3'),'any/all impossible')
        require(set(row.get('family_hit3',{}))==set(FAMILY),'families incomplete')
        require(sum(row['family_hit3'].values())==row['heldout_any_hit3'],'family totals mismatch')
        require(all(0<=row['family_hit3'][f]<=FAMILY[f] for f in FAMILY),'family bound')
        require(row.get('family_delta_vs_bm25')=={f:row['family_hit3'][f]-seen['bm25']['family_hit3'][f] for f in FAMILY},'invalid family deltas')
    require(seen['bm25']['family_hit3']==PRIOR and seen['bm25']['heldout_any_hit3']==372,'historical BM25 parity changed')
    primary=seen['phrase_char']
    require(primary['heldout_any_hit3']==383 and primary['family_delta_vs_bm25']==DELTA,'historical primary observation changed')
    require(review.get('bm25_heldout_hit3')==372 and review.get('primary_heldout_hit3')==383 and review.get('per_family_primary_delta')==DELTA,'reviewer mismatches')
    require(set(report.get('per_family_pairwise_vs_bm25',{}))==set(FAMILY),'paired root counts')
    for f in FAMILY:
        x=report['per_family_pairwise_vs_bm25'][f]['phrase_char']
        require(all(type(x[k]) is int and 0<=x[k]<=FAMILY[f] for k in ('gain_vs_bm25','loss_vs_bm25','membership_changed')),'bad paired events')
        require(x['gain_vs_bm25']-x['loss_vs_bm25']==DELTA[f],'paired gain/loss inconsistent')
    flags={'trained_head_updates':0,'pretrained_encoder_forwards':0,'original_reader_calls':0,
           'future_calendar_windows':0,'equal_full_lifecycle_cost_to_v11':False,
           'full_task_superiority_verified':False,'stem_winner_verified':False,
           'production_authorized':False,'original_v6_seed41_retention_closed':False}
    for k,want in flags.items():require(type(report.get(k))==type(want) and report[k]==want,'false authority or capability: '+k)
    require(report.get('independent_semantic_qa') is None,'semantic truth was not judged')
    return {'status':'PASS_SOURCE_ONLY_COUNTS_NO_GO','delta_weak_hit3':11,
            'independent_heldout_roots':4,'reader_task_success_verified':False,'production_authorized':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--review',type=Path,required=True);args=p.parse_args()
    print(json.dumps(gate(json.loads(args.report.read_bytes()),json.loads(args.review.read_bytes())),sort_keys=True))
if __name__=='__main__':main()
