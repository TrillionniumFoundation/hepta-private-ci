#!/usr/bin/env python3
"""P4 original-artifact independent stdlib recount. Research/deny-only.

All inputs are ORIGINAL archived GitHub Actions ZIPs. Does not contact network,
load a model, train a head, or treat a new parser as prospective task success.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
import zipfile

MAX_MEMBER=2000000

def fail(message):
    raise ValueError(message)

def strict_json(raw):
    def pairs(pairs):
        obj={}
        for k,v in pairs:
            if k in obj:fail('duplicate JSON key')
            obj[k]=v
        return obj
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda n:fail('nonfinite JSON '+n))

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')

def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def read_zip(path, expected):
    with zipfile.ZipFile(path) as z:
        members=z.infolist()
        if {i.filename for i in members} != set(expected) or len(members)!=len(expected):fail('original artifact inventory drift: '+str(path))
        for i in members:
            if i.is_dir() or i.file_size>MAX_MEMBER or i.file_size<1 or i.filename.startswith('/') or '..' in Path(i.filename).parts:fail('unsafe original zip member')
        return {i.filename:strict_json(z.read(i)) if i.filename.endswith('.json') else z.read(i).decode().splitlines() for i in members}

def interpret_raw_after_the_fact(text):
    # DIAGNOSTIC only. Original predeclared strict scorer REJECTED angle syntax.
    m=re.fullmatch(r'\s*(?:FINAL\s*[:=]\s*)?(?:([0-3])|<([0-3])>)\s*',text)
    if not m:return None
    return int(m.group(1) if m.group(1) is not None else m.group(2))

def audit(public_zip, truth_zip, original_zip, review_zip):
    public=read_zip(public_zip,['train-public.json','held-public.json'])
    truth=read_zip(truth_zip,['held-private-labels.json'])['held-private-labels.json']
    original=read_zip(original_zip,['completed-original.json','frozen-plan.json','original-starts-and-dones.jsonl'])
    review=read_zip(review_zip,['hepta-p4-sanitized-review.json'])['hepta-p4-sanitized-review.json']
    completed=original['completed-original.json'];plan=original['frozen-plan.json']
    train=public['train-public.json'];held=public['held-public.json']
    if sha(train)!=plan['train_source_sha256'] or sha(held)!=plan['held_public_sha256']:fail('public TRAIN/held integrity')
    if sha(truth)!=review['original_publisher_gold_sha256']:fail('postseal original truth integrity')
    if sha(plan)!=completed['frozen_plan_sha256'] or sha(plan)!=review['frozen_plan_sha256']:fail('frozen plan SHA drift')
    if sha(completed)!=review['completed_original_sha256']:fail('original completed SHA drift')
    if plan['portfolio_attempt']['seal_sha256']!=sha(plan['portfolio_attempt']['attempt']):fail('P1 original selection seal drift')
    if completed['schema']!='hepta.ndu-merton.p4.equal-cap-thinking-control.v1.completed-original' or review['authority']!='RESEARCH_ONLY_DENY_ALL':fail('research schema/authority mismatch')
    train_rows=completed['original_train_trace'];served=completed['actual_policy_trace'];pairs=completed['paired_equalcap_trace']
    if [len(train_rows),len(served),len(pairs)]!=[48,56,16]:fail('wrong original 48/56/16 census')
    if completed['total_generation_invocations']!=120 or review['physical_on_policy_generation_invocations_self_reported']!=120:fail('wrong call count')
    if sha(train_rows)!=completed['train_original_sha256'] or sha(train_rows)!=plan['train_original_outputs_sha256']:fail('train original output drift')
    labels={r['task_id']:r['label'] for r in truth['rows']}
    train_labels={r['task_id']:r['label'] for r in train['rows']}
    if set(labels)!={r['task_id'] for r in held['rows']}:fail('test truth IDs drift')
    if set(train_labels)!={r['task_id'] for r in train['rows']}:fail('TRAIN IDs drift')
    if 'label' in str(held):fail('test label leaked to public model packet')
    schedule=plan['selected_request_schedule'];pair_schedule=plan['paired_equalcap_schedule']
    if len(schedule)!=56 or len(pair_schedule)!=16:fail('frozen schedule length')
    if [(r['policy'],r['task_id'],r['action']) for r in served] != [(r['policy'],r['task_id'],r['action']) for r in schedule]:fail('selected physical order drift')
    if [(r['policy'],r['task_id'],r['action']) for r in pairs] != [(r['policy'],r['task_id'],r['action']) for r in pair_schedule]:fail('paired physical order drift')
    original_logs=original['original-starts-and-dones.jsonl']
    parsed_logs=[strict_json(x) for x in original_logs]
    idx=0
    def require(wanted):
        nonlocal idx
        if idx>=len(parsed_logs) or parsed_logs[idx]!=wanted:fail('original log not exact at '+str(idx))
        idx+=1
    for r in train_rows:
        part={k:r[k] for k in ('task_id','action')};part['stage']='train'
        require({'event':'start',**part});require({'event':'done',**part,'output_sha256':sha(r)})
    require({'event':'plan_frozen','sha256':sha(plan)})
    for n,r in enumerate(served):
        part={'stage':'held','policy':r['policy'],'task_id':r['task_id'],'action':r['action'],'plan_sha256':sha(plan)}
        require({'event':'start',**part});require({'event':'done',**part,'output_sha256':sha(r)})
        if (n+1)%7==0:
            for pair in pairs[2*(n//7):2*(n//7)+2]:
                part={'stage':'contrast','policy':pair['policy'],'task_id':pair['task_id'],'action':pair['action'],'plan_sha256':sha(plan)}
                require({'event':'start',**part});require({'event':'done',**part,'output_sha256':sha(pair)})
    if idx!=len(parsed_logs):fail('unconsumed/fabricated original journal entries')
    for stage,rows in [('train',train_rows),('held',served),('pair',pairs)]:
        for x in rows:
            if x['source_kind']!='original_physical':fail('fixture substituted in original '+stage)
            if x['answer_sha256']!=hashlib.sha256(x['answer'].encode()).hexdigest():fail('answer tamper '+stage)
            if type(x['predicted_class']) is not int and x['predicted_class'] is not None:fail('prediction type')
            if x['input_tokens']<1 or x['output_tokens']<1:fail('missing meter')
    trained=Counter((r['action'],r['success']) for r in plan['train_record']['rows'])
    if any(k[1]!=0 for k in trained):fail('unexpected effective TRAIN decisions')
    results={}
    for p in plan['portfolio_attempt']['attempt']['policies']:
        name=p['policy']; rows=[r for r in served if r['policy']==name]
        if len(rows)!=8:fail('missing held policy arm')
        official=sum(r['predicted_class']==labels[r['task_id']] for r in rows)
        counted=sum(r['input_tokens']+r['output_tokens'] for r in rows)
        match=next(x for x in review['seven_policy_results'] if x['policy']==name)
        if (official,counted)!=(match['correct'],match['actual_full_input_and_output_tokens']):fail('independent P4 score/cost mismatch: '+name)
        results[name]={'official_correct':official,'n':8,'original_full_tokens':counted,'generated_tokens':sum(r['output_tokens'] for r in rows),'diagnostic_angle_parser_correct_posthoc':sum(interpret_raw_after_the_fact(r['answer'])==labels[r['task_id']] for r in rows),'actual_wall_seconds':sum(r['measured_wall_seconds'] for r in rows),'actual_cpu_seconds':sum(r['measured_cpu_seconds'] for r in rows)}
    paired={}
    for mode in ['reason','reason_equalcap']:
        rows=[r for r in pairs if r['action']==mode]
        match=next(x for x in review['paired_equalcap_96_token_contrast']['thinking_mode_vs_equalcap_nonthinking'] if x['action']==mode)
        if len(rows)!=8 or sum(r['predicted_class']==labels[r['task_id']] for r in rows)!=match['correct'] or sum(r['output_tokens'] for r in rows)!=match['total_generated_tokens']:fail('independent pair mismatch')
        paired[mode]={'official_correct':match['correct'],'calls':8,'output_tokens':match['total_generated_tokens'],'thinking_tokens':match['total_thinking_tokens'],'unfinished_thinking':match['incomplete_thinking'],'cpu_seconds':match['cpu_seconds'],'wall_seconds':match['wall_seconds'],'diagnostic_angle_parser_correct_posthoc':sum(interpret_raw_after_the_fact(r['answer'])==labels[r['task_id']] for r in rows)}
    afterhoc_train=Counter((r['action'],interpret_raw_after_the_fact(r['answer'])==train_labels[r['task_id']]) for r in train_rows)
    raw=Counter(r['answer'] for r in (train_rows+served+pairs))
    missing={x['task_id'] for x in train['rows']} & set(labels)
    if missing:fail('overlapping TRAIN and held IDs')
    return {'schema':'hepta.p4.negative-independent-audit.v1','source':'original_sha_pinned_public_Qwen3_model','original_real_model_calls_self_reported':120,'journal_entries_verified':idx,'train_calls':48,'held_policy_calls':56,'paired_diagnostic_calls':16,'gold_distribution':dict(Counter(str(x) for x in labels.values())),'TRAIN_strict_successes':sum(x['success'] for x in plan['train_record']['rows']),'TRAIN_posthoc_bracket_decoder_true_by_action':{a:afterhoc_train[(a,True)] for a in ['direct','reason','verify']},'original_outputs_by_raw_answer':dict(raw),'strict_P4_policies':results,'matched_96_cap':paired,'review_sha256':sha(review),'plan_sha256':sha(plan),'original_completed_sha256':sha(completed),'status':'NEGATIVE_NO_NDU_LIFT_STRICT_SCORER_ZERO','note':'Posthoc bracket decoding is DIAGNOSTIC ONLY and MUST NOT be substituted for the original sealed evaluator or claimed prospective accuracy. Historical labels already public.','production_accepted':False,'authority':'RESEARCH_ONLY_DENY_ALL'}

def main():
    p=argparse.ArgumentParser()
    for k in ['public','truth','original','review','output']:p.add_argument('--'+k,required=True)
    a=p.parse_args()
    res=audit(a.public,a.truth,a.original,a.review)
    with open(a.output,'x',encoding='utf8') as f:
        json.dump(res,f,ensure_ascii=False,sort_keys=True,indent=2)
        f.write('\n')
    print(json.dumps({k:res[k] for k in ('original_real_model_calls_self_reported','journal_entries_verified','TRAIN_strict_successes','gold_distribution','status')},sort_keys=True))

if __name__=='__main__':main()
