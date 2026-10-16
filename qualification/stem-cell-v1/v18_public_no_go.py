"""Source-only fail-closed V18 original factual negative authority.

Checking this sanitized report is NOT a pretrained execution or human review.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import math

SCHEMA='hepta.stem.v18.original-four-factor-causal-isolation.public.v1'
ARMS=('full_full_heading','full_focus_heading','focused_full_heading','focused_focus_heading')
COHORTS=('literal_in_annotated_source','not_literal_in_annotated_source')
EXPECTED_LITERAL=(9,7,5,3)

def check(r):
    if type(r)!=dict or r.get('schema')!=SCHEMA or r.get('status')!='HOLD_NO_GO':
        raise ValueError('unrecognized V18 real source receipt')
    forbidden=('raw_answers','source_only','publisher_answers','original_dialogues','private_ticket_mapping','owner_secret_hex','model_tensor','real_model_tokens')
    if any(k in r for k in forbidden):raise ValueError('unsafe raw source/model material in public record')
    required_false=('source_publisher_gold_in_producer','human_verified_sufficient_evidence',
        'stronger_reference_reader_physically_executed','official_hf_tokenizer_operator_parity_verified',
        'equal_total_lifecycle_model_compute_verified','v6_seed41_retention_repaired',
        'improved_stem_selected','production_authorized','main_merged')
    if any(r.get(k) is not False for k in required_false):raise ValueError('invented owner/scientific acceptance')
    if any(type(r.get(k)) is not type(v) or r.get(k)!=v for k,v in {
        'historical_label_conditioned_cohorts':True,'two_original_model_runs_identical_outputs':True,
        'original_questions':32,'question_only_focus_modified_source_cases':29,
        'original_publisher_answer_fields_unknown':5,
        'all_factorial_case_arm_slots':128,'unique_new_original_pretrained_requests_per_run':58,
        'identical_previous_request_ids_reused':6,'two_original_model_runs_identical_request_count':58,
        'original_v17_pretrained_requests_used_for_reuse':64,
        'original_publisher_answer_fields_unknown':5,'blinded_private_original_review_tickets':128,
        'independent_human_reviews_received':0,'historical_unique_source_roots':4,
        'independent_future_calendar_windows':0}.items()):
        raise ValueError('changed denominator or phantom independent human evaluation')
    if r.get('independent_human_semantic_correctness') is not None:
        raise ValueError('no external semantic review has occurred')
    def validsha(s):return type(s)is str and len(s)==64 and all(x in '0123456789abcdef' for x in s)
    digests=('original_model_weights_sha256','original_tokenizer_sha256','original_dataset_sha256',
      'v16_plan_sha256','v17_plan_sha256','v18_plan_sha256',
      'private_original_first_answer_file_sha256','private_original_repeat_answer_file_sha256',
      'private_original_first_start_sha256','private_original_repeat_start_sha256','original_raw_output_sha256')
    if not all(validsha(r.get(k)) for k in digests):raise ValueError('unpinned original material')
    for k in ('first_process_cpu_seconds','first_process_wall_seconds','second_process_cpu_seconds','second_process_wall_seconds'):
        if type(r.get(k)) not in (int,float) or not math.isfinite(r[k]) or not 0<r[k]<4000:
            raise ValueError('false physical CPU/wall measurement')
    if type(r.get('new_original_model_forwards_per_run')) is not int or not 1300<=r['new_original_model_forwards_per_run']<=1500:
        raise ValueError('unmeasured original pretrained forward count')
    if r.get('first_physical_input_tokens') != 9779 or r.get('first_physical_output_tokens')!=1311:
        raise ValueError('raw physically consumed tokens changed')
    t=r.get('factorial_arm_logical_token_counts')
    target={'full_full_heading':(5679,754),'full_focus_heading':(5871,719),
            'focused_full_heading':(4884,736),'focused_focus_heading':(5076,695)}
    if type(t)!=dict or set(t)!=set(target):raise ValueError('four factorial conditions omitted')
    for arm,(i,o) in target.items():
        if t[arm]!={'logical_case_count':32,'input_tokens':i,'output_tokens':o}:
            raise ValueError('inconsistent factorial tokens')
    table=r.get('original_publisher_answer_substring_proxy_by_cohort')
    if type(table)!=dict or set(table)!=set(COHORTS):raise ValueError('missing outcome cohort')
    for cohort in COHORTS:
        obj=table[cohort]
        if set(obj)!=set(ARMS):raise ValueError('missing paired arm')
        for arm in ARMS:
            row=obj[arm]
            correct=EXPECTED_LITERAL[ARMS.index(arm)] if cohort==COHORTS[0] else 0
            unknown=0 if cohort==COHORTS[0] else 5
            if row!={'n':16,'unknown':unknown,'substring':correct,'exact':0}:
                raise ValueError('weak match proxy changed without original Reader')
    d=r.get('paired_factorial_source_contrasts')
    if type(d)!=dict or set(d)!=set(COHORTS):raise ValueError('missing repeated-measure contrasts')
    for cohort in COHORTS:
        c=d[cohort]
        if set(c)!={'known','length_effect_full_heading_gain','length_effect_full_heading_loss',
                'length_effect_focus_heading_gain','length_effect_focus_heading_loss',
                'heading_effect_full_body_gain','heading_effect_full_body_loss',
                'heading_effect_focus_body_gain','heading_effect_focus_body_loss','interaction_sum'}:
            raise ValueError('changing paired results')
        if cohort==COHORTS[0]:
            exp={'known':16,'length_effect_full_heading_gain':0,'length_effect_full_heading_loss':4,
               'length_effect_focus_heading_gain':0,'length_effect_focus_heading_loss':4,
               'heading_effect_full_body_gain':1,'heading_effect_full_body_loss':3,
               'heading_effect_focus_body_gain':0,'heading_effect_focus_body_loss':2,
               'interaction_sum':0}
        else:exp={k:0 for k in c};exp['known']=11
        if c!=exp:raise ValueError('factorial intervention mislabeled')
    roots=r.get('original_source_root_counts')
    if type(roots)!=dict or set(roots)!={'conv-47','conv-48','conv-49','conv-50'}:
        raise ValueError('source-family pseudo independence')
    for fam,arms in roots.items():
        if set(arms)!=set(ARMS):raise ValueError('incomplete root arms')
        for arm,row in arms.items():
            if type(row)!=dict or set(row)!={'n','substring'} or type(row['n']) is not int or row['n']!=8 or type(row['substring']) is not int or not 0<=row['substring']<=8:
                raise ValueError('invalid root count')
    for arm in ARMS:
        if sum(roots[f][arm]['substring'] for f in roots)!=sum(table[c][arm]['substring'] for c in COHORTS):
            raise ValueError('family aggregation drift')
    return {'schema':'hepta.stem.v18.public-review.v1','status':'SOURCE_AGGREGATE_CONSISTENT_NO_GO',
            'pretrained_model_forward_attested_by_this_gate':False,
            'independent_human_judgments_present':False,'production_authorized':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);a=p.parse_args()
    def reject_dupe(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate key')
            d[k]=v
        return d
    x=json.loads(a.receipt.read_text(),object_pairs_hook=reject_dupe,
      parse_constant=lambda z: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    print(json.dumps(check(x),sort_keys=True))

if __name__=='__main__':main()
