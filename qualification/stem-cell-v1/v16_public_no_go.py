"""Read-only negative publication guard. Verifies published summary, NOT pretrained execution."""
import argparse
import json
from v16_literal_witness_reader import SCHEMA, GROUPS, ARMS, HELD, READER_SHA, CORPUS_SHA, read


def check(report,byte_report,gold_report,repeat_report):
    if (type(report)!=dict or report.get('schema')!=SCHEMA+'.sanitized-historical-literal-diagnostic'
        or report.get('retrospective_question_count')!=32
        or report.get('actual_original_reader_requests')!=128
        or report.get('unique_original_source_families')!=4
        or report.get('original_model_sha256')!=READER_SHA
        or report.get('original_dataset_sha256')!=CORPUS_SHA
        or report.get('cohorts_selected_using_publisher_answers') is not True
        or report.get('literal_occurrence_does_not_establish_semantic_sufficiency') is not True
        or report.get('independently_human_verified_sufficiency') is not False
        or report.get('independent_semantic_answer_correctness') is not None
        or report.get('reference_reader_actual_calls')!=0
        or report.get('prospective_calendar_windows')!=0
        or report.get('official_HF_operator_parity') is not False
        or report.get('full_lifecycle_cost_matched') is not False
        or report.get('stem_winner_verified') is not False
        or report.get('v6_seed41_retention_fixed') is not False
        or report.get('production_authorized') is not False
        or report.get('decision')!='HOLD_NO_GO'):
        raise ValueError('wrong source or false published research authority')
    if (type(byte_report)!=dict or byte_report.get('schema')!=SCHEMA+'.independent-private-recount'
        or byte_report.get('verified_requests')!=128
        or byte_report.get('model_forward_calls')!=report.get('actual_model_forwards')
        or byte_report.get('semantic_accuracy') is not None
        or byte_report.get('source_sufficiency_human_verified') is not False
        or byte_report.get('reference_reader_executed') is not False
        or byte_report.get('production_authorized') is not False):
        raise ValueError('byte review not an independent real task qualification')
    if (type(gold_report)!=dict or gold_report.get('schema')!=SCHEMA+'.independent-original-source-recount'
        or gold_report.get('question_count')!=32 or gold_report.get('source_roots')!=4
        or gold_report.get('answer_dependent_historical_cohort') is not True
        or gold_report.get('independently_verified_semantics') is not False
        or gold_report.get('stronger_reader_executed') is not False
        or gold_report.get('production_authorized') is not False
        or gold_report.get('status')!='RECOUNT_PASS_NO_GO'):
        raise ValueError('original gold recount not qualified')
    if (type(repeat_report)!=dict or repeat_report.get('schema')!=SCHEMA+'.original-independent-process-repeat'
        or repeat_report.get('matched_exact_original_request_outputs')!=128
        or repeat_report.get('first_physical_forwards')!=report.get('actual_model_forwards')
        or repeat_report.get('second_physical_forwards')!=report.get('actual_model_forwards')
        or repeat_report.get('original_first_answer_sha256')!=report.get('original_answer_journal_sha256')
        or repeat_report.get('original_model_hf_parity_verified') is not False
        or repeat_report.get('independent_semantic_accuracy') is not None
        or repeat_report.get('stronger_reference_reader_executed') is not False
        or repeat_report.get('production_authorized') is not False
        or repeat_report.get('result')!='PHYSICAL_BYTES_REPEATABLE_ONLY'):
        raise ValueError('incomplete or fabricated original model second process')
    if type(report.get('per_cohort_arm'))!=dict or set(report['per_cohort_arm'])!=set(GROUPS):
        raise ValueError('incomplete literal cohort')
    for g in GROUPS:
        rows=report['per_cohort_arm'][g]
        if type(rows)!=dict or set(rows)!=set(ARMS):raise ValueError('incomplete evidence arms')
        for arm,d in rows.items():
            if (type(d)!=dict or d.get('cases')!=16
                or d.get('publisher_witness_delivered')!=(16 if arm=='witness' else 0)
                or type(d.get('literal_target_substring'))!=int
                or not 0<=d['literal_target_substring']<=16
                or type(d.get('input_tokens'))!=int or d['input_tokens']<=0
                or type(d.get('output_tokens'))!=int or d['output_tokens']<=0):
                raise ValueError('missing actual original arm results')
            if d['literal_target_substring']!=gold_report['literal_substring_hit_per_arm'][g][arm]:
                raise ValueError('independent original target mismatch')
    if type(report.get('per_original_family'))!=dict or set(report['per_original_family'])!=set(HELD):
        raise ValueError('missing independent source roots')
    for f,row in report['per_original_family'].items():
        if type(row)!=dict or set(row)!=set(GROUPS) or any(row[g]['cases']!=4 for g in GROUPS):
            raise ValueError('unbalanced source roots')
    return {'status':'ORIGINAL_BYTE_AND_PUBLISHER_COUNTS_CONSISTENT_NO_GO',
            'independent_semantic_task_accuracy':None,'model_promotion':False,
            'production_authorized':False}


def cli():
    a=argparse.ArgumentParser()
    for k in ('report','byte-recount','gold-recount','repeat'):a.add_argument('--'+k,required=True)
    p=a.parse_args()
    print(json.dumps(check(read(p.report),read(p.byte_recount),read(p.gold_recount),read(p.repeat)),sort_keys=True))

if __name__=='__main__':cli()
