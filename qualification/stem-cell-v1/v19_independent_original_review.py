"""Independent V19 original-source, journal, model-output and postseal recount.

No learned Cell gain, no human semantic authority and no external referee.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from v17_source_focusing import digest, htext, SENTENCE, STOP, WORD
from v19_windowed_witness import SCHEMA, ARMS, READER_SHA, TOKEN_SHA

COHORTS=('literal_in_annotated_source','not_literal_in_annotated_source')
FAMILIES=('conv-47','conv-48','conv-49','conv-50')


def source_span_independent(q, text, radius):
    """Independent lexicographic matched sentence + n-neighbor oracle; source only."""
    if type(radius) is not int or radius not in (1,2):raise ValueError('invalid radius')
    ranges=[]
    for m in SENTENCE.finditer(text):
        a,b=m.span()
        while a<b and text[a].isspace():a+=1
        while b>a and text[b-1].isspace():b-=1
        if a<b:ranges.append((a,b))
    qterms={w.casefold() for w in WORD.findall(q) if len(w)>1 and w.casefold() not in STOP}
    def score(i):
        chunk=text[ranges[i][0]:ranges[i][1]]
        row=Counter(w.casefold() for w in WORD.findall(chunk))
        return (sum(k in row for k in qterms),sum(row[k] for k in qterms),-i)
    if not ranges:raise ValueError('empty sentence list')
    idx=max(range(len(ranges)),key=score)
    return (text[ranges[max(0,idx-radius)][0]:ranges[min(len(ranges)-1,idx+radius)][1]],
            [ranges[max(0,idx-radius)][0],ranges[min(len(ranges)-1,idx+radius)][1]])


def original_prompt_independent(question, ids, docs):
    inst='Use only the numbered evidence. Give the shortest directly supported answer; cite supporting source [E1], [E2] or [E3]. If insufficient, reply exactly unknown.'
    if len(ids)!=3 or len(set(ids))!=3:raise ValueError('wrong source counts')
    rendered='\n'.join(f'[E{i}] {docs[z]}' for i,z in enumerate(ids,1))
    return ('<|im_start|>system\n'+inst+'<|im_end|>\n<|im_start|>user\nQuestion: '+question+\
            '\nComplete original source passages\n'+rendered+'\n<|im_end|>\n<|im_start|>assistant\n')


def validate_source(plan, source, ranks, v16, v17, v18):
    if (plan.get('schema')!=SCHEMA+'.source-only' or len(plan.get('cases',[]))!=32
        or len(plan.get('new_requests',{}))!=23 or plan.get('new_original_requests')!=23
        or plan.get('reused_prior_V17_slots')!=40 or plan.get('reused_prior_V18_slots')!=0
        or plan.get('duplicated_new_input_slots')!=1 or plan.get('original_historical_cohort')!=32
        or plan.get('arms')!=list(ARMS) or plan.get('max_new_tokens')!=24):raise ValueError('wrong V19 admission')
    for name, expected in [('source_sha256',digest(source)),('ranks_sha256',digest(ranks)),
                           ('v16_plan_sha256',digest(v16)),('v17_plan_sha256',digest(v17)),
                           ('v18_plan_sha256',digest(v18)),('reader_weights_sha256',READER_SHA),
                           ('reader_tokenizer_sha256',TOKEN_SHA)]:
        if plan.get(name)!=expected:raise ValueError('wrong original source pin '+name)
    if (plan.get('publisher_answers_accessed_during_planning') is not False
        or plan.get('historical_answer_conditioned_parent') is not True
        or plan.get('independent_semantic_correctness') is not None
        or plan.get('independently_reviewed_sufficient_evidence') is not False
        or plan.get('pretrained_reference_reader_executed') is not False
        or plan.get('source_independent_future_windows')!=0
        or plan.get('production_authorized') is not False
        or source.get('contains_gold_or_answers') is not False):raise ValueError('false capabilities')
    original_cases={z['case_id']:z for z in v17['cases']};known=set();expected_new={};old_count=0;dupes=0
    for case in plan['cases']:
        cid=case['case_id'];fam=case['family'];cohort=case['cohort']
        if cid in known or cid not in original_cases or fam not in FAMILIES or cohort not in COHORTS:
            raise ValueError('duplicate/foreign source case')
        known.add(cid);orig=original_cases[cid]
        if (fam!=orig['family'] or case['witness_id']!=orig['witness_id'] or
            set(case['arms'])!=set(ARMS)):raise ValueError('changed parent source identity')
        docs={z['id']:z['text'] for z in source['families'][fam]['passages']}
        qs={z['id']:z['text'] for z in source['families'][fam]['questions']}
        ids=v17['requests'][orig['arms']['formatted_full']]['source_ids']
        if cid not in qs or case['source_ids']!=ids:raise ValueError('source IDs differ from original')
        for radius,arm in ((1,ARMS[0]),(2,ARMS[1])):
            chunk,offset=source_span_independent(qs[cid],docs[case['witness_id']],radius)
            modified={**docs,case['witness_id']:chunk}
            prompt=original_prompt_independent(qs[cid],ids,modified)
            rid=htext(prompt);spec=case['arms'][arm]
            if spec['request_id']!=rid or spec['span']!=offset or spec['text_sha256']!=htext(chunk) or spec['shortened']!=(len(chunk)<len(docs[case['witness_id']].strip())):
                raise ValueError('window text/context intervention drift')
            if rid in v17['requests']:
                old_count+=1
                if spec['reuse']!='v17' or v17['requests'][rid]['prompt']!=prompt or v17['requests'][rid]['case_id']!=cid:
                    raise ValueError('false old-original-Reader request reuse')
            else:
                if spec['reuse']!='new':raise ValueError('false unmeasured V18 reuse')
                required=dict(case_id=cid,family=fam,arm=arm,prompt=prompt,source_ids=ids,
                              question_sha256=htext(qs[cid]),evidence_text_sha256=[htext(modified[x]) for x in ids])
                if rid in expected_new:
                    dupes+=1
                    if expected_new[rid]['case_id']!=cid:raise ValueError('cross-case input alias')
                else:expected_new[rid]=required
    if len(known)!=32 or len(expected_new)!=23 or old_count!=40 or dupes!=1 or plan['new_requests']!=expected_new:
        raise ValueError('incomplete full V19 request identity census')
    return expected_new


def validate_physical(plan, model, starts, v17_answers, tokenizer):
    if (model.get('schema')!=SCHEMA+'.original-physical' or model.get('plan_sha256')!=digest(plan)
        or model.get('model_sha256')!=READER_SHA or model.get('tokenizer_sha256')!=TOKEN_SHA
        or model.get('requests')!=23 or model.get('pretrained_model_executed') is not True
        or model.get('reference_reader_executed') is not False or model.get('official_HF_parity') is not False
        or model.get('production_authorized') is not False or model.get('independent_human_semantic_correctness') is not None):
        raise ValueError('wrong genuine Reader provenance')
    if v17_answers.get('plan_sha256')!=plan['v17_plan_sha256'] or v17_answers.get('requests')!=64:
        raise ValueError('prior original V17 unavailable')
    if type(starts)is not list or len(starts)!=23 or type(model.get('raw_answers'))is not dict or set(model['raw_answers'])!=set(plan['new_requests']):
        raise ValueError('incomplete original model attempt/answer census')
    seen=set();forward=ni=no=0;digests=[]
    for begin in starts:
        if type(begin)is not dict or set(begin)!={'request_id','plan_sha256','input_tokens','input_ids_sha256'}:
            raise ValueError('incorrect journal')
        rid=begin['request_id']
        if rid in seen or rid not in plan['new_requests']:raise ValueError('foreign/duplicate attempt')
        seen.add(rid);source=plan['new_requests'][rid];tokens=tokenizer.encode(source['prompt']);answer=model['raw_answers'][rid]
        if (begin['plan_sha256']!=digest(plan) or begin['input_tokens']!=len(tokens) or begin['input_ids_sha256']!=digest(tokens)
            or not 1<=len(tokens)<=1000):raise ValueError('prompt bytes/token start changed')
        ids=answer['output_ids'];decoded=tokenizer.decode(ids)
        if (type(ids)is not list or not 1<=len(ids)<=24 or any(type(k)is not int or k<0 or k>=49152 for k in ids)
            or answer['case_id']!=source['case_id'] or answer['arm']!=source['arm'] or answer['source_ids']!=source['source_ids']
            or answer['answer_text']!=decoded or answer['answer_sha256']!=htext(decoded)
            or answer['input_tokens']!=len(tokens) or answer['output_tokens']!=len(ids)
            or type(answer['cpu_seconds']) not in (int,float) or not math.isfinite(answer['cpu_seconds']) or answer['cpu_seconds']<0):
            raise ValueError('original Reader output mismatch')
        ni+=len(tokens);no+=len(ids);forward+=len(ids)+int(ids[-1]!=2)
        digests.append([rid,answer['answer_sha256'],digest(ids)])
    if forward!=model['model_forwards'] or ni!=model['input_tokens'] or no!=model['output_tokens']:
        raise ValueError('original physical forward and cost counters drifted')
    return dict(schema=SCHEMA+'.independent-byte-recount',requests=23,forwards=forward,
                input_tokens=ni,output_tokens=no,output_sha256=digest(sorted(digests)),
                original_model_locally_executed=True,original_model_external_attestation=False,
                independent_semantic_accuracy=None,production_authorized=False)


def compare_repeat(plan, a, b):
    if a['plan_sha256']!=digest(plan) or b['plan_sha256']!=digest(plan) or a['requests']!=23 or b['requests']!=23:
        raise ValueError('unrelated repeat')
    for rid in plan['new_requests']:
        for field in ('case_id','arm','source_ids','input_tokens','output_tokens','output_ids','answer_sha256','answer_text'):
            if a['raw_answers'][rid][field]!=b['raw_answers'][rid][field]:raise ValueError('different original model outputs')
    return dict(identical_requests=23,original_two_process_replay=True,outputs_identical=True,production_authorized=False)


def score_after_original_seal(plan, model, v17_answers, original, source):
    owners={item['sample_id']:item for item in original}
    if len(owners)!=10 or set(owners)!=set(source['families']):raise ValueError('publisher corpus changed')
    by_fam={k:dict(rows=0,answers_known=0) for k in FAMILIES}
    grouped={cohort:{arm:dict(total=0,answer_known=0,answer_in_source=0,
                              answer_in_output=0,output_exact=0) for arm in ARMS} for cohort in COHORTS}
    # Include original V17 full/focus arms as stable, exactly source matched controls.
    for cohort in COHORTS:
        for arm in ('v17_full_original','v17_focus_original'):
            grouped[cohort][arm]=dict(total=0,answer_known=0,answer_in_source=0,answer_in_output=0,output_exact=0)
    for case in plan['cases']:
        fam=case['family'];cid=case['case_id'];cohort=case['cohort']
        original_ans=owners[fam]['qa'][int(cid.split('/q',1)[1])].get('answer')
        known=isinstance(original_ans,str) and bool(original_ans.strip());target=original_ans.strip().casefold() if known else None
        by_fam[fam]['rows']+=1;by_fam[fam]['answers_known']+=int(known)
        docs={x['id']:x['text'] for x in source['families'][fam]['passages']}
        witness=docs[case['witness_id']]
        for arm in ARMS:
            spec=case['arms'][arm];kind=spec['reuse'];rid=spec['request_id']
            if kind=='new':output=model['raw_answers'][rid]['answer_text']
            elif kind=='v17':output=v17_answers['raw_answers'][rid]['answer_text']
            else:raise ValueError('unknown original output source')
            chunk=witness[spec['span'][0]:spec['span'][1]]
            t=grouped[cohort][arm];t['total']+=1;t['answer_known']+=int(known)
            t['answer_in_source']+=int(known and target in chunk.casefold())
            t['answer_in_output']+=int(known and target in output.casefold())
            t['output_exact']+=int(known and output.strip().casefold()==target)
    if any(v['rows']!=8 for v in by_fam.values()):raise ValueError('family denominator')
    if any(v['total']!=16 for g in grouped.values() for a,v in g.items() if a in ARMS):raise ValueError('cohort denominator')
    return dict(schema=SCHEMA+'.original-postseal-literal-audit',families=by_fam,cohorts={g:{a:z for a,z in ar.items() if a in ARMS} for g,ar in grouped.items()},
                cohort_label_outcome_conditioned_historical=True,original_publisher_labels_opened_postseal=True,
                human_semantic_correctness=None,source_sufficiency_human_verified=False,
                reference_reader_executed=False,physical_HF_parity=False,
                source_independent_future_windows=0,Cell_learning_benefit_proven=False,
                production_authorized=False,decision='NO_GO')


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--source',required=True)
    p.add_argument('--ranks',required=True);p.add_argument('--v16-plan',required=True)
    p.add_argument('--v17-plan',required=True);p.add_argument('--v18-plan',required=True)
    p.add_argument('--original-answers',required=True);p.add_argument('--starts',required=True)
    p.add_argument('--v17-answers',required=True);p.add_argument('--reader-dir',required=True)
    p.add_argument('--original-corpus',default=None);p.add_argument('--out',required=True)
    a=p.parse_args();from v17_source_focusing import read,sealed
    from v12_reader_runtime import OriginalCandidateBPE
    from v19_windowed_witness import digest
    plan=read(a.plan);source=read(a.source);ranks=read(a.ranks);v16=read(a.v16_plan);v17=read(a.v17_plan);v18=read(a.v18_plan)
    validate_source(plan,source,ranks,v16,v17,v18)
    old=read(a.v17_answers);physical=read(a.original_answers)
    starts=[json.loads(x) for x in Path(a.starts).read_text().splitlines() if x.strip()]
    tok=OriginalCandidateBPE(a.reader_dir)
    receipt=validate_physical(plan,physical,starts,old,tok)
    if a.original_corpus is not None:
        receipt['postseal']=score_after_original_seal(plan,physical,old,read(a.original_corpus),source)
    sealed(a.out,receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k!='postseal'},sort_keys=True))

if __name__=='__main__':main()
