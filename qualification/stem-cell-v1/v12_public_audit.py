"""Pure standard-library auditor for the sanitized V12 source-first real Reader negative.

This validates published claims and byte-bound provenance; without original
private journals it never attests genuine model execution or human correctness.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path

SCHEMA='hepta.stem.v12.original-reader-negative-public.v1'
EXPECTED={
 'reader_weights_sha256':'5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c',
 'reader_tokenizer_sha256':'9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c',
 'upstream_v11_predictions_sha256':'3dabcb167a676d124ae36ff271bb14de3d58b557b00fbbef5619030b857c8a9a',
 'upstream_v9_source_sha256':'1cb2d1d7194137cdea48ef8a13e8002c6612a9c98a1ffa71e28e7263c61bf84c',
 'publisher_gold_original_sha256':'79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4',
 'all_original_queries':829,
 'unique_disagreement_questions':3,
 'independent_source_roots':3,
 'tested_membership_events':4,
 'route_choices':12,
 'deduplicated_genuine_reader_requests':8,
 'original_reader_physical_forward_calls':142,
 'reader_input_tokens':1057,
 'reader_output_tokens':135,
 'publisher_weak_support_route_hits':0,
 'actual_changed_raw_answer_events':3,
 'cross_seed_reused_case_events':1,
 'rerun_matching_original_reader_requests':8,
 'archived_host_numeric_parity':False,
 'official_HF_operator_tokenizer_parity':False,
 'human_semantic_correctness':None,
 'independent_future_calendar_windows':0,
 'matched_total_lifecycle_cost':False,
 'full_task_superiority_verified':False,
 'typed_head_causal_utility_verified':False,
 'stem_winner_verified':False,
 'v6_seed41_retention_fixed':False,
 'production_authorized':False,
 'main_merged':False,
}
COUNTS={'41':{'ordered_diff':68,'membership_diff':3},
        '47':{'ordered_diff':7,'membership_diff':0},
        '53':{'ordered_diff':46,'membership_diff':1}}

def _reject_duplicates(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('duplicate key')
        result[k]=v
    return result

def audit(data):
    if not isinstance(data,dict) or data.get('schema')!=SCHEMA:raise ValueError('wrong V12 schema')
    if set(data)!=set(EXPECTED)|{'schema','census','original_plan_sha256','sealed_answers_sha256','rerun_token_text_sha256','experiment_source_sha256'}:
        raise ValueError('missing or unexpected claims')
    for k,expected in EXPECTED.items():
        if type(data[k])!=type(expected) or data[k]!=expected:raise ValueError('unqualified claim: '+k)
    if data['census']!=COUNTS:raise ValueError('wrong V11 disagreement census')
    for k in ('original_plan_sha256','sealed_answers_sha256','rerun_token_text_sha256','experiment_source_sha256'):
        val=data[k]
        if type(val)!=str or len(val)!=64 or any(c not in '0123456789abcdef' for c in val):raise ValueError('invalid digest: '+k)
    if len({data[k] for k in ('original_plan_sha256','sealed_answers_sha256','rerun_token_text_sha256')})!=3:
        raise ValueError('digest domain collision')
    return {'audit':'PASS_CONTRACT_ONLY','actual_reader_host_authenticated':False,
            'new_independent_model_execution':False,'production_authorized':False}

def read_file(path):
    return json.loads(Path(path).read_bytes(),object_pairs_hook=_reject_duplicates,
                      parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('report');args=a.parse_args()
    print(json.dumps(audit(read_file(args.report)),sort_keys=True))
