"""Model-free independent per-token recount and retrospective weak-label audit.

Run ONLY after physically sealed V22 original 135M outputs. Original gold is
reopened in a separate reviewer process; no human semantic accuracy is inferred.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from v21_original_plan_rebuilder import (
    ARMS, GROUPS, HELD, V16_PLAN_SHA, READER_SHA, TOKEN_SHA,
    READER_CFG_SHA, digest, htext, rebuild, canonical,
)

SCHEMA='hepta.stem.v16.original-literal-answer-witness.shadow.v1'
LABELS='hepta.stem.v22.real-135m-crosshost-weak-label-audit.shadow.v1'
ORIGINAL_STATS={
  GROUPS[0]:{'none':0,'retrieved':0,'witness':8,'lesion':0},
  GROUPS[1]:{'none':0,'retrieved':1,'witness':0,'lesion':1}}


def verify_raw(plan,raw,starts,tokenizer):
    """No model inference; checks complete actual serialized tokens and starts."""
    if type(plan)is not dict or digest(plan)!=V16_PLAN_SHA or len(plan.get('requests',{}))!=128:
        raise ValueError('original plan not the frozen V16 inputs')
    if (type(raw)is not dict or set(raw)!={
            'schema','plan_sha256','model_sha256','tokenizer_sha256','reader_config_sha256',
            'model_forwards','requests','raw_answers','execution_cpu_seconds',
            'execution_wall_seconds','stronger_reference_reader_executed',
            'human_verified_sufficiency','independent_semantic_correctness',
            'hf_operator_tokenizer_parity','production_authorized'}
        or raw['schema']!=SCHEMA+'.actual-original-reader-results'
        or raw['plan_sha256']!=V16_PLAN_SHA or raw['model_sha256']!=READER_SHA
        or raw['tokenizer_sha256']!=TOKEN_SHA or raw['reader_config_sha256']!=READER_CFG_SHA
        or raw['stronger_reference_reader_executed'] is not False
        or raw['human_verified_sufficiency'] is not False
        or raw['independent_semantic_correctness'] is not None
        or raw['hf_operator_tokenizer_parity'] is not False
        or raw['production_authorized'] is not False):
        raise ValueError('false full Reader provenance or authority')
    requests=plan['requests'];out=raw.get('raw_answers')
    if (type(out)is not dict or set(out)!=set(requests)
        or type(raw['requests'])is not int or raw['requests']!=128
        or type(starts)is not list or len(starts)!=128):
        raise ValueError('incomplete original physical answer or start census')
    for field in ('execution_cpu_seconds','execution_wall_seconds'):
        x=raw[field]
        if type(x) not in (float,int) or not math.isfinite(x) or x<=0:
            raise ValueError('nonphysical aggregate runtime')
    identities=set();model_forwards=input_count=output_count=0;digests=[]
    for start in starts:
        if type(start)is not dict or set(start)!={'request_id','plan_sha256','input_ids_sha256','input_token_count'}:
            raise ValueError('invalid durable start row')
        rid=start['request_id']
        if type(rid)is not str or rid not in requests or rid in identities:
            raise ValueError('duplicate, foreign or omitted start')
        identities.add(rid)
        req=requests[rid];ans=out[rid]
        token_ids=tokenizer.encode(req['prompt'])
        if (type(token_ids)is not list or not 1<=len(token_ids)<=1000
            or any(type(k)is not int or not 0<=k<49152 for k in token_ids)
            or start['plan_sha256']!=V16_PLAN_SHA
            or start['input_ids_sha256']!=digest(token_ids)
            or start['input_token_count']!=len(token_ids)):
            raise ValueError('model prompt tokenization or physical start drift')
        if (type(ans)is not dict or set(ans)!={'case_id','arm','source_ids','answer_text',
                 'answer_sha256','token_ids','input_tokens','output_tokens','cpu_seconds'}
            or (ans['case_id'],ans['arm'],ans['source_ids']) !=
                (req['case_id'],req['arm'],req['source_ids'])
            or type(ans['token_ids'])is not list or not 1<=len(ans['token_ids'])<=24
            or any(type(i)is not int or not 0<=i<49152 for i in ans['token_ids'])
            or type(ans['answer_text'])is not str
            or ans['answer_text']!=tokenizer.decode(ans['token_ids'])
            or ans['answer_sha256']!=htext(ans['answer_text'])
            or type(ans['input_tokens'])is not int or ans['input_tokens']!=len(token_ids)
            or type(ans['output_tokens'])is not int or ans['output_tokens']!=len(ans['token_ids'])
            or type(ans['cpu_seconds']) not in (int,float)
            or not math.isfinite(ans['cpu_seconds']) or ans['cpu_seconds']<0):
            raise ValueError('model answer token, source or CPU corruption')
        seq=ans['token_ids']
        model_forwards+=len(seq)+(seq[-1]!=2)
        input_count+=len(token_ids);output_count+=len(seq)
        digests.append([rid,digest(seq),ans['answer_sha256']])
    if identities!=set(requests) or type(raw['model_forwards'])is not int or raw['model_forwards']!=model_forwards:
        raise ValueError('model forward count or request census incomplete')
    return {'verified_original_requests':128,'physical_forward_calls':model_forwards,
            'input_tokens':input_count,'output_tokens':output_count,
            'actual_answer_token_lineage_sha256':digest(sorted(digests)),
            'private_original_result_sha256':digest(raw),
            'model_operator_hf_parity_verified':False,
            'independent_semantic_correctness':None,
            'stronger_reference_reader_executed':False,
            'production_authorized':False}


def weak_label_review(plan,raw,original):
    """Publisher-answer literal substring only; five missing answers are censored."""
    if len(plan['cases'])!=32 or type(original)is not list or len(original)!=10:
        raise ValueError('wrong original historical cohorts')
    original_by_fam={x['sample_id']:x for x in original}
    if len(original_by_fam)!=10:raise ValueError('duplicate original family')
    counters={group:{a:{'cases':0,'known':0,'unknown':0,
                          'substring':0,'exact':0} for a in ARMS} for group in GROUPS}
    per_root={f:0 for f in HELD}
    for case in plan['cases']:
        cohort=case['cohort'];fam=case['family']
        if cohort not in GROUPS or fam not in per_root:raise ValueError('foreign original cohort')
        per_root[fam]+=1
        idx=int(case['id'].split('/q')[1])
        target=original_by_fam[fam]['qa'][idx].get('answer')
        if target is not None and type(target)is not str:
            raise ValueError('nonstring publisher answer not scoreable')
        known=type(target)is str and bool(target.strip())
        for arm in ARMS:
            row=raw['raw_answers'][case['arms'][arm]['request_id']]
            cnt=counters[cohort][arm];cnt['cases']+=1
            if not known:
                cnt['unknown']+=1
                continue
            cnt['known']+=1
            text=row['answer_text'].strip().casefold();gold=target.strip().casefold()
            cnt['substring']+=int(gold in text)
            cnt['exact']+=int(text==gold)
    if per_root!={f:8 for f in HELD}:
        raise ValueError('claim of 32 independent roots instead of four')
    for group in GROUPS:
        for arm in ARMS:
            n=counters[group][arm]
            if n['cases']!=16 or n['known']+n['unknown']!=16:
                raise ValueError('missing historical cohort/arm')
    matched=all(counters[g][a]['substring']==ORIGINAL_STATS[g][a]
                and counters[g][a]['exact']==0
                for g in GROUPS for a in ARMS)
    return {'per_cohort_arm':counters,'per_correlated_root_case_counts':per_root,
            'historical_v16_weak_substring_counts':ORIGINAL_STATS,
            'historical_v16_weak_counts_match_current_host':matched,
            'historical_cohort_selection_answer_dependent':True,
            'historical_unique_source_roots':4,'future_windows':0,
            'human_evidence_sufficiency_verified':False,
            'independent_semantic_correctness':None,
            'production_authorized':False}


def strict_start_lines(path):
    data=Path(path).read_bytes()
    if not data or len(data)>120_000:raise ValueError('unbounded original start journal')
    def pairs(rows):
        d={}
        for k,v in rows:
            if k in d:raise ValueError('duplicate start key')
            d[k]=v
        return d
    return [json.loads(line,object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite start')))
            for line in data.splitlines() if line.strip()]



def verify_public_receipt(r):
    """Source-only gate: checks sanitized prior observation, NOT original model bytes."""
    fixed={
        'schema':LABELS,'original_plan_sha256':V16_PLAN_SHA,
        'verified_original_requests':128,'physical_forward_calls':2951,
        'input_tokens':16264,'output_tokens':2855,
        'model_operator_hf_parity_verified':False,
        'independent_semantic_correctness':None,
        'stronger_reference_reader_executed':False,
        'production_authorized':False,
        'per_correlated_root_case_counts':{fam:8 for fam in HELD},
        'historical_v16_weak_substring_counts':ORIGINAL_STATS,
        'historical_v16_weak_counts_match_current_host':True,
        'historical_cohort_selection_answer_dependent':True,
        'historical_unique_source_roots':4, 'future_windows':0,
        'human_evidence_sufficiency_verified':False,
        'gold_opened_only_after_model_result':True,
        'model_is_frozen_original_135m':True,
        'reference_qwen_128_calls':0,
        'decision':'PHYSICAL_135M_REPLAY_ONLY_HOLD_NO_GO'}
    dynamic={'actual_answer_token_lineage_sha256','private_original_result_sha256',
             'per_cohort_arm'}
    if type(r)is not dict or set(r)!=set(fixed)|dynamic:
        raise ValueError('public original replay report shape changed')
    for field,value in fixed.items():
        if type(r[field]) is not type(value) or r[field]!=value:
            raise ValueError('inflated or corrupted physical original profile: '+field)
    for field in ('actual_answer_token_lineage_sha256','private_original_result_sha256'):
        x=r[field]
        if type(x) is not str or len(x)!=64 or any(c not in '0123456789abcdef' for c in x):
            raise ValueError('invalid original receipt byte identity')
    t=r['per_cohort_arm']
    if type(t)is not dict or set(t)!=set(GROUPS):
        raise ValueError('missing historical cohort')
    for cohort in GROUPS:
        if type(t[cohort])is not dict or set(t[cohort])!=set(ARMS):
            raise ValueError('missing paired original condition')
        for arm in ARMS:
            row=t[cohort][arm]
            n_known=16 if cohort==GROUPS[0] else 11
            n_unknown=16-n_known
            expected={'cases':16,'known':n_known,'unknown':n_unknown,
                      'substring':ORIGINAL_STATS[cohort][arm], 'exact':0}
            if row != expected or any(type(row[k])is not int for k in expected):
                raise ValueError('historical original weak label count changed')
    return {'status':'SANITIZED_REAL_MODEL_REPORT_CONSISTENT_ONLY',
            'original_model_forward_independently_attested_by_this_check':False,
            'human_semantic_correctness_verified':False,
            'qwen_reference_executed':False,'production_authorized':False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--public-receipt')
    for field in ('original','source','routes','plan','answers','starts','reader','receipt'):
        p.add_argument('--'+field)
    x=p.parse_args()
    if x.public_receipt:
        if any(getattr(x,k) is not None for k in ('original','source','routes','plan','answers','starts','reader','receipt')):
            raise ValueError('public source-only checking must not access private data')
        from v22_original_crosshost_execute import read_private
        public=read_private(x.public_receipt,cap=30_000)
        print(json.dumps(verify_public_receipt(public),sort_keys=True))
        return
    if any(getattr(x,k) is None for k in ('original','source','routes','plan','answers','starts','reader','receipt')):
        raise ValueError('complete private physical-review input set required')
    # Gold enters this reviewer after the complete physical answer was sealed.
    report,source,routes,plan=rebuild(x.original)
    from v22_original_crosshost_execute import read_private,seal,validate_inputs
    if (source!=read_private(x.source) or routes!=read_private(x.routes)
        or plan!=read_private(x.plan) or not validate_inputs(source,routes,plan)):
        raise ValueError('original publisher/source/route/input binding failed')
    raw=read_private(x.answers,cap=2_000_000)
    from v12_reader_runtime import OriginalCandidateBPE,check_original
    check_original(x.reader)
    reviewer=verify_raw(plan,raw,strict_start_lines(x.starts),OriginalCandidateBPE(x.reader))
    weak=weak_label_review(plan,raw,
        __import__('v21_original_plan_rebuilder').read_original(x.original))
    result={'schema':LABELS,'original_plan_sha256':V16_PLAN_SHA,
            **reviewer,**weak,'gold_opened_only_after_model_result':True,
            'model_is_frozen_original_135m':True,
            'reference_qwen_128_calls':0,'decision':'PHYSICAL_135M_REPLAY_ONLY_HOLD_NO_GO'}
    seal(x.receipt,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('per_cohort_arm',)},sort_keys=True))

if __name__=='__main__':main()
