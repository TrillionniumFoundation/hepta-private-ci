"""Independent original 135M evidence-absence guard reviewer (no model generation).

Research-only: compares 96 new physical model outputs against the frozen V22
real original output, verifies 32 exact deterministic no-evidence abstentions.
Never asserts semantic correctness, NDU or production authority. Both provenance
and private raw outputs must be verified on the machine that holds source files.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
import re
from pathlib import Path

from v21_original_plan_rebuilder import V16_PLAN_SHA, READER_SHA, TOKEN_SHA, READER_CFG_SHA, ARMS, digest, htext
from v22_original_crosshost_execute import read_private,seal,validate_inputs
from v22_original_crosshost_review import verify_raw,strict_start_lines
from v23_evidence_absence_shadow import SCHEMA,GUARD,MODEL,admitted_roster

EXPECTED_BASELINE={'none':658,'retrieved':759,'witness':767,'lesion':767}
CITES=re.compile(r'\[E(\d+)\]')


def review(plan, baseline, baseline_starts, guarded, guarded_starts, tokenizer,
           *,require_original_backend=True):
    """Re-tokenize every actual model request and compare all response bytes."""
    base=verify_raw(plan,baseline,baseline_starts,tokenizer)
    if base['verified_original_requests']!=128 or base['physical_forward_calls']!=2951:
        raise ValueError('original full-model frozen control not physical 128/2951')
    if (type(guarded)is not dict or set(guarded)!={
        'schema','plan_sha256','model_sha256','tokenizer_sha256','reader_config_sha256',
        'requests','model_requests','guard_requests','model_forwards','model_input_tokens',
        'model_output_tokens','total_cpu_seconds','total_wall_seconds','raw_answers',
        'true_pretrained_backend','reference_qwen_executed','human_semantic_correctness',
        'production_authorized'}):
        raise ValueError('unexpected guard result shape')
    if (guarded['schema']!=SCHEMA+'.sealed-private-original-answers'
        or guarded['plan_sha256']!=V16_PLAN_SHA or guarded['model_sha256']!=READER_SHA
        or guarded['tokenizer_sha256']!=TOKEN_SHA or guarded['reader_config_sha256']!=READER_CFG_SHA
        or guarded['requests']!=128 or guarded['model_requests']!=96
        or guarded['guard_requests']!=32 or guarded['reference_qwen_executed'] is not False
        or guarded['human_semantic_correctness'] is not None
        or guarded['production_authorized'] is not False
        or type(guarded['true_pretrained_backend'])is not bool
        or (require_original_backend and guarded['true_pretrained_backend'] is not True)):
        raise ValueError('unqualified original Reader experiment flags')
    if any(type(guarded[k]) not in (int,float) or not math.isfinite(guarded[k])
           or guarded[k]<=0 for k in ('total_cpu_seconds','total_wall_seconds')):
        raise ValueError('missing measured total cost')
    answers=guarded['raw_answers'];wanted=plan['requests']
    if type(answers) is not dict or set(answers)!=set(wanted):
        raise ValueError('replaced/missing model or abstention answers')
    if type(guarded_starts)is not list or len(guarded_starts)!=128:
        raise ValueError('every guarded or model request must be journaled before action')
    seen=set(); model_n=guard_n=forwards=input_tokens=output_tokens=0
    avoided=Counter(); baseline_citation_fail=0; baseline_capped=0
    lineage=[]
    for start in guarded_starts:
        if type(start)is not dict or set(start)!={
            'request_id','plan_sha256','route','input_tokens','input_ids_sha256'}:
            raise ValueError('unsafe/unknown durable attempt fields')
        rid=start['request_id']
        if type(rid)is not str or rid not in wanted or rid in seen:
            raise ValueError('duplicate/foreign guarded attempt identity')
        seen.add(rid)
        row=wanted[rid];observed=answers[rid];prior=baseline['raw_answers'][rid]
        expected_route=GUARD if row['arm']=='none' else MODEL
        if (start['plan_sha256']!=V16_PLAN_SHA or start['route']!=expected_route
            or type(observed)is not dict or set(observed)!={
                'case_id','arm','source_ids','route','answer_text','answer_sha256',
                'token_ids','input_tokens','output_tokens','model_cpu_seconds'}
            or observed['route']!=expected_route
            or (observed['case_id'],observed['arm'],observed['source_ids'])!=(row['case_id'],row['arm'],row['source_ids'])
            or type(observed['answer_text']) is not str
            or observed['answer_sha256']!=htext(observed['answer_text'])
            or type(observed['model_cpu_seconds'])not in (int,float)
            or not math.isfinite(observed['model_cpu_seconds'])
            or observed['model_cpu_seconds']<0):
            raise ValueError('changed original source/guard/result receipt')
        tokens=observed['token_ids']
        if type(tokens)is not list:
            raise ValueError('model token output list missing')
        if expected_route == GUARD:
            if (row['source_ids']!=[] or observed['answer_text']!='unknown'
                or tokens!=[] or observed['input_tokens']!=0 or observed['output_tokens']!=0
                or observed['model_cpu_seconds']!=0.0
                or start['input_ids_sha256'] is not None or start['input_tokens']!=0):
                raise ValueError('deterministic no-source abstention was bypassed')
            guard_n+=1
            actual_prior_ids=prior['token_ids']
            avoided['model_forwards']+=len(actual_prior_ids)+(actual_prior_ids[-1]!=2)
            avoided['input_tokens']+=prior['input_tokens']
            avoided['output_tokens']+=prior['output_tokens']
        else:
            inp=tokenizer.encode(row['prompt'])
            if (type(inp)is not list or not 1<=len(inp)<=1000
                or any(type(x) is not int or not 0<=x<49152 for x in inp)
                or start['input_tokens']!=len(inp) or start['input_ids_sha256']!=digest(inp)
                or observed['input_tokens']!=len(inp) or not 1<=len(tokens)<=24
                or any(type(x)is not int or not 0<=x<49152 for x in tokens)
                or observed['output_tokens']!=len(tokens)
                or observed['answer_text']!=tokenizer.decode(tokens)):
                raise ValueError('actual model prompt/token bytes failed independent replay')
            for key in ('case_id','arm','source_ids','answer_text','answer_sha256','token_ids','input_tokens','output_tokens'):
                if observed[key]!=prior[key]:
                    raise ValueError('other 96 Reader outputs changed; guard confound detected: '+key)
            model_n+=1
            forwards+=len(tokens)+(tokens[-1]!=2)
            input_tokens+=len(inp);output_tokens+=len(tokens)
        citations=CITES.findall(prior['answer_text']);source_count=len(prior['source_ids'])
        baseline_citation_fail+=int(any(not 1<=int(c)<=source_count for c in citations))
        baseline_capped+=int(len(prior['token_ids'])==24)
        lineage.append([rid,expected_route,observed['answer_sha256'],digest(tokens)])
    if (set(seen)!=set(wanted) or (guard_n,model_n)!=(32,96)
        or forwards!=guarded['model_forwards'] or forwards!=2951-658
        or input_tokens!=guarded['model_input_tokens']
        or output_tokens!=guarded['model_output_tokens']
        or avoided != {'model_forwards':658,'input_tokens':1936,'output_tokens':645}
        or baseline_citation_fail!=3 or baseline_capped!=99):
        raise ValueError('physical baseline/cost/guard census mismatch')
    return {'schema':SCHEMA+'.digest-only-physical-review-v1',
            'original_plan_sha256':V16_PLAN_SHA,
            'original_model_sha256':READER_SHA,
            'baseline_full_requests':128,
            'baseline_real_model_forwards':2951,
            'baseline_absent_evidence_nonabstentions':32,
            'baseline_unbound_citation_rows':baseline_citation_fail,
            'baseline_24_output_token_cap_reached':baseline_capped,
            'new_real_model_requests':model_n,
            'new_deterministic_no_evidence_abstentions':guard_n,
            'new_real_model_forwards':forwards,
            'saved_real_forward_calls_vs_full_control':avoided['model_forwards'],
            'saved_original_input_tokens_vs_full_control':avoided['input_tokens'],
            'saved_original_output_tokens_vs_full_control':avoided['output_tokens'],
            'new_model_input_tokens':input_tokens,'new_model_output_tokens':output_tokens,
            'all_96_original_model_outputs_identical':True,
            'total_cpu_seconds':guarded['total_cpu_seconds'],
            'total_wall_seconds':guarded['total_wall_seconds'],
            'guarded_private_result_sha256':digest(guarded),
            'baseline_private_result_sha256':digest(baseline),
            'guard_output_lineage_sha256':digest(sorted(lineage)),
            'reported_pretrained_backend':guarded['true_pretrained_backend'],
            'pretrained_execution_independently_signed':False,
            'semantic_correctness_human_reviewed':False,
            'reference_qwen_executed':False,
            'production_authorized':False,
            'decision':'SHADOW_DETERMINISTIC_ABSTENTION_NOT_LEARNING_HOLD_NO_GO'}


def check_public(r):
    """Only consistency of public aggregates, never replaces raw-data attestation."""
    fixed={'schema':SCHEMA+'.digest-only-physical-review-v1',
        'original_plan_sha256':V16_PLAN_SHA,'original_model_sha256':READER_SHA,
        'baseline_full_requests':128,'baseline_real_model_forwards':2951,
        'baseline_absent_evidence_nonabstentions':32,
        'baseline_unbound_citation_rows':3,
        'baseline_24_output_token_cap_reached':99,
        'new_real_model_requests':96,'new_deterministic_no_evidence_abstentions':32,
        'new_real_model_forwards':2293,'saved_real_forward_calls_vs_full_control':658,
        'saved_original_input_tokens_vs_full_control':1936,
        'saved_original_output_tokens_vs_full_control':645,
        'new_model_input_tokens':14328,'new_model_output_tokens':2210,
        'all_96_original_model_outputs_identical':True,
        'reported_pretrained_backend':True,
        'pretrained_execution_independently_signed':False,
        'semantic_correctness_human_reviewed':False,
        'reference_qwen_executed':False,'production_authorized':False,
        'decision':'SHADOW_DETERMINISTIC_ABSTENTION_NOT_LEARNING_HOLD_NO_GO'}
    variable=('total_cpu_seconds','total_wall_seconds',
              'guarded_private_result_sha256','baseline_private_result_sha256',
              'guard_output_lineage_sha256')
    if type(r)is not dict or set(r)!=set(fixed)|set(variable):
        raise ValueError('added private/source/model material to public receipt')
    for k,v in fixed.items():
        if type(r[k])is not type(v) or r[k]!=v:
            raise ValueError('invented Qwen/learning/authority or altered count: '+k)
    for k in variable[:2]:
        if type(r[k])not in (int,float) or not math.isfinite(r[k]) or not 0<r[k]<10000:
            raise ValueError('invalid measured complete execution time')
    for k in variable[2:]:
        t=r[k]
        if type(t) is not str or len(t)!=64 or any(c not in '0123456789abcdef' for c in t):
            raise ValueError('missing digest')
    return {'status':'V23_SOURCE_ONLY_SANITIZED_RECEIPT_VALID',
            'physical_model_execution_proven_by_this_audit':False,
            'production_authorized':False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--public-receipt')
    for k in ('plan','baseline','baseline-starts','guarded','guarded-starts','reader','receipt'):
        p.add_argument('--'+k)
    a=p.parse_args()
    if a.public_receipt:
        if any(getattr(a,k) is not None for k in ('plan','baseline','baseline_starts','guarded','guarded_starts','reader','receipt')):
            raise ValueError('private original files forbidden in public review')
        print(json.dumps(check_public(read_private(a.public_receipt,30_000)),sort_keys=True))
        return
    if any(getattr(a,k)is None for k in ('plan','baseline','baseline_starts','guarded','guarded_starts','reader','receipt')):
        raise ValueError('no partial original source/result review')
    from v12_reader_runtime import OriginalCandidateBPE,check_original
    check_original(a.reader)
    packet=review(read_private(a.plan),read_private(a.baseline,2_000_000),
                  strict_start_lines(a.baseline_starts),
                  read_private(a.guarded,2_000_000),
                  strict_start_lines(a.guarded_starts),OriginalCandidateBPE(a.reader))
    seal(a.receipt,packet)
    print(json.dumps({k:v for k,v in packet.items() if not k.endswith('sha256')},sort_keys=True))

if __name__=='__main__':main()
