"""V17 original CPU receipt source-only negative claims and integrity gate.

This gate never re-executes original model or authenticates human conclusions;
checking a sealed summary is NOT an original scientific replication.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path

SCHEMA='hepta.stem.v17.source-focusing-physical-public-negative.v1'
EXPECTED={
    'original_dataset_sha256':'79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4',
    'original_reader_weights_sha256':'5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c',
    'original_tokenizer_sha256':'9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c',
    'new_original_reader_requests':64,'genuine_original_model_forwards':1502,
    'original_model_input_tokens':10755,'original_model_output_tokens':1449,
    'source_roots':4,'selected_retrospective_original_questions':32,
    'source_content_actually_shrunk_cases':29,
    'double_replay_64_of_64':64,'blind_review_ticket_count_prepared':96,
    'independent_human_reviews_received':0,'stronger_reference_reader_original_forwards':0,
    'new_future_calendar_windows':0,'v6_three_seed_retention_repaired':False,
    'production_authorized':False,'decision':'HOLD_NO_GO',
}
SHA_FIELDS=('original_source_packet_sha256','original_v16_plan_sha256','v17_plan_sha256',
            'first_original_private_answer_file_sha256','second_original_private_answer_file_sha256',
            'exact_original_output_identity_digest')


def validate(x):
    if type(x)is not dict or x.get('schema')!=SCHEMA:raise ValueError('wrong V17 source claim')
    expected_keys=set(EXPECTED)|set(SHA_FIELDS)|{
        'schema','two_new_arms','per_arm_tokens','per_cohort_arm_weak_string_proxy',
        'per_original_source_root_weak_string_proxy','paired_weak_string_proxy',
        'first_physical_process_cpu_seconds','first_physical_process_wall_seconds',
        'second_physical_process_cpu_seconds','second_physical_process_wall_seconds',
        'double_replay_exact_raw_token_answers','historical_cohort_chosen_using_publisher_answer',
        'focus_selection_used_publisher_answers','five_publisher_targets_unknown_not_silent_failures',
        'semantic_correctness_independently_judged','publisher_answer_substring_is_not_semantic_accuracy',
        'human_verified_sufficient_evidence','huggingface_operator_tokenizer_parity',
        'cell_learning_utility_verified'}
    if set(x)!=expected_keys:raise ValueError('missing or added public claim')
    for k,v in EXPECTED.items():
        if type(x.get(k))!=type(v) or x[k]!=v:raise ValueError('original negative receipt drift '+k)
    for k in SHA_FIELDS:
        if type(x[k])!=str or len(x[k])!=64 or any(z not in '0123456789abcdef' for z in x[k]):raise ValueError('unbound original digest '+k)
    for k,val in {'double_replay_exact_raw_token_answers':True,
                  'historical_cohort_chosen_using_publisher_answer':True,
                  'focus_selection_used_publisher_answers':False,
                  'five_publisher_targets_unknown_not_silent_failures':True,
                  'semantic_correctness_independently_judged':None,
                  'publisher_answer_substring_is_not_semantic_accuracy':True,
                  'human_verified_sufficient_evidence':False,
                  'huggingface_operator_tokenizer_parity':False,
                  'cell_learning_utility_verified':False}.items():
        if type(x[k])!=type(val) or x[k]!=val:raise ValueError('invented scientific qualification '+k)
    if x['two_new_arms']!=['formatted_full','formatted_focused']:raise ValueError('arm swap')
    tokens=x['per_arm_tokens']
    if tokens!={'formatted_full':{'input':5679,'output':754},'formatted_focused':{'input':5076,'output':695}}:
        raise ValueError('model token accounting drift')
    if sum(t['input'] for t in tokens.values())!=10755 or sum(t['output'] for t in tokens.values())!=1449:
        raise ValueError('duplicated nested model costs')
    for k in ('first_physical_process_cpu_seconds','first_physical_process_wall_seconds',
              'second_physical_process_cpu_seconds','second_physical_process_wall_seconds'):
        if type(x[k]) not in (int,float) or not 1 < x[k] < 2000:raise ValueError('unmeasured physical process cost')
    table=x['per_cohort_arm_weak_string_proxy']
    expected={
        'literal_in_annotated_source':{'formatted_full':(16,9,0,10,0),'formatted_focused':(16,3,0,14,0),'v16_witness':(16,8,0,0,0)},
        'not_literal_in_annotated_source':{'formatted_full':(16,0,0,8,5),'formatted_focused':(16,0,0,16,5),'v16_witness':(16,0,0,0,5)}}
    if set(table)!=set(expected):raise ValueError('cohort roster')
    for cohort,arms in expected.items():
        if set(table[cohort])!=set(arms):raise ValueError('arm roster')
        for arm,(n,hit,exact,changed,unknown) in arms.items():
            row=table[cohort][arm]
            if row!={'n':n,'answer_substring':hit,'answer_exact':exact,
                     'changed_vs_original':changed,'publisher_answer_unknown':unknown}:
                raise ValueError('missing-case or weak-proxy laundering')
    p=x['paired_weak_string_proxy']
    if p!={
        'literal_in_annotated_source':{'known_answers':16,'focus_only_gain':0,'focus_only_loss':6,'formatted_vs_v16_gain':2,'formatted_vs_v16_loss':1},
        'not_literal_in_annotated_source':{'known_answers':11,'focus_only_gain':0,'focus_only_loss':0,'formatted_vs_v16_gain':0,'formatted_vs_v16_loss':0}}:
        raise ValueError('paired gain/loss invented')
    roots=x['per_original_source_root_weak_string_proxy']
    if set(roots)!={'conv-47','conv-48','conv-49','conv-50'}:raise ValueError('source-family alias')
    for fam,arms in roots.items():
        if set(arms)!={'formatted_full','formatted_focused','v16_witness'}:raise ValueError('family arms')
        if any(set(row)!={'n','answer_substring'} or type(row['n']) is not int or row['n']!=8
               or type(row['answer_substring']) is not int or not 0<=row['answer_substring']<=8 for row in arms.values()):
            raise ValueError('family count false')
    for arm in ('formatted_full','formatted_focused','v16_witness'):
        root_sum=sum(roots[f][arm]['answer_substring'] for f in roots)
        group_sum=sum(table[g][arm]['answer_substring'] for g in table)
        if root_sum!=group_sum:raise ValueError('source-family answer sum mismatch')
    return dict(audit='SEALED_SUMMARY_CONSISTENT_ONLY',reader_qualified=False,source_sufficient=False,
                pretrained_reexecuted_by_gate=False,production_authorized=False)


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);a=p.parse_args()
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate input key')
            d[k]=v
        return d
    x=json.loads(a.receipt.read_bytes(),object_pairs_hook=unique,
                 parse_constant=lambda s:(_ for _ in ()).throw(ValueError('nonfinite json')))
    print(json.dumps(validate(x),sort_keys=True))

if __name__=='__main__':main()
