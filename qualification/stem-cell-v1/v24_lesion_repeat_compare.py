"""V24 separate original-model process consistency, never a semantic review.

Both input reports MUST have come from independently sealed model outputs and
separate on-host token/source reviewers. This program checks reports only, so a
source-only CI test cannot independently authenticate the physical producer.
"""
from __future__ import annotations
import argparse
import json
from v21_original_plan_rebuilder import digest
from v22_original_crosshost_execute import read_private,seal
from v24_lesion_citation_independent_review import SCHEMA,check_public


def compare(first, second):
    check_public(first);check_public(second)
    if (first['source_scope_private_plan_sha256']!=second['source_scope_private_plan_sha256']
        or first['private_source_scoped_answer_sha256']==second['private_source_scoped_answer_sha256']):
        # Identical complete receipt including different measured CPU/wall is
        # suspicious, not an independently observed distinct run.
        raise ValueError('not distinct complete immutable physical run receipts')
    equal_fields=(
        'original_plan_sha256','original_model_sha256','tokenizer_sha256',
        'reader_config_sha256','total_historical_lesion_cases',
        'source_scope_input_identity_sha256','output_lineage_sha256',
        'source_scoped_model_forwards','source_scoped_input_tokens',
        'source_scoped_output_tokens','baseline_structural_citations',
        'source_scoped_structural_citations','paired_structural_transitions',
        'original_publisher_answer_weak_proxy','per_correlated_root',
        'source_ids_and_evidence_text_same','changes_only_reference_range_instruction',
        'reference_qwen_executed','semantic_accuracy','independent_human_review',
        'production_authorized','decision',
    )
    if any(first[k]!=second[k] for k in equal_fields):
        raise ValueError('two original physical runs do not reproduce response/citation lineage')
    return {
        'schema':SCHEMA+'.two-process-non-authorizing-repeat',
        'first_private_result_sha256':first['private_source_scoped_answer_sha256'],
        'second_private_result_sha256':second['private_source_scoped_answer_sha256'],
        'source_scoped_plan_sha256':first['source_scope_private_plan_sha256'],
        'identical_original_generated_token_and_answer_lineage_sha256':first['output_lineage_sha256'],
        'actual_model_forward_calls_per_process':first['source_scoped_model_forwards'],
        'same_32_original_prompt_and_source_identities':True,
        'first_cpu_seconds':first['source_scoped_cpu_seconds'],
        'second_cpu_seconds':second['source_scoped_cpu_seconds'],
        'first_wall_seconds':first['source_scoped_wall_seconds'],
        'second_wall_seconds':second['source_scoped_wall_seconds'],
        'source_only_review_can_attest_independent_execution':False,
        'official_hf_numeric_parity_verified':False,
        'human_semantic_correctness':None,
        'reference_qwen_executed':False,'production_authorized':False,
        'decision':'TWO_ORIGINAL_READER_PROCESSES_IDENTICAL_OUTPUT_ONLY_HOLD_NO_GO',
    }


def check_public_repeat(result):
    wanted={'schema','first_private_result_sha256','second_private_result_sha256',
            'source_scoped_plan_sha256','identical_original_generated_token_and_answer_lineage_sha256',
            'actual_model_forward_calls_per_process','same_32_original_prompt_and_source_identities',
            'first_cpu_seconds','second_cpu_seconds','first_wall_seconds','second_wall_seconds',
            'source_only_review_can_attest_independent_execution',
            'official_hf_numeric_parity_verified','human_semantic_correctness',
            'reference_qwen_executed','production_authorized','decision'}
    if type(result) is not dict or set(result)!=wanted:
        raise ValueError('unrecognized two-process repeat receipt')
    def valid_sha(s):return type(s) is str and len(s)==64 and all(c in '0123456789abcdef' for c in s)
    if any(not valid_sha(result[x]) for x in ('first_private_result_sha256','second_private_result_sha256',
           'source_scoped_plan_sha256','identical_original_generated_token_and_answer_lineage_sha256')):
        raise ValueError('missing original private process digests')
    if result['first_private_result_sha256']==result['second_private_result_sha256']:
        raise ValueError('not distinct physical CPU-time receipts')
    if (result['source_scoped_plan_sha256']!='b6df57f17d12c01e56bf66a2c1e56a845b878838192293fd217ea0215a66a1c5'
        or type(result['actual_model_forward_calls_per_process']) is not int
        or result['actual_model_forward_calls_per_process']!=775):
        raise ValueError('invalid repeated original forwards')
    for k in ('first_cpu_seconds','second_cpu_seconds','first_wall_seconds','second_wall_seconds'):
        from math import isfinite
        if type(result[k])not in(int,float) or not isfinite(result[k]) or not 0<result[k]<3000:
            raise ValueError('invalid physical performance claim')
    if (result['schema']!=SCHEMA+'.two-process-non-authorizing-repeat'
        or result['same_32_original_prompt_and_source_identities'] is not True
        or result['source_only_review_can_attest_independent_execution'] is not False
        or result['official_hf_numeric_parity_verified'] is not False
        or result['human_semantic_correctness'] is not None
        or result['reference_qwen_executed'] is not False
        or result['production_authorized'] is not False
        or result['decision']!='TWO_ORIGINAL_READER_PROCESSES_IDENTICAL_OUTPUT_ONLY_HOLD_NO_GO'):
        raise ValueError('invented numeric/semantic/authorizing claim')
    return {'status':'SANITIZED_SOURCE_ONLY_REPEAT_RECEIPT_CONSISTENT',
            'independent_physical_execution_proven_by_this_check':False,
            'production_authorized':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--first');p.add_argument('--second')
    p.add_argument('--output');p.add_argument('--public-receipt');a=p.parse_args()
    if a.public_receipt:
        if any((a.first,a.second,a.output)):
            raise ValueError('public source-only workflow may not import private process receipts')
        print(json.dumps(check_public_repeat(read_private(a.public_receipt,50_000)),sort_keys=True));return
    if not all((a.first,a.second,a.output)):
        raise ValueError('both independently reviewed original runs required')
    result=compare(read_private(a.first,40_000),read_private(a.second,40_000))
    seal(a.output,result)
    print(json.dumps({k:v for k,v in result.items() if not k.endswith('sha256')},sort_keys=True))

if __name__=='__main__':main()
