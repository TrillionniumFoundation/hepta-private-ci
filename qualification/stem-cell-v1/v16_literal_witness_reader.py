"""V16 original 135M Reader: literal-answer witness vs nonliteral historical controls.

Research only. Literal containment of publisher answer in annotated source is NOT
independently reviewed sufficiency. The retrospective cohort is answer-dependent.
Four actual evidence variants execute with the same pinned candidate Reader;
there is NO stronger reference model, semantic reviewer, future observation or
production permission. Private answers and original dataset never enter Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

from v15_original_candidate_four_arm import (
    htext, jbytes, digest, sha_file, source_and_rank, prompt,
    CORPUS_SHA, READER_SHA, TOKEN_SHA, HELD,
)

SCHEMA = 'hepta.stem.v16.original-literal-answer-witness.shadow.v1'
GROUPS = ('literal_in_annotated_source', 'not_literal_in_annotated_source')
ARMS = ('none', 'retrieved', 'witness', 'lesion')
N_PER_GROUP_ROOT = 4
OUT_CAP = 24
READER_CFG_SHA = '8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a'
CITATIONS = re.compile(r'\[E(\d+)\]')


def read(path, *, max_bytes=16_000_000):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>max_bytes:raise ValueError('unsafe/missing/oversize source')
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate JSON field')
            d[k]=v
        return d
    def deny(x):raise ValueError('nonfinite JSON')
    return json.loads(p.read_bytes(),object_pairs_hook=unique,parse_constant=deny)


def sealed(path,obj):
    p=Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:
        f.write(jbytes(obj)+b'\n');f.flush();os.fsync(f.fileno())


def literal_answer(q, text):
    """Answer substring is an *objective text occurrence*, not semantic sufficiency."""
    answer=q.get('answer')
    if type(answer)!=str:return False
    a=answer.strip()
    return (len(a)>=4 and a.casefold() not in {'yes','no','true','false','none','unknown'}
            and any(c.isalpha() for c in a) and a.casefold() in text.casefold())


def eligibility(src,ranks,original):
    bycase=source_and_rank(src,ranks)
    if type(original)!=list or len(original)!=10:raise ValueError('original ten family input required')
    families={x['sample_id']:x for x in original}
    if set(families)!=set(src['families']):raise ValueError('original source-roster substitution')
    eligible={f:{g:[] for g in GROUPS} for f in HELD}
    for fam in HELD:
        original_qa=families[fam]['qa']
        docs={d['id']:d['text'] for d in src['families'][fam]['passages']}
        for i,q in enumerate(original_qa):
            case=f'{fam}/q{i}';ev=q.get('evidence')
            if type(ev)!=list or len(ev)!=1 or type(ev[0])!=str:continue
            witness=ev[0]
            if witness not in docs or witness in bycase[case]['top32'][:3]:continue
            group=GROUPS[0] if literal_answer(q,docs[witness]) else GROUPS[1]
            eligible[fam][group].append((case,witness))
    return eligible


def construct(src,ranks,original):
    pools=eligibility(src,ranks,original)
    bycase=source_and_rank(src,ranks)
    cases=[];requests={}
    for fam in HELD:
        docs={d['id']:d['text'] for d in src['families'][fam]['passages']}
        qs={q['id']:q['text'] for q in src['families'][fam]['questions']}
        for group in GROUPS:
            selected=sorted(pools[fam][group],key=lambda item:(htext(item[0]),item[0]))[:N_PER_GROUP_ROOT]
            if len(selected)!=N_PER_GROUP_ROOT:raise ValueError('not enough original history in designated cohort')
            for case,witness in selected:
                top=bycase[case]['top32'][:3]
                arms={'none':[], 'retrieved':list(top),
                      'witness':[witness,top[0],top[1]],'lesion':[top[0],top[1]]}
                entry={'id':case,'family':fam,'cohort':group,'witness_id':witness,'arms':{}}
                for arm in ARMS:
                    sentence=prompt(qs[case],arms[arm],docs)
                    key=htext(sentence)
                    if key in requests:raise ValueError('original prompt duplicate across registered arms')
                    requests[key]={'case_id':case,'family':fam,'arm':arm,'prompt':sentence,
                                   'source_ids':arms[arm], 'question_sha256':htext(qs[case])}
                    entry['arms'][arm]={'request_id':key,'evidence_ids':arms[arm]}
                cases.append(entry)
    plan={'schema':SCHEMA+'.answer-dependent-precommitted-plan',
          'source_sha256':digest(src),'bm25_routes_sha256':digest(ranks),
          'dataset_sha256':CORPUS_SHA,'reader_sha256':READER_SHA,
          'tokenizer_sha256':TOKEN_SHA,'reader_config_sha256':READER_CFG_SHA,
          'frozen_arms':list(ARMS),'source_roots':list(HELD),
          'answer_dependent_historical_selection':True,
          'label_text_entered_model_prompts':False,
          'literal_containment_not_human_sufficiency':True,
          'independent_semantic_adjudication':False,
          'candidate_only_reader':True,'stronger_reference_reader_executed':False,
          'calendar_future_windows':0,'production_authorized':False,
          'max_new_tokens':OUT_CAP,'cases':cases,'requests':requests}
    validate(plan,src,ranks)
    return plan


def validate(plan,src,ranks):
    bycase=source_and_rank(src,ranks)
    require= lambda ok,msg: None if ok else (_ for _ in ()).throw(ValueError(msg))
    require(type(plan)==dict and set(plan)=={
        'schema','source_sha256','bm25_routes_sha256','dataset_sha256','reader_sha256',
        'tokenizer_sha256','reader_config_sha256','frozen_arms','source_roots',
        'answer_dependent_historical_selection','label_text_entered_model_prompts',
        'literal_containment_not_human_sufficiency','independent_semantic_adjudication',
        'candidate_only_reader','stronger_reference_reader_executed','calendar_future_windows',
        'production_authorized','max_new_tokens','cases','requests'},'plan field insertion')
    require(plan['schema']==SCHEMA+'.answer-dependent-precommitted-plan' and
            plan['source_sha256']==digest(src) and plan['bm25_routes_sha256']==digest(ranks)
            and plan['dataset_sha256']==CORPUS_SHA and plan['reader_sha256']==READER_SHA
            and plan['tokenizer_sha256']==TOKEN_SHA and plan['reader_config_sha256']==READER_CFG_SHA,
            'original model or source shifted')
    require(plan['frozen_arms']==list(ARMS) and plan['source_roots']==list(HELD)
            and plan['answer_dependent_historical_selection'] is True
            and plan['label_text_entered_model_prompts'] is False
            and plan['literal_containment_not_human_sufficiency'] is True
            and plan['independent_semantic_adjudication'] is False
            and plan['candidate_only_reader'] is True
            and plan['stronger_reference_reader_executed'] is False
            and plan['calendar_future_windows']==0
            and plan['production_authorized'] is False
            and plan['max_new_tokens']==OUT_CAP,
            'untrusted qualification flags')
    cases=plan['cases'];requests=plan['requests']
    require(type(cases)==list and len(cases)==len(HELD)*len(GROUPS)*N_PER_GROUP_ROOT
            and type(requests)==dict and len(requests)==len(cases)*len(ARMS),
            'incomplete actual Reader requests')
    seen=set();used=set();cnt={(f,g):0 for f in HELD for g in GROUPS}
    for c in cases:
        require(type(c)==dict and set(c)=={'id','family','cohort','witness_id','arms'},'case fields')
        ident=c['id'];fam=c['family'];group=c['cohort'];wit=c['witness_id']
        require((fam,group) in cnt and ident in bycase and ident not in seen
                and ident.split('/q')[0]==fam,'missing/colliding original family')
        seen.add(ident);cnt[fam,group]+=1
        docs={x['id']:x['text'] for x in src['families'][fam]['passages']}
        qs={x['id']:x['text'] for x in src['families'][fam]['questions']}
        top=bycase[ident]['top32'][:3]
        require(wit in docs and wit not in top and type(c['arms'])==dict
                and set(c['arms'])==set(ARMS),'unregistered witness')
        expected={'none':[], 'retrieved':list(top),
                  'witness':[wit,top[0],top[1]],'lesion':[top[0],top[1]]}
        for arm in ARMS:
            row=c['arms'][arm]
            require(type(row)==dict and set(row)=={'request_id','evidence_ids'},'arm injection')
            ids=row['evidence_ids'];reqid=row['request_id']
            require(type(ids)==list and ids==expected[arm] and type(reqid)==str
                    and reqid not in used and reqid in requests, 'evidence or request replacement')
            used.add(reqid);entry=requests[reqid]
            sentence=prompt(qs[ident],ids,docs)
            require(type(entry)==dict and set(entry)=={'case_id','family','arm','prompt','source_ids','question_sha256'}
                    and (entry['case_id'],entry['family'],entry['arm'])==(ident,fam,arm)
                    and entry['source_ids']==ids and entry['prompt']==sentence
                    and entry['question_sha256']==htext(qs[ident]) and reqid==htext(sentence),
                    'original model prompt substitution')
    require(all(n==N_PER_GROUP_ROOT for n in cnt.values()) and used==set(requests), 'missing cohort/Reader requests')
    return True


def run(plan,src,ranks,reader_dir,out):
    """Actual ORIGINAL archived model, never receives publisher answers."""
    from v12_reader_runtime import check_original, OriginalCandidateBPE,OriginalCandidateLlama
    import torch
    validate(plan,src,ranks);check_original(reader_dir)
    output=Path(out);starts=Path(str(output)+'.starts.jsonl')
    if output.exists() or starts.exists():raise FileExistsError('refuse overwriting actual physical results')
    tok=OriginalCandidateBPE(reader_dir)
    torch.set_num_threads(2)
    model=OriginalCandidateLlama(reader_dir)
    first_cpu=time.process_time();first_wall=time.perf_counter();answers={}
    with starts.open('x',encoding='utf-8') as journal:
        for request_id,row in sorted(plan['requests'].items()):
            tokens=tok.encode(row['prompt'])
            if not 1<=len(tokens)<=1000:raise ValueError('original model context limit')
            start={'request_id':request_id,'plan_sha256':digest(plan),'input_ids_sha256':digest(tokens),
                   'input_token_count':len(tokens)}
            journal.write(json.dumps(start,sort_keys=True)+'\n');journal.flush();os.fsync(journal.fileno())
            begin=time.process_time()
            original_ids=model.generate(tokens,max_tokens=OUT_CAP)
            raw=tok.decode(original_ids)
            answers[request_id]={'case_id':row['case_id'],'arm':row['arm'],
                 'source_ids':row['source_ids'],'answer_text':raw,'answer_sha256':htext(raw),
                 'token_ids':original_ids,'input_tokens':len(tokens),'output_tokens':len(original_ids),
                 'cpu_seconds':time.process_time()-begin}
    result={'schema':SCHEMA+'.actual-original-reader-results',
            'plan_sha256':digest(plan),'model_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
            'reader_config_sha256':READER_CFG_SHA,'model_forwards':model.calls,
            'requests':len(answers),'raw_answers':answers,
            'execution_cpu_seconds':time.process_time()-first_cpu,
            'execution_wall_seconds':time.perf_counter()-first_wall,
            'stronger_reference_reader_executed':False,
            'human_verified_sufficiency':False,
            'independent_semantic_correctness':None,
            'hf_operator_tokenizer_parity':False,'production_authorized':False}
    sealed(output,result)
    return result


def verify_answers(plan,src,ranks,answers):
    validate(plan,src,ranks)
    if (type(answers)!=dict or set(answers)!={'schema','plan_sha256','model_sha256','tokenizer_sha256',
       'reader_config_sha256','model_forwards','requests','raw_answers','execution_cpu_seconds',
       'execution_wall_seconds','stronger_reference_reader_executed','human_verified_sufficiency',
       'independent_semantic_correctness','hf_operator_tokenizer_parity','production_authorized'}
        or answers['schema']!=SCHEMA+'.actual-original-reader-results'
        or answers['plan_sha256']!=digest(plan)
        or answers['model_sha256']!=READER_SHA or answers['tokenizer_sha256']!=TOKEN_SHA
        or answers['reader_config_sha256']!=READER_CFG_SHA
        or answers['stronger_reference_reader_executed'] is not False
        or answers['human_verified_sufficiency'] is not False
        or answers['independent_semantic_correctness'] is not None
        or answers['hf_operator_tokenizer_parity'] is not False
        or answers['production_authorized'] is not False):raise ValueError('invented original Reader qualification')
    responses=answers['raw_answers']
    if (type(responses)!=dict or set(responses)!=set(plan['requests'])
        or type(answers['requests'])!=int or answers['requests']!=len(responses)
        or type(answers['model_forwards'])!=int or answers['model_forwards']<len(responses)):
        raise ValueError('incomplete real output roster')
    for rid,row in responses.items():
        req=plan['requests'][rid]
        if (type(row)!=dict or set(row)!={'case_id','arm','source_ids','answer_text','answer_sha256','token_ids','input_tokens','output_tokens','cpu_seconds'}
            or (row['case_id'],row['arm'])!=(req['case_id'],req['arm'])
            or row['source_ids']!=req['source_ids']
            or type(row['answer_text'])!=str or row['answer_sha256']!=htext(row['answer_text'])
            or type(row['token_ids'])!=list or not 1<=len(row['token_ids'])<=OUT_CAP
            or any(type(t)!=int or not 0<=t<49152 for t in row['token_ids'])
            or type(row['input_tokens'])!=int or not 1<=row['input_tokens']<=1000
            or type(row['output_tokens'])!=int or row['output_tokens']!=len(row['token_ids'])
            or type(row['cpu_seconds']) not in (int,float) or not 0<=row['cpu_seconds']<600):
            raise ValueError('false original model answer bytes')
    return True


def score_after_seal(plan,src,ranks,answers,original):
    """Publisher target answers are opened ONLY HERE, in separate process."""
    verify_answers(plan,src,ranks,answers)
    rebuild=construct(src,ranks,original)
    if rebuild!=plan:raise ValueError('postseal historical answer-dependent cohort changed')
    orig={o['sample_id']:o for o in original}
    tallies={cohort:{arm:dict(cases=0,publisher_witness_delivered=0,
                         literal_target_substring=0,literal_target_exact_casefold=0,
                         citation_syntax=0,bad_citations=0,literal_unknown=0,
                         input_tokens=0,output_tokens=0) for arm in ARMS} for cohort in GROUPS}
    per_family={f:{g:dict(cases=0,changed_retrieved_to_witness=0,
                       changed_witness_to_lesion=0,witness_target_substring=0) for g in GROUPS} for f in HELD}
    for case in plan['cases']:
        ident=case['id'];fam=case['family'];group=case['cohort'];q=orig[fam]['qa'][int(ident.split('/q')[1])]
        target=q.get('answer');valid=type(target)==str and len(target.strip())>0
        texts={}
        for arm in ARMS:
            row=answers['raw_answers'][case['arms'][arm]['request_id']]
            txt=row['answer_text'];t=tallies[group][arm];t['cases']+=1
            t['publisher_witness_delivered']+=int(case['witness_id'] in row['source_ids'])
            t['literal_target_substring']+=int(valid and target.strip().casefold() in txt.casefold())
            t['literal_target_exact_casefold']+=int(valid and txt.strip().casefold()==target.strip().casefold())
            citations=CITATIONS.findall(txt);t['citation_syntax']+=len(citations)
            t['bad_citations']+=sum(not 1<=int(z)<=len(row['source_ids']) for z in citations)
            t['literal_unknown']+=int(txt.strip().lower()=='unknown')
            t['input_tokens']+=row['input_tokens'];t['output_tokens']+=row['output_tokens']
            texts[arm]=txt
        local=per_family[fam][group];local['cases']+=1
        local['changed_retrieved_to_witness']+=int(texts['retrieved']!=texts['witness'])
        local['changed_witness_to_lesion']+=int(texts['witness']!=texts['lesion'])
        local['witness_target_substring']+=int(valid and target.strip().casefold() in texts['witness'].casefold())
    return {'schema':SCHEMA+'.sanitized-historical-literal-diagnostic',
            'plan_sha256':digest(plan),'original_answer_journal_sha256':digest(answers),
            'original_model_sha256':READER_SHA,'original_dataset_sha256':CORPUS_SHA,
            'retrospective_question_count':len(plan['cases']),
            'unique_original_source_families':len(HELD),
            'actual_original_reader_requests':answers['requests'],
            'actual_model_forwards':answers['model_forwards'],
            'reader_execution_cpu_seconds':answers['execution_cpu_seconds'],
            'reader_execution_wall_seconds':answers['execution_wall_seconds'],
            'per_cohort_arm':tallies,'per_original_family':per_family,
            'cohorts_selected_using_publisher_answers':True,
            'literal_occurrence_does_not_establish_semantic_sufficiency':True,
            'independently_human_verified_sufficiency':False,
            'independent_semantic_answer_correctness':None,
            'reference_reader_actual_calls':0,'prospective_calendar_windows':0,
            'official_HF_operator_parity':False,'full_lifecycle_cost_matched':False,
            'stem_winner_verified':False,'v6_seed41_retention_fixed':False,
            'production_authorized':False,'decision':'HOLD_NO_GO'}


def cli():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    for action in ('prepare','run','score'):
        sp=sub.add_parser(action);sp.add_argument('--source',required=True);sp.add_argument('--bm25',required=True)
        sp.add_argument('--plan',required=True)
        if action in ('prepare','score'):sp.add_argument('--original',required=True)
        if action=='run':sp.add_argument('--reader',required=True)
        if action!='prepare':sp.add_argument('--answers',required=True)
        if action=='score':sp.add_argument('--output',required=True)
    a=p.parse_args()
    src=read(a.source);ranks=read(a.bm25)
    if a.cmd=='prepare':
        data=read(a.original);plan=construct(src,ranks,data);sealed(a.plan,plan)
        print(json.dumps({'cases':len(plan['cases']),'requests':len(plan['requests']),'plan_sha256':digest(plan),
                          'answer_dependent_historical_selection':True}))
    else:
        plan=read(a.plan)
        if a.cmd=='run':
            result=run(plan,src,ranks,a.reader,a.answers)
            print(json.dumps({'original_reader_requests':result['requests'],'model_forwards':result['model_forwards'],
                              'cpu_seconds':result['execution_cpu_seconds'],'wall_seconds':result['execution_wall_seconds']}))
        else:
            original=read(a.original);answers=read(a.answers)
            report=score_after_seal(plan,src,ranks,answers,original);sealed(a.output,report)
            print(json.dumps({'cases':report['retrospective_question_count'],
                              'requests':report['actual_original_reader_requests'],
                              'decision':report['decision']}))

if __name__=='__main__':cli()
