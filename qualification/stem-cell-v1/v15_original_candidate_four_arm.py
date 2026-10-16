"""Original archived 135M Reader, four evidence regimes, candidate-only experiment.

Publisher annotations select a historical witness in a separate preparation
phase. It is NOT independently human-verified sufficient evidence, nor a blind
future-window or a comparison with a stronger reference Reader. Original raw
answers, questions, publisher gold and model bytes stay private.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

SCHEMA = 'hepta.stem.v15.original-candidate-witness-probe.shadow.v1'
ARMS = ('none', 'retrieved', 'annotated_witness', 'witness_lesion')
HELD = ('conv-47', 'conv-48', 'conv-49', 'conv-50')
N_PER_ROOT = 4
OUT_CAP = 24
CORPUS_SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
READER_SHA = '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKEN_SHA = '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
_CITE = re.compile(r'\[E([0-9]+)\]')


def hbytes(data: bytes) -> str: return sha256(data).hexdigest()
def htext(text: str) -> str: return hbytes(text.encode('utf-8'))
def jbytes(obj) -> bytes: return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(obj) -> str: return hbytes(jbytes(obj))
def sha_file(path):
    h=sha256()
    with Path(path).open('rb') as file:
        for part in iter(lambda: file.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def load(path):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('duplicate JSON field')
            d[k]=v
        return d
    def bad(x):raise ValueError('nonfinite JSON: '+x)
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>12*1024*1024:
        raise ValueError('absent, symbolic or unbounded original input')
    return json.loads(p.read_bytes(),object_pairs_hook=pairs,parse_constant=bad)


def save_new(path, packet):
    p=Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:
        f.write(jbytes(packet)+b'\n');f.flush();os.fsync(f.fileno())


def prompt(question, ids, docs):
    if type(question)!=str or not question.strip() or type(ids)!=list or len(ids)>3 or len(set(ids))!=len(ids):
        raise ValueError('invalid evidence prompt')
    if any(type(x)!=str or x not in docs or not docs[x].strip() for x in ids):
        raise ValueError('foreign/empty evidence')
    instructions=('Answer only from numbered evidence. If not supported, reply unknown. '
                  'Cite supporting evidence using [E1], [E2] or [E3].')
    return ('<|im_start|>system\n'+instructions+'<|im_end|>\n'
            '<|im_start|>user\nQuestion: '+question+'\n'
            + '\n'.join('[E'+str(k+1)+'] '+docs[s] for k,s in enumerate(ids))
            + '\n<|im_end|>\n<|im_start|>assistant\n')


def source_and_rank(src, ranks):
    from stem_v13_cheap_retrieval import assert_source, digest as source_digest
    assert_source(src)
    if type(ranks)!=dict or ranks.get('schema')!='hepta.stem.v14.original-primary-single-arm-cost.shadow.v1.private-routes':
        # Accept only known V14 physical BM25 route schema (never arbitrary ranking objects).
        raise ValueError('unregistered BM25 original route schema')
    if (ranks.get('profile')!='bm25_only' or ranks.get('gold_present') is not False or ranks.get('source_sha256')!=source_digest(src) or ranks.get('rank_sha256')!='b0b38675d2d5458795d0577d5c861b796dfbdf9e7d4cd089838895c419831697' or ranks.get('rank_sha256')!=digest(ranks.get('rows'))):
        raise ValueError('invalid BM25 route provenance')
    allids={q['id'] for fam in src['family_order'] for q in src['families'][fam]['questions']}
    rows=ranks.get('rows')
    if type(rows)!=list or len(rows)!=1986 or {x['id'] for x in rows}!=allids or len(allids)!=1986:
        raise ValueError('incomplete original question inventory')
    for row in rows:
        if type(row)!=dict or set(row)!={'id','family','top32'} or row['id'].split('/')[0]!=row['family']:
            raise ValueError('wrong BM25 row identity')
        ids=row['top32']
        if type(ids)!=list or len(ids)!=32 or len(set(ids))!=32:
            raise ValueError('truncated/duplicated BM25 ranking')
        known={x['id'] for x in src['families'][row['family']]['passages']}
        if not set(ids)<=known:raise ValueError('unbound source IDs')
    return {r['id']:r for r in rows}


def prepare(src,ranks,original):
    bycase=source_and_rank(src,ranks)
    if type(original)!=list or len(original)!=10:
        raise ValueError('expected original ten-family source')
    originals={row['sample_id']:row for row in original}
    if set(originals)!=set(src['families']):raise ValueError('original family mismatch')
    requests={};cases=[];candidate_counts={}
    for fam in HELD:
        docs={d['id']:d['text'] for d in src['families'][fam]['passages']}
        qs={q['id']:q['text'] for q in src['families'][fam]['questions']}
        pool=[]
        for idx,item in enumerate(originals[fam]['qa']):
            ident=fam+'/q'+str(idx)
            ann=item.get('evidence')
            if type(ann)!=list or len(ann)!=1 or type(ann[0])!=str:continue
            witness=ann[0]
            if witness not in docs or witness in bycase[ident]['top32'][:3]:continue
            pool.append((ident,witness))
        candidate_counts[fam]=len(pool)
        chosen=sorted(pool,key=lambda z:(htext(z[0]),z[0]))[:N_PER_ROOT]
        if len(chosen)!=N_PER_ROOT:raise ValueError('missing single-witness evidence candidates')
        for ident,witness in chosen:
            top=bycase[ident]['top32'][:3]
            evidence={'none':[], 'retrieved':list(top),
                      'annotated_witness':[witness,top[0],top[1]],
                      'witness_lesion':[top[0],top[1]]}
            if witness in evidence['witness_lesion'] or len(set(evidence['annotated_witness']))!=3:
                raise ValueError('lesion failed to remove publisher witness')
            arms={}
            for arm in ARMS:
                sentence=prompt(qs[ident],evidence[arm],docs)
                rid=htext(sentence)
                if rid in requests:raise ValueError('request identity collision')
                requests[rid]=dict(case_id=ident,family=fam,arm=arm,prompt=sentence,
                                   source_ids=evidence[arm],question_sha256=htext(qs[ident]))
                arms[arm]=dict(request_id=rid,evidence_ids=evidence[arm])
            cases.append(dict(id=ident,family=fam,witness_id=witness,arms=arms))
    plan=dict(schema=SCHEMA+'.plan',original_dataset_sha256=CORPUS_SHA,
              source_sha256=digest(src),bm25_routes_sha256=digest(ranks),
              selected_on_publisher_witness_annotation=True,
              selected_using_publisher_answer_text=False,
              purported_sufficient_evidence_independently_verified=False,
              source_roots=list(HELD),eligible_counts=candidate_counts,
              cases=cases,requests=requests,
              readers_executed=['candidate'],stronger_reference_reader_available=False,
              model_sha256=READER_SHA,tokenizer_sha256=TOKEN_SHA,
              max_new_tokens=OUT_CAP,model_answer_labels_before_seal=False,
              source_future_windows=0,production_authorized=False)
    validate_plan(plan,src,ranks)
    return plan


def validate_plan(plan,src,ranks):
    lookup=source_and_rank(src,ranks)
    if (type(plan)!=dict or plan.get('schema')!=SCHEMA+'.plan'
        or plan.get('original_dataset_sha256')!=CORPUS_SHA
        or plan.get('source_sha256')!=digest(src)
        or plan.get('bm25_routes_sha256')!=digest(ranks)
        or plan.get('source_roots')!=list(HELD)
        or plan.get('model_sha256')!=READER_SHA
        or plan.get('tokenizer_sha256')!=TOKEN_SHA
        or plan.get('max_new_tokens')!=OUT_CAP
        or plan.get('readers_executed')!=['candidate']
        or plan.get('stronger_reference_reader_available') is not False
        or plan.get('purported_sufficient_evidence_independently_verified') is not False
        or plan.get('selected_on_publisher_witness_annotation') is not True
        or plan.get('selected_using_publisher_answer_text') is not False
        or plan.get('model_answer_labels_before_seal') is not False
        or plan.get('source_future_windows')!=0 or plan.get('production_authorized') is not False):
        raise ValueError('unverifiable or inflated four-arm plan')
    cases=plan.get('cases');req=plan.get('requests')
    if type(cases)!=list or len(cases)!=len(HELD)*N_PER_ROOT or type(req)!=dict or len(req)!=len(HELD)*N_PER_ROOT*len(ARMS):
        raise ValueError('missing full 4-arm cohort')
    seen=set(); used=set(); counts={f:0 for f in HELD}
    for case in cases:
        ident=case['id'];fam=case['family'];witness=case['witness_id']
        if ident in seen or fam not in counts or ident not in lookup or not isinstance(witness,str):raise ValueError('invalid case or witness')
        seen.add(ident);counts[fam]+=1
        docs={d['id']:d['text'] for d in src['families'][fam]['passages']}
        questions={q['id']:q['text'] for q in src['families'][fam]['questions']}
        if witness not in docs or witness in lookup[ident]['top32'][:3] or type(case['arms'])!=dict or set(case['arms'])!=set(ARMS):
            raise ValueError('unbound annotated witness')
        a=case['arms'];top=lookup[ident]['top32'][:3]
        required={'none':[], 'retrieved':top, 'annotated_witness':[witness,top[0],top[1]],
                  'witness_lesion':[top[0],top[1]]}
        for arm in ARMS:
            ids=a[arm]['evidence_ids'];rid=a[arm]['request_id']
            if ids!=required[arm] or rid in used or rid not in req:raise ValueError('source membership or request substitution')
            used.add(rid);row=req[rid]
            expected=prompt(questions[ident],ids,docs)
            if (type(row)!=dict or set(row)!={'case_id','family','arm','prompt','source_ids','question_sha256'}
                or (row['case_id'],row['family'],row['arm'])!=(ident,fam,arm)
                or row['source_ids']!=ids or row['prompt']!=expected or rid!=htext(expected)
                or row['question_sha256']!=htext(questions[ident])):
                raise ValueError('source ID/prompt/hash mismatch')
    if any(v!=N_PER_ROOT for v in counts.values()) or used!=set(req):raise ValueError('missing original paired case')
    return True


def execute(plan,src,ranks,reader_dir,destination):
    from v12_reader_runtime import OriginalCandidateBPE,OriginalCandidateLlama,check_original
    import torch
    validate_plan(plan,src,ranks)
    check_original(reader_dir)
    tok=OriginalCandidateBPE(reader_dir)
    torch.set_num_threads(2)
    model=OriginalCandidateLlama(reader_dir)
    result=Path(destination)
    if result.exists() or Path(str(result)+'.starts.jsonl').exists():raise FileExistsError('one original inference attempt per target')
    starts=Path(str(result)+'.starts.jsonl')
    records={};cpu=time.process_time();wall=time.perf_counter()
    with starts.open('x',encoding='utf-8') as f:
        for rid,row in sorted(plan['requests'].items()):
            ids=tok.encode(row['prompt'])
            if not 1<=len(ids)<=1000:raise ValueError('original Reader context exceeded, no truncation')
            entry=dict(request_id=rid,plan_sha256=digest(plan),original_input_token_sha256=digest(ids),original_input_token_count=len(ids))
            f.write(json.dumps(entry,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
            before=time.process_time()
            generated=model.generate(ids,max_tokens=OUT_CAP)
            answer=tok.decode(generated)
            records[rid]=dict(case_id=row['case_id'],source_ids=row['source_ids'],arm=row['arm'],
                              answer_text=answer,answer_sha256=htext(answer),token_ids=generated,
                              input_tokens=len(ids),output_tokens=len(generated),
                              cpu_seconds=time.process_time()-before)
    packet=dict(schema=SCHEMA+'.original-model-answers',plan_sha256=digest(plan),
                original_reader_weights_sha256=READER_SHA,original_reader_tokenizer_sha256=TOKEN_SHA,
                requests=len(records),model_forwards=model.calls,raw_answers=records,
                execution_cpu_seconds=time.process_time()-cpu,execution_wall_seconds=time.perf_counter()-wall,
                official_hf_numerical_parity_verified=False,independent_semantic_correctness=None,
                stronger_reference_reader_executed=False,production_authorized=False)
    save_new(result,packet)
    return packet


def validate_answers(plan,src,ranks,packet):
    validate_plan(plan,src,ranks)
    if (type(packet)!=dict or packet.get('schema')!=SCHEMA+'.original-model-answers'
        or packet.get('plan_sha256')!=digest(plan)
        or packet.get('original_reader_weights_sha256')!=READER_SHA
        or packet.get('original_reader_tokenizer_sha256')!=TOKEN_SHA
        or packet.get('requests')!=len(plan['requests'])
        or packet.get('official_hf_numerical_parity_verified') is not False
        or packet.get('stronger_reference_reader_executed') is not False
        or packet.get('production_authorized') is not False):
        raise ValueError('false original model provenance')
    got=packet.get('raw_answers')
    if type(got)!=dict or set(got)!=set(plan['requests']):raise ValueError('missing/foreign answer attempts')
    for rid,ans in got.items():
        row=plan['requests'][rid]
        if (type(ans)!=dict or ans.get('case_id')!=row['case_id'] or ans.get('arm')!=row['arm']
            or ans.get('source_ids')!=row['source_ids']
            or ans.get('answer_sha256')!=htext(ans['answer_text'])
            or type(ans.get('token_ids'))!=list or any(type(t)!=int or not 0<=t<49152 for t in ans['token_ids'])
            or len(ans['token_ids'])!=ans.get('output_tokens')
            or not 1<=ans['output_tokens']<=OUT_CAP
            or type(ans.get('input_tokens'))!=int or not 1<=ans['input_tokens']<=1000):
            raise ValueError('altered original model output')
    if type(packet.get('model_forwards'))!=int or packet['model_forwards']<packet['requests']:
        raise ValueError('invented physical forwards')
    return True


def postseal_score(plan,src,ranks,packet,original):
    validate_answers(plan,src,ranks,packet)
    # Original publisher target ANSWERS and source annotations appear only here.
    original_by={entry['sample_id']:entry for entry in original}
    if set(original_by)!=set(src['families']):raise ValueError('changed gold family inventory')
    independently_prepared=prepare(src,ranks,original)
    if independently_prepared!=plan:raise ValueError('postseal publisher witness/selection mismatch')
    byarm={arm:dict(cases=0,publisher_annotated_witness_delivered=0,
                    publisher_target_exact_casefold=0,publisher_target_substring=0,
                    syntactic_citations=0,invalid_citations=0,abstention_literal=0,
                    input_tokens=0,output_tokens=0) for arm in ARMS}
    comparisons={f:dict(answers_changed_retrieved_to_witness=0,cases=0) for f in HELD}
    for case in plan['cases']:
        cid=case['id'];fam=case['family'];idx=int(cid.split('/q')[1]);q=original_by[fam]['qa'][idx]
        target=q.get('answer')
        valid=isinstance(target,str) and bool(target.strip())
        seen={}
        for arm in ARMS:
            rid=case['arms'][arm]['request_id'];resp=packet['raw_answers'][rid];text=resp['answer_text']
            stats=byarm[arm];stats['cases']+=1
            stats['publisher_annotated_witness_delivered']+=int(case['witness_id'] in resp['source_ids'])
            stats['publisher_target_exact_casefold']+=int(valid and text.strip().casefold()==target.strip().casefold())
            stats['publisher_target_substring']+=int(valid and target.strip().casefold() in text.casefold())
            found=_CITE.findall(text)
            stats['syntactic_citations']+=len(found)
            stats['invalid_citations']+=sum(not 1<=int(x)<=len(resp['source_ids']) for x in found)
            stats['abstention_literal']+=int(text.strip().lower()=='unknown')
            stats['input_tokens']+=resp['input_tokens'];stats['output_tokens']+=resp['output_tokens']
            seen[arm]=text
        comparisons[fam]['cases']+=1
        comparisons[fam]['answers_changed_retrieved_to_witness']+=int(seen['retrieved']!=seen['annotated_witness'])
    return dict(schema=SCHEMA+'.sanitized-negative.v1',
                source_sha256=digest(src),plan_sha256=digest(plan),original_model_answer_sha256=digest(packet),
                original_dataset_sha256=CORPUS_SHA,original_reader_sha256=READER_SHA,
                actual_pretrained_reader_requests=packet['requests'],actual_model_forwards=packet['model_forwards'],
                cases=len(plan['cases']),independent_retrospective_source_families=len(HELD),
                per_arm=byarm,per_source_family=comparisons,
                publisher_witness_not_independently_human_verified=True,
                source_annotation_informed_candidate_selection=True,
                reference_reader_not_executed=True,real_future_source_windows=0,
                semantic_task_accuracy_independently_verified=None,
                citation_semantic_entailment_independently_verified=None,
                official_hf_operator_parity_verified=False,
                equivalent_total_lifecycle_compute=False,
                v6_seed41_retention_fixed=False,
                causal_stem_utility_verified=False,stem_winner_verified=False,
                production_authorized=False,decision='HOLD_NO_GO')


def cli():
    a=argparse.ArgumentParser();p=a.add_subparsers(dest='phase',required=True)
    z=p.add_parser('prepare')
    for arg in ('source','bm25','original','output'):z.add_argument('--'+arg,required=True)
    z=p.add_parser('execute')
    for arg in ('source','bm25','plan','reader','output'):z.add_argument('--'+arg,required=True)
    z=p.add_parser('score')
    for arg in ('source','bm25','plan','answers','original','output'):z.add_argument('--'+arg,required=True)
    v=a.parse_args();src=load(v.source);bm=load(v.bm25)
    if v.phase=='prepare':packet=prepare(src,bm,load(v.original))
    elif v.phase=='execute':packet=execute(load(v.plan),src,bm,v.reader,v.output);print(json.dumps({'requests':packet['requests'],'model_forwards':packet['model_forwards']}));return
    else:packet=postseal_score(load(v.plan),src,bm,load(v.answers),load(v.original))
    save_new(v.output,packet)
    print(json.dumps({'phase':v.phase,'cases':len(packet['cases']) if v.phase=='prepare' else packet['cases'],'production_authorized':False}))

if __name__=='__main__':cli()
