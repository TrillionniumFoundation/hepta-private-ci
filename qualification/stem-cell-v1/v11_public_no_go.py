"""Stdlib-only denial gate for V11 original pretrained exploratory reranking."""
from pathlib import Path
import json

SCHEMA='hepta.stem.v11.original-pretrained-lexical-residual-public-negative.v1'
ORIGINAL_FEATURES='f1a66e34ae3f0e1a33d9719181b33b46cd91e02564642c980e6a2cd3da20ab0b'
ORIGINAL_PRED='df05ec7906d58834cf7856a0dce4dc77f6b639c0a7c910c88d49cb191f1cd01c'
ROOTS=('conv-47','conv-48','conv-49','conv-50')
SIZES=(190,239,196,204)
COUNTS={'bm25_full':372,'dense_full':223,'seed41/residual':381,'seed41/safe_two':381,
        'seed47/residual':380,'seed47/safe_two':380,
        'seed53/residual':382,'seed53/safe_two':382}


def verify(o):
    if not isinstance(o,dict) or o.get('schema')!=SCHEMA:
        raise ValueError('not original V11 negative evidence')
    if (o.get('v9_original_feature_matrix_float_sha256')!=ORIGINAL_FEATURES
        or o.get('v9_original_prediction_sha256')!=ORIGINAL_PRED
        or o.get('original_dataset_sha256')!='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
        or o.get('archive_model',{}).get('model_sha256')!='53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
        or o['archive_model'].get('official_HF_operator_tokenizer_parity') is not False
        or o.get('original_encoder_batches_reused_historical')!=492
        or o.get('new_original_pretrained_encoder_forwards')!=0
        or o.get('heldout_question_denominator')!=829
        or o.get('frozen_original_heldout_groups')!=4
        or o.get('publisher_unannotated_cases')!=7
        or o.get('train_questions_with_candidate_positive')!=906
        or o.get('train_questions_without_union_positive')!=248
        or o.get('per_seed_trainable_head_parameters')!=31
        or o.get('optimizer_updates_per_seed')!=300
        or o.get('total_actual_optimizer_updates')!=900
        or o.get('seed_values')!=[41,47,53]):
        raise ValueError('physical source/dataset/train/holdout identity mismatch')
    if (o.get('retrospective_weak_evidence_only') is not True
        or o.get('all_heldout_family_nonregression') is not False
        or o.get('production_authorized') is not False
        or o.get('stem_winner_verified') is not False
        or o.get('v6_three_seed_retention_closed') is not False
        or o.get('model_selected_on_retrospective_heldout') is not False
        or o.get('paired_question_significance_authorized') is not False
        or o.get('new_independent_future_calendar_windows')!=0
        or o.get('independent_semantic_answer_correctness') is not None
        or o.get('whole_reader_task_calls')!=0
        or o.get('equal_full_lifecycle_compute') is not False):
        raise ValueError('invented efficacy, statistical independence, compute parity or authority')
    if o.get('weak_publisher_support_top3_per_arm')!=COUNTS:
        raise ValueError('original negative and small retrospective deltas changed')
    if set(o.get('actual_head_tensors_sha256',{}))!={'41','47','53'} or any(
        not isinstance(x,str) or len(x)!=64 for x in o['actual_head_tensors_sha256'].values()):
        raise ValueError('actual original trained weight inventory missing')
    if not all(o.get(k) is True for k in ('identical_prediction_sha_in_three_original_repeat_processes',
               'identical_31_weight_head_sha_in_original_repeat_processes')):
        raise ValueError('reproducibility claim altered')
    details=o.get('weak_hit3_family_paired_diagnostics')
    if not isinstance(details,dict) or set(details)!=set(COUNTS):
        raise ValueError('family census missing arm')
    negative_arms=0
    for arm,roots in details.items():
        if not isinstance(roots,dict) or set(roots)!=set(ROOTS):
            raise ValueError('source-family census incomplete')
        total=0
        for family,size in zip(ROOTS,SIZES):
            row=roots[family]
            if not isinstance(row,dict) or set(row)!={'n','hit','unknown','gained_vs_bm25','lost_vs_bm25'}:
                raise ValueError('family row schema invalid')
            if any(type(v) is not int for v in row.values()):raise ValueError('booleans are not physical counts')
            if row['n']!=size or not 0<=row['unknown']<=size or not 0<=row['hit']<=size-row['unknown']:
                raise ValueError('impossible source-family count')
            if row['gained_vs_bm25']<0 or row['lost_vs_bm25']<0:
                raise ValueError('negative pair count')
            if arm!='bm25_full':
                bm=details['bm25_full'][family]['hit']
                if row['hit']-bm!=row['gained_vs_bm25']-row['lost_vs_bm25']:
                    raise ValueError('paired gain/loss discrepancy')
                negative_arms+=int(row['hit']<bm)
            total+=row['hit']
        if total!=COUNTS[arm]:raise ValueError('missing original denominator or changed score')
    if negative_arms==0:raise ValueError('false all-family improvement claim')
    return {'original_questions':829,'independent_family_roots':4,
            'model_winner_verified':False,'production_authorized':False}


def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('receipt',type=Path);a=ap.parse_args()
    print(json.dumps(verify(json.loads(a.receipt.read_bytes())),sort_keys=True))
if __name__=='__main__':main()
