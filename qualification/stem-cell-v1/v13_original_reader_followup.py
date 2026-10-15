"""V13 diagnostic Reader responses to BM25-vs-untrained lexical source changes.

Not a new blind natural-task study: historical weak held aggregates already seen.
Distinct prepare/generate/postseal score processes. No production authorization.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from stem_v13_cheap_retrieval import (CORPUS_SHA, HELD, PRIMARY, SCHEMA as V13,
    assert_source,digest,file_sha,read_json,validate_routes,write_once)

SCHEMA="hepta.stem.v13.original-lexical-reader-diagnostic.v1"
READER_SHA="5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c"
TOKENIZER_SHA="9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c"
SELECTION_PER_ROOT=4
MAX_GENERATED=24

def _digest_text(s):return sha256(s.encode('utf-8')).hexdigest()

def source_disagreement_selection(routes):
    """Pure ID/route selection, never accesses gold or original answers."""
    byfam={f:[] for f in HELD}
    for row in routes['cases']:
        f=row['family']
        if f not in byfam:continue
        a=row['top32']['bm25'][:3];b=row['top32'][PRIMARY][:3]
        if set(a)!=set(b):byfam[f].append(row['id'])
    if any(len(x)<SELECTION_PER_ROOT for x in byfam.values()):raise ValueError('not enough source-changing cases in each original root')
    # One fixed SHA question-ID ordering per family; no gold/answer access.
    chosen={f:sorted(byfam[f],key=lambda q:(sha256(q.encode()).hexdigest(),q))[:SELECTION_PER_ROOT] for f in HELD}
    return chosen,{f:len(byfam[f]) for f in HELD}

def prepare(src,plan,routes):
    validate_routes(src,plan,routes)
    chosen,counts=source_disagreement_selection(routes)
    selected={q for qs in chosen.values() for q in qs}
    look={r['id']:r for r in routes['cases']}
    prompts={};choices=[]
    for f in HELD:
        family=src['families'][f]
        docs={d['id']:d['text'] for d in family['passages']}
        qs={q['id']:q['text'] for q in family['questions']}
        for qid in chosen[f]:
            q=qs[qid]
            for arm in ('bm25',PRIMARY):
                evidence=look[qid]['top32'][arm][:3]
                if len(evidence)!=3 or len(set(evidence))!=3 or any(i not in docs or not docs[i].strip() for i in evidence):raise ValueError('missing source evidence')
                prompt=('<|im_start|>system\nAnswer only from numbered evidence. If not supported, reply unknown. Cite supporting evidence using [E1], [E2] or [E3].<|im_end|>\n'
                        '<|im_start|>user\nQuestion: '+q+'\n'+'\n'.join('[E'+str(i+1)+'] '+docs[k] for i,k in enumerate(evidence))+'\n<|im_end|>\n<|im_start|>assistant\n')
                rid=_digest_text(prompt)
                if rid in prompts and prompts[rid]['prompt']!=prompt:raise ValueError('prompt SHA collision')
                prompts.setdefault(rid,{'case_id':qid,'prompt':prompt,'sources':evidence,'question_sha256':_digest_text(q)})
                choices.append({'case_id':qid,'family':f,'arm':arm,'request_id':rid})
    if len(selected)!=16 or len(choices)!=32 or len(prompts)>32 or len(prompts)<16:raise ValueError('unregistered request scope')
    return dict(schema=SCHEMA+'.source-plan',source_sha256=digest(src),original_rank_sha256=digest(routes),
        source_only_selection={'cases_by_family':chosen,'all_membership_changes_by_family':counts},
        selected_original_cases=16,choices=choices,requests=prompts,
        unique_request_count=len(prompts),original_reader_model_sha256=READER_SHA,
        original_reader_tokenizer_sha256=TOKENIZER_SHA,max_new_tokens=MAX_GENERATED,
        heldout_gold_available_before_generation=False,independent_calendar_windows=0,
        human_semantic_evaluator_attached=False,production_authorized=False)

def _validate_plan(plan):
    if plan.get('schema')!=SCHEMA+'.source-plan' or plan.get('original_reader_model_sha256')!=READER_SHA or plan.get('original_reader_tokenizer_sha256')!=TOKENIZER_SHA or plan.get('max_new_tokens')!=MAX_GENERATED or plan.get('selected_original_cases')!=16 or len(plan.get('choices',[]))!=32 or plan.get('unique_request_count')!=len(plan.get('requests',{})) or not 16<=len(plan['requests'])<=32 or plan.get('heldout_gold_available_before_generation') is not False or plan.get('production_authorized') is not False:raise ValueError('unregistered original Reader plan')
    all_ids={q for arr in plan['source_only_selection']['cases_by_family'].values() for q in arr}
    if len(all_ids)!=16 or set(plan['source_only_selection']['cases_by_family'])!=set(HELD) or any(len(arr)!=4 for arr in plan['source_only_selection']['cases_by_family'].values()):raise ValueError('source-first ID selection changed')
    choice_pairs=set()
    for c in plan['choices']:
        if set(c)!={'case_id','family','arm','request_id'} or c['arm'] not in ('bm25',PRIMARY) or c['case_id'] not in all_ids or c['case_id'].split('/')[0]!=c['family'] or c['request_id'] not in plan['requests']:raise ValueError('unregistered Reader route')
        key=c['case_id'],c['arm']
        if key in choice_pairs:raise ValueError('duplicate route')
        choice_pairs.add(key)
        row=plan['requests'][c['request_id']]
        if row['case_id']!=c['case_id'] or len(row['sources'])!=3 or len(set(row['sources']))!=3 or _digest_text(row['prompt'])!=c['request_id']:raise ValueError('altered prompt/source IDs')
    if len(choice_pairs)!=32:raise ValueError('incomplete route matrix')

def validate_exact(plan,src,registered_plan,routes):
    _validate_plan(plan)
    expected=prepare(src,registered_plan,routes)
    if plan!=expected:raise ValueError("original plan differs from independently pinned source and ranking")

def generate(plan_file,reader_dir,result_file,source_file,registered_plan_file,ranked_file):
    from v12_reader_runtime import OriginalCandidateBPE,OriginalCandidateLlama,check_original,file_sha as original_hash
    import torch
    plan=read_json(plan_file)
    validate_exact(plan,read_json(source_file),read_json(registered_plan_file),read_json(ranked_file))
    check_original(reader_dir)
    tok=OriginalCandidateBPE(reader_dir);torch.set_num_threads(2)
    reader=OriginalCandidateLlama(reader_dir)
    started=Path(str(result_file)+'.starts.jsonl')
    if Path(result_file).exists() or started.exists():raise FileExistsError('original output/journal already exists')
    rows={};t0=time.process_time();w0=time.perf_counter()
    with started.open('x') as journal:
        for key,row in sorted(plan['requests'].items()):
            tokens=tok.encode(row['prompt'])
            if not tokens or len(tokens)>1000:raise ValueError('untruncated Reader input exceeds budget')
            line={'request_id':key,'plan_sha256':file_sha(plan_file),'input_token_sha256':digest(tokens),
                  'input_token_count':len(tokens)}
            journal.write(json.dumps(line,sort_keys=True)+'\n');journal.flush();os.fsync(journal.fileno())
            before=time.process_time()
            ids=reader.generate(tokens,max_tokens=MAX_GENERATED)
            answer=tok.decode(ids)
            rows[key]={'case_id':row['case_id'],'source_ids':row['sources'],
                'raw_answer':answer,'raw_answer_sha256':_digest_text(answer),'original_token_ids':ids,
                'input_tokens':len(tokens),'output_tokens':len(ids),
                'cpu_seconds':time.process_time()-before}
    if len(rows)!=plan['unique_request_count']:raise ValueError('missing genuine model request')
    packet=dict(schema=SCHEMA+'.original-reader-answers',source_plan_sha256=file_sha(plan_file),
                reader_weights_sha256=READER_SHA,reader_tokenizer_sha256=TOKENIZER_SHA,
                revalidated_source_file_sha256=file_sha(source_file),revalidated_rank_file_sha256=file_sha(ranked_file),
                original_Reader_requests=len(rows),original_Reader_forwards=reader.calls,
                all_original_raw_answers=rows,model_cpu_seconds=time.process_time()-t0,
                model_wall_seconds=time.perf_counter()-w0,
                official_HF_model_tokenizer_parity=False,semantic_correctness=None,
                independent_calendar_windows=0,production_authorized=False)
    write_once(result_file,packet)
    return packet

def score(plan_file,answer_file,original_file):
    plan=read_json(plan_file);a=read_json(answer_file);_validate_plan(plan)
    if a.get('schema')!=SCHEMA+'.original-reader-answers' or a.get('source_plan_sha256')!=file_sha(plan_file) or a.get('reader_weights_sha256')!=READER_SHA or a.get('reader_tokenizer_sha256')!=TOKENIZER_SHA or a.get('production_authorized') is not False:raise ValueError('corrupted model material')
    if len(a['all_original_raw_answers'])!=len(plan['requests']) or a.get('original_Reader_requests')!=len(plan['requests']):raise ValueError('missing model generation')
    for rid,row in a['all_original_raw_answers'].items():
        orig=plan['requests'].get(rid)
        if orig is None or row['case_id']!=orig['case_id'] or row['source_ids']!=orig['sources'] or row['raw_answer_sha256']!=_digest_text(row['raw_answer']) or len(row['original_token_ids'])!=row['output_tokens'] or type(row['output_tokens'])!=int or not 1<=row['output_tokens']<=MAX_GENERATED:raise ValueError('original raw answer altered')
    if file_sha(original_file)!=CORPUS_SHA:raise ValueError('original publisher source changed')
    raw=read_json(original_file)
    byid={item['sample_id']+'/q'+str(i):q for item in raw for i,q in enumerate(item['qa'])}
    totals={arm:dict(any_weak_support=0,missing_or_ambiguous_weak_annotation=0,output_tokens=0,input_tokens=0) for arm in ('bm25',PRIMARY)}
    changes=0
    pair={}
    for choice in plan['choices']:
        key=choice['case_id'];arm=choice['arm'];rid=choice['request_id'];rr=a['all_original_raw_answers'][rid]
        label=byid[key].get('evidence');family=key.split('/')[0]
        known={d['dia_id'] for s in raw if s['sample_id']==family for turns in s['conversation'].values() if isinstance(turns,list) for d in turns if isinstance(d,dict) and 'dia_id' in d}
        valid=(type(label)==list and len(label)>0 and all(type(x)==str and x in known for x in label))
        totals[arm]['any_weak_support']+=int(valid and bool(set(label).intersection(rr['source_ids'])))
        totals[arm]['missing_or_ambiguous_weak_annotation']+=int(not valid)
        totals[arm]['input_tokens']+=rr['input_tokens'];totals[arm]['output_tokens']+=rr['output_tokens']
        pair.setdefault(key,{})[arm]=rid
    for key,p in pair.items():
        if set(p)!={'bm25',PRIMARY}:raise ValueError('missing paired Reader route')
        changes+=int(a['all_original_raw_answers'][p['bm25']]['raw_answer']!=a['all_original_raw_answers'][p[PRIMARY]]['raw_answer'])
    if len(pair)!=16:raise ValueError('not complete 16 original questions')
    return dict(schema=SCHEMA+'.sanitized-physical-diagnostic.v1',
       original_corpus_sha256=CORPUS_SHA,source_plan_sha256=file_sha(plan_file),
       original_answer_file_sha256=file_sha(answer_file),
       genuine_original_reader_requests=len(a['all_original_raw_answers']),
       original_reader_forward_calls=a['original_Reader_forwards'],
       source_first_original_cases=len(pair),independent_retrospective_source_roots=4,
       selected_conditioned_on_evidence_membership_difference=True,
       original_answers_changed_between_routes=changes,per_arm=totals,
       original_reader_model_cpu_seconds=a['model_cpu_seconds'],original_reader_model_wall_seconds=a['model_wall_seconds'],
       official_HF_parity=False,original_task_semantic_correctness=None,
       new_calendar_future_windows=0,equal_end_to_end_compute=False,model_learning_utility_verified=False,
       production_authorized=False,stem_winner_verified=False)

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='phase',required=True)
    z=sub.add_parser('prepare')
    for field in ('source','registered-plan','ranked','output'):z.add_argument('--'+field,required=True)
    z=sub.add_parser('generate');z.add_argument('--reader-plan',required=True);z.add_argument('--reader-root',required=True);z.add_argument('--source',required=True);z.add_argument('--registered-plan',required=True);z.add_argument('--ranked',required=True);z.add_argument('--output',required=True)
    z=sub.add_parser('score');z.add_argument('--reader-plan',required=True);z.add_argument('--raw-answers',required=True);z.add_argument('--original',required=True);z.add_argument('--output',required=True)
    a=p.parse_args()
    if a.phase=='prepare':
        data=prepare(read_json(a.source),read_json(a.registered_plan),read_json(a.ranked));write_once(a.output,data)
        print(json.dumps({'phase':'prepare','cases':data['selected_original_cases'],'unique_original_requests':data['unique_request_count'],'gold_available_before_generation':False}))
    elif a.phase=='generate':
        data=generate(a.reader_plan,a.reader_root,a.output,a.source,a.registered_plan,a.ranked)
        print(json.dumps({'phase':'generate','actual_original_reader_requests':data['original_Reader_requests'],'physical_forward_calls':data['original_Reader_forwards'],'full_task_claim':False}))
    else:
        data=score(a.reader_plan,a.raw_answers,a.original);write_once(a.output,data)
        print(json.dumps(data,sort_keys=True))
if __name__=='__main__':main()
