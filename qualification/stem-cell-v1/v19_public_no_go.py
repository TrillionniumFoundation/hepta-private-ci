"""Read-only independent source-only denial gate for ORIGINAL V19 sanitized receipt.

Does not load weights or publisher data. It cannot certify original neural runs.
"""
import argparse
import json
import re
from pathlib import Path

SCHEMA='hepta.stem.v19.original-window-sanitized-negative.v1'
ARMS=('full_original','single_sentence','window_plus_1','window_plus_2')
EXPECTED_SOURCE={'full_original':16,'single_sentence':7,'window_plus_1':12,'window_plus_2':14}
EXPECTED_OUTPUT={'full_original':9,'single_sentence':5,'window_plus_1':8,'window_plus_2':9}
EXPECTED_INPUT_LITERAL={'full_original':2854,'single_sentence':2448,'window_plus_1':2664,'window_plus_2':2744}
EXPECTED_INPUT_NONLITERAL={'full_original':2825,'single_sentence':2436,'window_plus_1':2592,'window_plus_2':2665}
SHA=re.compile(r'^[0-9a-f]{64}$')


def must(cond,msg):
    if not cond:raise ValueError(msg)


def audit(x):
    must(type(x)is dict and x.get('schema')==SCHEMA,'wrong source-only publication')
    for key,want in (('historical_questions',32),('source_family_roots',4),('literal_answer_cohort',16),
                     ('nonliteral_answer_cohort',16),('original_publisher_answer_unknown',5),
                     ('unique_new_original_requests_each',23),('new_original_forwards_each',526),
                     ('new_input_tokens_each',3919),('new_output_tokens_each',506),
                     ('physical_original_Runs',2),('factorial_case_arm_slots',64),
                     ('reused_physically_equal_V17_slots',40),('new_logical_slots',24),
                     ('new_unique_physical_requests',23),
                     ('cohort_selection','RETROSPECTIVE_HISTORIC_PUBLISHER_ANSWER_CONDITIONED'),
                     ('decision','HOLD_NO_GO')):
        must(type(x.get(key)) is type(want) and x[key]==want,'wrong original V19 '+key)
    for key in ('registered_plan_sha256','original_pretrained_weights_sha256','original_tokenizer_sha256',
                'frozen_original_V17_plan_sha256','frozen_original_V18_plan_sha256','original_source_sha256',
                'independent_raw_recount_digest_sha256','original_first_answer_file_sha256',
                'original_second_answer_file_sha256','original_source_first_journal_sha256',
                'original_source_second_journal_sha256'):
        must(type(x.get(key))is str and SHA.fullmatch(x[key]) is not None,'missing physical evidence SHA: '+key)
    must(x['original_pretrained_weights_sha256']=='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c', 'swapped pretrained model')
    must(x['original_tokenizer_sha256']=='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c','swapped tokenizer')
    for field in ('first_cpu_seconds','second_cpu_seconds','first_wall_seconds','second_wall_seconds'):
        val=x.get(field)
        must(type(val) in (int,float) and 0<val<3600,'fabricated or unbounded physical cost '+field)
    for key in ('independent_replay_exact','baseline_and_candidate_same_evidence_heading',
                'evidence_selected_without_publisher_answer_text_in_model_process',
                'original_publisher_gold_opened_separately_after_complete_model_seal',
                'answer_presence_string_proxy_only'):
        must(x.get(key) is True,'missing scope or original evidence flag '+key)
    for key in ('independently_human_reviewed_source_sufficiency','reference_reader_physically_executed',
                'official_HF_operator_tokenizer_parity','matched_full_lifecycle_compute',
                'independent_original_model_host_issuer_signature','stem_winner_verified',
                'cell_learning_benefit_verified','production_authorized'):
        must(x.get(key) is False,'false scientific success/authority '+key)
    must(x.get('human_semantic_task_correctness') is None and x.get('new_source_independent_calendar_windows')==0,'human or future evidence invented')
    literal=x.get('per_arm_literal_answer_cohort');nonlit=x.get('per_arm_nonliteral_answer_cohort')
    must(type(literal)is dict and type(nonlit)is dict and set(literal)==set(ARMS) and set(nonlit)==set(ARMS),'arm census')
    for arm in ARMS:
        a=literal[arm];b=nonlit[arm]
        for key,want in [('total',16),('answer_known',16),('answer_in_source',EXPECTED_SOURCE[arm]),
                         ('answer_in_output',EXPECTED_OUTPUT[arm]),('output_exact',0),
                         ('input_tokens',EXPECTED_INPUT_LITERAL[arm])]:
            must(type(a.get(key))is int and a[key]==want,'tampered literal outcome '+arm+key)
        for key,want in [('total',16),('answer_known',11),('answer_in_source',0),
                         ('answer_in_output',0),('output_exact',0),('input_tokens',EXPECTED_INPUT_NONLITERAL[arm])]:
            must(type(b.get(key))is int and b[key]==want,'tampered negative/unknown '+arm+key)
        for c in (a,b):
            must(type(c.get('output_tokens'))is int and c['output_tokens']>0,'missing actual Reader generated work')
    c=x.get('paired_literal_contrasts',{})
    for name,expected in {
        'window_plus_1_vs_single_sentence':(3,0),
        'window_plus_2_vs_single_sentence':(4,0),
        'window_plus_2_vs_full_original':(0,0),
        'window_plus_1_vs_full_original':(0,1),
        'window_plus_2_vs_window_plus_1':(1,0),
    }.items():
        d=c.get(name,{})
        must(d.get('gain')==expected[0] and d.get('loss')==expected[1] and
             d.get('identical')==16-sum(expected) and d.get('unjudged')==0,'altered paired V19 comparisons')
    family=x.get('per_family_source_counts')
    must(type(family)is dict and set(family)=={'conv-47','conv-48','conv-49','conv-50'},'source family count')
    for arms in family.values():
        must(type(arms)is dict and set(arms)==set(ARMS),'source family route census')
        for row in arms.values():must(row.get('n')==8 and type(row.get('output_has_answer'))is int,'source family denominator')
    return {'status':'COUNTS_CONSISTENT_NOT_SEMANTIC_TASK_GAIN',
            'historical_question_count':32,'source_family_roots':4,
            'independent_human_correctness':None,'production_authorized':False,
            'learning_gain_verified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('report');arg=p.parse_args()
    def no_dups(pairs):
        obj={}
        for k,v in pairs:
            if k in obj:raise ValueError('duplicate report key')
            obj[k]=v
        return obj
    def reject_constant(x):raise ValueError('nonfinite JSON '+x)
    result=json.loads(Path(arg.report).read_text(),object_pairs_hook=no_dups,parse_constant=reject_constant)
    print(json.dumps(audit(result),sort_keys=True))
