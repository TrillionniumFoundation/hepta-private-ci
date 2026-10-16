"""V17: source-bound Reader representation A/B with the *original* model.

Same 32 V16 cases; answer-dependent RETROSPECTIVE sample. New intervention is
label-blind question-token lexical focusing of a witness, not a new learnt Cell.
No stronger reference Reader / independent human sufficiency / main promotion.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import time

from v16_literal_witness_reader import (
    read, sealed, digest, htext, validate as validate_v16, SCHEMA as PARENT_SCHEMA,
    READER_SHA, TOKEN_SHA, READER_CFG_SHA,
)
from v15_original_candidate_four_arm import source_and_rank, CORPUS_SHA

SCHEMA = 'hepta.stem.v17.original-source-focusing.shadow.v1'
ARMS = ('formatted_full', 'formatted_focused')
ANSWER_CAP = 24
WORD = re.compile(r'\w+', re.UNICODE)
SENTENCE = re.compile(r'[^.!?;\n]+(?:[.!?;]+|$)', re.UNICODE)
STOP = frozenset('the a an and or to in at on by with of for what when where who why how did does is was were are had has have from as it that this they you which'.split())


def selected_sentences(question: str, passage: str):
    """Return exact verbatim source spans, never trained/gold-selected text."""
    if type(question) is not str or type(passage) is not str or not question.strip() or not passage.strip() or len(passage)>3000:
        raise ValueError('missing/oversized original source')
    candidates=[]
    for match in SENTENCE.finditer(passage):
        if match.group().strip():
            start,end=match.span()
            # Preserve the exact source spelling; whitespace padding is not a fact.
            while start<end and passage[start].isspace():start+=1
            while end>start and passage[end-1].isspace():end-=1
            if start<end:candidates.append((start,end,passage[start:end]))
    if not candidates:raise ValueError('no finite original sentence span')
    q={word.casefold() for word in WORD.findall(question) if word.casefold() not in STOP and len(word)>1}
    ranked=[]
    for i,(_,_,text) in enumerate(candidates):
        tf=Counter(t.casefold() for t in WORD.findall(text))
        ranked.append((sum(1 for term in q if term in tf),sum(tf[term] for term in q),-i,i))
    best=max(ranked)[-1]
    start,end,selected=candidates[best]
    if selected not in passage or passage[start:end]!=selected:raise ValueError('false source span')
    return selected, [start,end],len(candidates)


def original_prompt(question, source_ids, text_by_id, *, focused):
    if type(source_ids)is not list or len(source_ids)!=3 or len(set(source_ids))!=3:
        raise ValueError('exactly three original source IDs')
    if any(type(z)!=str or z not in text_by_id for z in source_ids):raise ValueError('foreign evidence')
    if type(question)!=str or not question.strip():raise ValueError('missing original question')
    instruction=('Use only the numbered evidence. Give the shortest directly supported answer; '
                 'cite supporting source [E1], [E2] or [E3]. If insufficient, reply exactly unknown.')
    section='Relevant sentence selected by question-only lexical overlap' if focused else 'Complete original source passages'
    evidence='\n'.join(f'[E{i}] {text_by_id[s]}' for i,s in enumerate(source_ids,1))
    return ('<|im_start|>system\n'+instruction+'<|im_end|>\n'
            '<|im_start|>user\nQuestion: '+question+'\n'+section+'\n'
            +evidence+'\n<|im_end|>\n<|im_start|>assistant\n')


def build(src, ranks, parent):
    validate_v16(parent,src,ranks)
    if parent.get('schema')!=PARENT_SCHEMA+'.answer-dependent-precommitted-plan':raise ValueError('wrong precommitted parent')
    if parent['reader_sha256']!=READER_SHA or parent['tokenizer_sha256']!=TOKEN_SHA:raise ValueError('Reader identity')
    bycase=source_and_rank(src,ranks)
    cases=[];requests={};with_shrink=0
    for case in parent['cases']:
        fam=case['family'];qid=case['id'];wid=case['witness_id']
        docs={d['id']:d['text'] for d in src['families'][fam]['passages']}
        qs={q['id']:q['text'] for q in src['families'][fam]['questions']}
        if qid not in bycase or qid not in qs or wid not in docs:raise ValueError('tampered original case')
        source_ids=case['arms']['witness']['evidence_ids']
        if source_ids!=[wid,*case['arms']['lesion']['evidence_ids']]:raise ValueError('source membership changed')
        q=qs[qid]
        focus,off,n=selected_sentences(q,docs[wid])
        shrunk=focus!=docs[wid].strip()
        with_shrink+=int(shrunk)
        rec={'case_id':qid,'family':fam,'cohort':case['cohort'],'witness_id':wid,
             'n_original_sentences':n,'focus_offsets':off,'focus_changed':shrunk,'arms':{}}
        for arm in ARMS:
            modified=docs.copy()
            if arm=='formatted_focused':modified[wid]=focus
            prompt=original_prompt(q,source_ids,modified,focused=arm=='formatted_focused')
            rid=htext(prompt)
            if rid in requests:raise ValueError('colliding original model requests')
            row={'case_id':qid,'family':fam,'arm':arm,'source_ids':source_ids,
                 'question_sha256':htext(q),'evidence_text_sha256':[htext(modified[z]) for z in source_ids],
                 'prompt':prompt}
            requests[rid]=row
            rec['arms'][arm]=rid
        cases.append(rec)
    plan={'schema':SCHEMA+'.source-only-plan','parent_v16_plan_sha256':digest(parent),
          'source_sha256':digest(src),'bm25_sha256':digest(ranks),
          'reader_weights_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
          'reader_config_sha256':READER_CFG_SHA,'dataset_sha256':CORPUS_SHA,
          'arms':list(ARMS),'max_new_tokens':ANSWER_CAP,'cases':cases,'requests':requests,
          'source_changed_cases':with_shrink,'retrospective_answer_dependent_parent':True,
          'new_focus_uses_publisher_answers':False,'human_verified_sufficient':False,
          'stronger_reference_reader_executed':False,'future_calendar_windows':0,
          'production_authorized':False}
    if len(cases)!=32 or len(requests)!=64 or len({x['case_id'] for x in cases})!=32:raise ValueError('case count')
    return plan


def verify_plan(plan,src,ranks,parent):
    rebuilt=build(src,ranks,parent)
    if plan!=rebuilt:raise ValueError('original V17 question/source intervention mutated')
    return rebuilt


def physical_run(plan,src,ranks,parent,reader_dir,output):
    from v12_reader_runtime import check_original, OriginalCandidateBPE, OriginalCandidateLlama
    import torch
    verify_plan(plan,src,ranks,parent)
    check_original(reader_dir)
    tok=OriginalCandidateBPE(reader_dir)
    torch.set_num_threads(2)
    model=OriginalCandidateLlama(reader_dir)
    out=Path(output); starts=Path(str(out)+'.starts.jsonl')
    if out.exists() or starts.exists():raise FileExistsError('create-only originals')
    answers={};t0=time.process_time();w0=time.perf_counter()
    with starts.open('x',encoding='utf8') as journal:
        for rid,row in sorted(plan['requests'].items()):
            ids=tok.encode(row['prompt'])
            if not 1<=len(ids)<=1000:raise ValueError('Reader context limit without truncation')
            start={'request_id':rid,'plan_sha256':digest(plan),'input_tokens':len(ids),
                   'input_ids_sha256':digest(ids)}
            journal.write(json.dumps(start,sort_keys=True)+'\n');journal.flush();os.fsync(journal.fileno())
            tp=time.process_time();token_ids=model.generate(ids,max_tokens=ANSWER_CAP)
            text=tok.decode(token_ids)
            answers[rid]={'case_id':row['case_id'],'arm':row['arm'],'source_ids':row['source_ids'],
                         'answer_text':text,'answer_sha256':htext(text),'output_ids':token_ids,
                         'input_tokens':len(ids),'output_tokens':len(token_ids),
                         'cpu_seconds':time.process_time()-tp}
    result={'schema':SCHEMA+'.original-physical-answers','plan_sha256':digest(plan),
            'model_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
            'model_forwards':model.calls,'requests':len(answers),'raw_answers':answers,
            'cpu_seconds':time.process_time()-t0,'wall_seconds':time.perf_counter()-w0,
            'pretrained_model_executed':True,'independently_human_reviewed':False,
            'official_HF_parity':False,'reference_reader_executed':False,
            'source_independent_future':False,'production_authorized':False}
    sealed(out,result)
    return result


def raw_recount(plan,physical,starts,tokenizer):
    """Token/source audit; separate gold scorer never called here."""
    if physical.get('schema')!=SCHEMA+'.original-physical-answers' or physical.get('plan_sha256')!=digest(plan):raise ValueError('wrong plan')
    expected=plan['requests'];outputs=physical.get('raw_answers')
    if type(outputs)!=dict or set(outputs)!=set(expected) or physical.get('requests')!=len(expected):raise ValueError('missing/extra results')
    if type(starts)!=list or len(starts)!=len(expected):raise ValueError('missing starts')
    seen=set();forward=ni=no=0;pair=[]
    for start in starts:
        rid=start.get('request_id');row=expected.get(rid)
        if type(start)!=dict or set(start)!={'request_id','plan_sha256','input_tokens','input_ids_sha256'} or row is None or rid in seen:raise ValueError('bad journal')
        seen.add(rid)
        t=tokenizer.encode(row['prompt']);got=outputs[rid];ids=got['output_ids']
        if not 1<=len(t)<=1000 or start['plan_sha256']!=digest(plan) or start['input_tokens']!=len(t) or start['input_ids_sha256']!=digest(t):raise ValueError('prompt input drift')
        if (type(got)!=dict or set(got)!={'case_id','arm','source_ids','answer_text','answer_sha256','output_ids','input_tokens','output_tokens','cpu_seconds'}
            or got['case_id']!=row['case_id'] or got['arm']!=row['arm'] or got['source_ids']!=row['source_ids']
            or type(ids)!=list or not 1<=len(ids)<=ANSWER_CAP or any(type(n)!=int or n<0 or n>=49152 for n in ids)
            or got['answer_text']!=tokenizer.decode(ids) or got['answer_sha256']!=htext(got['answer_text'])
            or got['output_tokens']!=len(ids) or got['input_tokens']!=len(t)):
            raise ValueError('answer token/source mismatch')
        ni+=len(t);no+=len(ids);forward+=len(ids)+(ids[-1]!=2)
        pair.append([rid,got['answer_sha256'],digest(ids)])
    if (physical.get('model_forwards')!=forward or physical.get('model_sha256')!=READER_SHA or physical.get('tokenizer_sha256')!=TOKEN_SHA
        or physical.get('pretrained_model_executed') is not True or physical.get('reference_reader_executed') is not False
        or physical.get('independently_human_reviewed') is not False or physical.get('production_authorized') is not False):raise ValueError('false provenance')
    return {'schema':SCHEMA+'.independent-private-byte-recount','requests':len(expected),'forwards':forward,
            'input_tokens':ni,'output_tokens':no,'answers_sha256':digest(sorted(pair)),
            'human_sufficiency_verified':False,'semantic_correctness':None,'production_authorized':False}


def score_after_seal(plan,raw,v16_plan,v16_answers,original):
    """Retrospective publisher-answer *literal* proxy only, NEVER semantic QA."""
    if raw.get('plan_sha256')!=digest(plan) or v16_answers.get('plan_sha256')!=digest(v16_plan):raise ValueError('independent original lineage')
    if raw.get('requests')!=64 or v16_answers.get('requests')!=128:raise ValueError('missing model results')
    orig={r['sample_id']:r for r in original}
    if set(orig)!=set(['conv-26','conv-30','conv-41','conv-42','conv-43','conv-44','conv-47','conv-48','conv-49','conv-50']):raise ValueError('corpus revision changed')
    result={cohort:{arm:dict(n=0,contains=0,exact=0,answer_changed_vs_v16=0) for arm in (*ARMS,'v16_original_witness')} for cohort in ('literal_in_annotated_source','not_literal_in_annotated_source')}
    by_v16={c['id']:c for c in v16_plan['cases']}
    for row in plan['cases']:
        cohort=row['cohort'];ident=row['case_id'];parent=by_v16[ident]
        orig_q=orig[row['family']]['qa'][int(ident.split('/q')[1])]
        answer=orig_q.get('answer')
        if type(answer)!=str:raise ValueError('missing original answer')
        normalized=answer.strip().casefold()
        if not normalized:raise ValueError('empty original publisher answer')
        base=v16_answers['raw_answers'][parent['arms']['witness']['request_id']]['answer_text']
        for arm in (*ARMS,'v16_original_witness'):
            text=base if arm=='v16_original_witness' else raw['raw_answers'][row['arms'][arm]]['answer_text']
            z=result[cohort][arm];z['n']+=1
            z['contains']+=int(normalized in text.casefold())
            z['exact']+=int(normalized==text.strip().casefold())
            z['answer_changed_vs_v16']+=int(text!=base)
    if any(z['n']!=16 for arm in result.values() for z in arm.values()):raise ValueError('cohort denominator changed')
    return {'schema':SCHEMA+'.publisher-literal-postseal','rows':result,
            'original_source_question_roots':4,'retrospective_answer_conditioned':True,
            'independent_semantic_correctness':None,'human_verified_source_sufficiency':False,
            'reference_reader_executed':False,'learned_cell_utility_verified':False,
            'production_authorized':False,'decision':'HOLD_NO_GO'}


def cli():
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='command',required=True)
    a=sp.add_parser('prepare');a.add_argument('--source',required=True);a.add_argument('--ranks',required=True);a.add_argument('--v16-plan',required=True);a.add_argument('--out',required=True)
    a=sp.add_parser('run');a.add_argument('--source',required=True);a.add_argument('--ranks',required=True);a.add_argument('--v16-plan',required=True);a.add_argument('--plan',required=True);a.add_argument('--reader-dir',required=True);a.add_argument('--out',required=True)
    a=sp.add_parser('score');a.add_argument('--plan',required=True);a.add_argument('--answers',required=True);a.add_argument('--v16-plan',required=True);a.add_argument('--v16-answers',required=True);a.add_argument('--original',required=True);a.add_argument('--out',required=True)
    a=p.parse_args()
    if a.command=='prepare':
        sealed(a.out,build(read(a.source),read(a.ranks),read(a.v16_plan)))
    elif a.command=='run':
        print(json.dumps(physical_run(read(a.plan),read(a.source),read(a.ranks),read(a.v16_plan),a.reader_dir,a.out),sort_keys=True,default=str)[:300])
    else:
        sealed(a.out,score_after_seal(read(a.plan),read(a.answers),read(a.v16_plan),read(a.v16_answers),read(a.original)))

if __name__=='__main__':cli()
