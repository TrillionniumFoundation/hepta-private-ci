"""Separate-source audit of two complete original 135M physical processes.

Different process CPU clocks/host reports are expected. Only actual original
prompt, answer bytes, token IDs and complete question/source census are compared.
No Qwen, no semantic correctness, no independent host authority.
"""
from __future__ import annotations
import argparse
import json
from v21_original_plan_rebuilder import V16_PLAN_SHA,digest
from v22_original_crosshost_execute import read_private,seal
from v22_original_crosshost_review import verify_raw,strict_start_lines

SCHEMA='hepta.stem.v22.real-original-135m-double-process.bytes-only.shadow.v1'


def compare(plan,first,first_starts,second,second_starts,tokenizer):
    a=verify_raw(plan,first,first_starts,tokenizer)
    b=verify_raw(plan,second,second_starts,tokenizer)
    if (a['actual_answer_token_lineage_sha256']!=b['actual_answer_token_lineage_sha256']
        or a['verified_original_requests']!=128 or b['verified_original_requests']!=128
        or a['physical_forward_calls']!=b['physical_forward_calls']):
        raise ValueError('two original physical processes disagree')
    keys=('case_id','arm','source_ids','answer_text','answer_sha256',
          'token_ids','input_tokens','output_tokens')
    x=first['raw_answers'];y=second['raw_answers']
    if set(x)!=set(y):raise ValueError('original case/source mismatch')
    for rid in x:
        if any(x[rid][k]!=y[rid][k] for k in keys):
            raise ValueError('original token, question, evidence or output drift')
    return {'schema':SCHEMA,'original_plan_sha256':V16_PLAN_SHA,
            'separate_processes':2,'complete_original_requests_per_process':128,
            'actual_model_forwards_per_process':a['physical_forward_calls'],
            'total_physical_model_forwards':a['physical_forward_calls']+b['physical_forward_calls'],
            'common_exact_token_answer_lineage_sha256':a['actual_answer_token_lineage_sha256'],
            'first_private_result_sha256':a['private_original_result_sha256'],
            'second_private_result_sha256':b['private_original_result_sha256'],
            'first_cpu_seconds':first['execution_cpu_seconds'],
            'second_cpu_seconds':second['execution_cpu_seconds'],
            'first_wall_seconds':first['execution_wall_seconds'],
            'second_wall_seconds':second['execution_wall_seconds'],
            'byte_identical_original_responses':True,
            'original_checkpoint_issuer_authenticated':False,
            'official_hf_operator_parity':False,
            'new_qwen_reference_forwards':0,
            'independent_semantic_correctness':None,
            'production_authorized':False,
            'decision':'ORIGINAL_135M_BYTE_REPEATABLE_ONLY_HOLD_NO_GO'}



def verify_public_repeat(r):
    """Aggregate check does NOT execute a model or authenticate its compute."""
    static={'schema':SCHEMA,'original_plan_sha256':V16_PLAN_SHA,
            'separate_processes':2,'complete_original_requests_per_process':128,
            'actual_model_forwards_per_process':2951,'total_physical_model_forwards':5902,
            'byte_identical_original_responses':True,
            'original_checkpoint_issuer_authenticated':False,
            'official_hf_operator_parity':False,
            'new_qwen_reference_forwards':0,
            'independent_semantic_correctness':None,
            'production_authorized':False,
            'decision':'ORIGINAL_135M_BYTE_REPEATABLE_ONLY_HOLD_NO_GO'}
    dynamic=('common_exact_token_answer_lineage_sha256','first_private_result_sha256',
             'second_private_result_sha256','first_cpu_seconds','second_cpu_seconds',
             'first_wall_seconds','second_wall_seconds')
    if type(r)is not dict or set(r)!=set(static)|set(dynamic):
        raise ValueError('unrecognized public original repeat report')
    for k,value in static.items():
        if type(r[k])is not type(value) or r[k]!=value:
            raise ValueError('false original model duplicate-run claim')
    for k in dynamic[:3]:
        value=r[k]
        if type(value)is not str or len(value)!=64 or any(ch not in '0123456789abcdef' for ch in value):
            raise ValueError('invalid sealed original byte identity')
    import math
    for k in dynamic[3:]:
        value=r[k]
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<10000:
            raise ValueError('missing actual per-process CPU or wall measurement')
    return {'status':'TWO_REPORTED_PROCESSES_DIGEST_CONSISTENT_ONLY',
            'pretrained_model_forward_independently_attested_by_this_check':False,
            'reference_qwen_executed':False,'production_authorized':False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--public-receipt')
    for field in ('plan','first','second','first-starts','second-starts','reader','receipt'):
        p.add_argument('--'+field)
    x=p.parse_args()
    if x.public_receipt:
        if any(getattr(x,k) is not None for k in ('plan','first','second','first_starts','second_starts','reader','receipt')):
            raise ValueError('public source-only repeated audit must not load private files')
        print(json.dumps(verify_public_repeat(read_private(x.public_receipt,30_000)),sort_keys=True))
        return
    if any(getattr(x,k) is None for k in ('plan','first','second','first_starts','second_starts','reader','receipt')):
        raise ValueError('all two physical process files must be bound')
    from v12_reader_runtime import OriginalCandidateBPE,check_original
    check_original(x.reader)
    packet=compare(read_private(x.plan),read_private(x.first,2_000_000),
                   strict_start_lines(x.first_starts),
                   read_private(x.second,2_000_000),
                   strict_start_lines(x.second_starts),
                   OriginalCandidateBPE(x.reader))
    seal(x.receipt,packet)
    print(json.dumps({k:v for k,v in packet.items() if 'private_result' not in k},sort_keys=True))

if __name__=='__main__':main()
