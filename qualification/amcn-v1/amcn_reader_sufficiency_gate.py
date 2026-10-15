"""STDlib independent-source-only refusal; does NOT rerun a physical Reader.

A research result receipt is not an independent semantic outcome or an
issuer-authenticated human sufficient-evidence attestation. Never grants GO.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

PROFILE='hepta.amcn.original-reader-4-evidence-regimes-two-cohort-negative.v1'
ARMS=('no_evidence','original_bm25_top3','publisher_annotated_witness','publisher_witness_lesion')
FAMILIES=('conv-47','conv-48','conv-49','conv-50')
SOURCE_SHA='7ed4ddc5ad8defb780b0931c5e9ed6c0330e01f1097a4f0196bf0128161a9864'
EXPECTED={
  'annotation_only_12': {
    'n':12,'calls':48,'answer_classes':{'ordinary':7,'adversarial':5},
    'verbatim':{'ordinary_questions':7,'gold_literal_in_original_witness':2},
    'inputs': [616,1897,1978,1880],
    'outputs':[273,261,260,265],
    'answer_contains':[0,0,1,0],
    'max24':[8,9,8,9],
    'weak':[0,0,12,0],
    'flag':False,
  },
  'verbatim_stress_8': {
    'n':8,'calls':32,'answer_classes':{'ordinary':8,'adversarial':0},
    'verbatim':{'ordinary_questions':8,'gold_literal_in_original_witness':8},
    'inputs':[413,1181,1425,1266],
    'outputs':[182,160,161,178],
    'answer_contains':[0,0,4,0],
    'max24':[7,5,5,7],
    'weak':[0,0,8,0],
    'flag':True,
  },
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verdict(report):
    require(report.get('profile')==PROFILE and report.get('all_precommitted_regimes')==list(ARMS),
            'original four-regime research contract changed')
    require(report.get('original_reader_135m_weights_sha256')==
              '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
            and report.get('original_reader_tokenizer_sha256')==
              '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
            and report.get('original_dataset_sha256')==
              '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4',
            'original archived physical Reader/source identity drift')
    cohorts=report.get('cohorts')
    require(isinstance(cohorts,dict) and set(cohorts)==set(EXPECTED),
            'missing precommitted reader diagnostics')
    for name, expect in EXPECTED.items():
        row=cohorts[name]
        require(row.get('original_case_count')==expect['n']
                and row.get('original_reader_attempts')==expect['calls']
                and row.get('actual_completed_reader_calls')==expect['calls']
                and row.get('failed_original_reader_calls')==0,
                'unreported failed/missing original reader calls')
        require(row.get('independent_historical_source_family_roots')==4
                and row.get('family_root_counts')=={fam:expect['n']//4 for fam in FAMILIES},
                'source-root duplication or omitted family')
        require(row.get('question_answer_class_counts')==expect['answer_classes']
                and row.get('ordinary_gold_verbatim_in_original_publisher_source')==expect['verbatim'],
                'publisher answer class/verbatim sufficient evidence misrepresented')
        require(row.get('case_selection_uses_publisher_gold_answer') is expect['flag']
                and row.get('publisher_witness_human_verified') is False
                and row.get('publisher_label_result_after_seal') is True,
                'gold-selected retrospective stress misreported independent')
        for field in ('original_plan_sha256','original_sealed_answers_sha256',
                      'original_input_starts_sha256','original_raw_answers_sha256',
                      'original_attempt_status_sha256','postseal_scored_aggregate_sha256'):
            token=row.get(field)
            require(isinstance(token,str) and len(token)==64
                    and set(token)<={*'0123456789abcdef'},
                    'original SHA-pinned file receipt missing')
        arms=row.get('arm_totals')
        require(isinstance(arms,dict) and set(arms)==set(ARMS),
                'missing original evidence arm')
        for i,arm in enumerate(ARMS):
            count=arms[arm]
            require(type(count.get('questions')) is int
                    and count['questions']==count['completed']==expect['n']
                    and count.get('strict_literal')==0
                    and count.get('weak_support_hit')==expect['weak'][i]
                    and count.get('publisher_answer_substring_proxy')==expect['answer_contains'][i]
                    and count.get('input_tokens')==expect['inputs'][i]
                    and count.get('output_tokens')==expect['outputs'][i]
                    and count.get('output_ceiling_reached')==expect['max24'][i],
                    'original physical cost or answer census drift')
    negatives=(
       'independent_human_verified_sufficient_evidence',
       'strict_matched_input_tokens_across_arms',
       'actual_total_Reader_compute_equal',
       'original_reader_HF_parity_verified',
       'parametric_memory_task_gain_proven',
       'typed_head_gain_proven',
       'graph_network_gain_proven',
       'reader_sufficiency_full_task_proven',
       'automatic_cell_fission_fusion_authorized',
       'production_accepted','superiority_claim')
    require(all(report.get(k) is False for k in negatives)
            and report.get('independent_semantic_judgment') is None
            and report.get('true_future_calendar_windows')==0
            and report.get('independent_source_family_roots_union')==4
            and report.get('total_actual_original_reader_calls')==80
            and report.get('total_model_failures')==0,
            'unverified original human/Reader/MemoryCell/production capability')
    require(report.get('publisher_annotations_only_weak_support') is True
            and report.get('verbatim_stress_selection_opened_answers_before_generation') is True
            and report.get('publisher_answer_text_not_passed_as_reader_gold_field') is True,
            'weak witness or gold-dependent cohort falsely hidden')
    return {
       'original_physical_reader_attempts_recounted_from_author_receipts':80,
       'number_of_unique_historical_source_roots':4,
       'publisher_oracle_weak_success_proxy_not_task_accuracy':True,
       'verbatim_8_oracle_answer_substring_proxy':4,
       'verbatim_8_oracle_strict_answer_match':0,
       'human_sufficient_evidence_verified':False,
       'independent_semantic_correctness':None,
       'trained_memorycell_candidate_promotion':False,
       'reader_capacity_accepted':False,
       'production_accepted':False,
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--summary',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    require(args.summary.is_file() and not args.summary.is_symlink() and
            sha256(args.summary.read_bytes()).hexdigest()==SOURCE_SHA,
            'unrecognized raw original aggregated receipt')
    result=verdict(json.loads(args.summary.read_bytes()))
    require(not args.output.exists() and not args.output.is_symlink(),
            'never overwrite independent rejection output')
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
