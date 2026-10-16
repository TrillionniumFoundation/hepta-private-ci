"""V18 2x2 source length x evidence-heading intervention on sealed original V16/V17.

RESEARCH SHADOW ONLY: original LoCoMo cases were historically selected using
publisher answers. Does not execute a stronger reference, certify semantic QA,
train a Cell, use labels during routing, or authorize any production effects.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from v17_source_focusing import (
    build as build_v17, original_prompt, selected_sentences,
    htext, digest, read, sealed, ANSWER_CAP,
    READER_SHA, TOKEN_SHA, READER_CFG_SHA, CORPUS_SHA,
)

SCHEMA = 'hepta.stem.v18.original-reader-heading-length-factorial.shadow.v1'
ARMS = ('full_focus_heading', 'focused_full_heading')
ALL_ARMS = ('full_full_heading', 'full_focus_heading',
            'focused_full_heading', 'focused_focus_heading')


def build(source, ranks, v16, v17):
    """Requires EXACT original V17 source-first bytes and creates only novel inputs."""
    original = build_v17(source, ranks, v16)
    if original != v17:
        raise ValueError('V17 source, model, originally sealed intervention changed')
    unique = {}
    cases = []
    seen = set()
    for case in v17['cases']:
        qid = case['case_id']
        fam = case['family']
        if qid in seen:
            raise ValueError('duplicate original question')
        seen.add(qid)
        qs = {q['id']:q['text'] for q in source['families'][fam]['questions']}
        docs = {d['id']:d['text'] for d in source['families'][fam]['passages']}
        q = qs[qid]
        witness = case['witness_id']
        ids = v17['requests'][case['arms']['formatted_full']]['source_ids']
        if ids[0] != witness or len(ids) != 3 or len(set(ids)) != 3:
            raise ValueError('changed original source membership')
        focus, offsets, n = selected_sentences(q, docs[witness])
        if (case['focus_offsets'] != offsets or
                case['focus_changed'] != (focus != docs[witness].strip())):
            raise ValueError('unrecognized original source focusing span')
        cross = {}
        for arm in ARMS:
            focused_heading = arm == 'full_focus_heading'
            focused_body = arm == 'focused_full_heading'
            changed = dict(docs)
            if focused_body:
                changed[witness] = focus
            prompt = original_prompt(q,ids,changed,focused=focused_heading)
            rid = htext(prompt)
            old = v17['requests'].get(rid)
            reused = old is not None
            if reused:
                if (old['prompt'] != prompt or old['source_ids'] != ids or
                    old['case_id'] != qid or old['family'] != fam):
                    raise ValueError('V17 lookup collision/authority confusion')
            else:
                if rid in unique:
                    raise ValueError('novel prompt collision across cases/arms')
                unique[rid] = {
                    'case_id':qid,'family':fam,'arm':arm,
                    'question_sha256':htext(q),'source_ids':ids,
                    'evidence_text_sha256':[htext(changed[x]) for x in ids],
                    'prompt':prompt,
                }
            cross[arm] = {'request_id':rid,'reused_v17':reused}
        cases.append({
            'case_id':qid,'family':fam,'cohort':case['cohort'],
            'original_focus_changed':case['focus_changed'],
            'cross_arms':cross,
            'full_full_heading':case['arms']['formatted_full'],
            'focused_focus_heading':case['arms']['formatted_focused'],
        })
    if (len(cases)!=32 or v17['source_changed_cases']!=29 or
        len(unique)!=58 or sum(c[a]['reused_v17'] for c in (row['cross_arms'] for row in cases)
                               for a in ARMS)!=6):
        raise ValueError('original complete 29 changed / 3 unchanged case roster required')
    if set(unique) & set(v17['requests']):
        raise ValueError('preexisting request treated as new')
    return {
        'schema':SCHEMA+'.source-only-plan','v16_plan_sha256':digest(v16),
        'v17_plan_sha256':digest(v17),'source_sha256':digest(source),'rank_sha256':digest(ranks),
        'reader_weights_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
        'reader_config_sha256':READER_CFG_SHA,'dataset_sha256':CORPUS_SHA,
        'new_arms':list(ARMS),'factorial_arms':list(ALL_ARMS),
        'cases':cases,'new_requests':unique,'novel_physical_requests':58,
        'reused_unchanged_model_requests':6,'existing_v17_requests':64,
        'question_count':32,'changed_source_cases':29,'max_new_tokens':ANSWER_CAP,
        'publisher_gold_available_to_producer':False,
        'historical_parent_answer_conditional':True,
        'human_verified_sufficiency':False,'independent_semantic_correctness':None,
        'stronger_reference_executed':False,'future_calendar_windows':0,
        'production_authorized':False,
    }


def verify(plan, source, ranks, v16, v17):
    if plan != build(source,ranks,v16,v17):
        raise ValueError('V18 source-first exact bytes or registered arms changed')
    return plan


def run(plan,source,ranks,v16,v17,reader_dir,destination):
    from v12_reader_runtime import check_original,OriginalCandidateBPE,OriginalCandidateLlama
    import torch
    verify(plan,source,ranks,v16,v17)
    check_original(reader_dir)
    tokenizer=OriginalCandidateBPE(reader_dir)
    torch.set_num_threads(2)
    model=OriginalCandidateLlama(reader_dir)
    dest=Path(destination)
    starts=Path(str(dest)+'.starts.jsonl')
    if dest.exists() or starts.exists():
        raise FileExistsError('original physical journal must be create-only')
    pairs={}; t0=time.process_time(); w0=time.perf_counter()
    with starts.open('x',encoding='utf8') as stream:
        for rid,row in sorted(plan['new_requests'].items()):
            tokens=tokenizer.encode(row['prompt'])
            if not 1<=len(tokens)<=1000:
                raise ValueError('Reader context exceeded; never truncate')
            pre={'request_id':rid,'plan_sha256':digest(plan),'input_tokens':len(tokens),
                 'input_ids_sha256':digest(tokens)}
            stream.write(json.dumps(pre,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
            ts=time.process_time()
            ids=model.generate(tokens,max_tokens=ANSWER_CAP)
            answer=tokenizer.decode(ids)
            pairs[rid]={'case_id':row['case_id'],'arm':row['arm'],'source_ids':row['source_ids'],
                        'answer_text':answer,'answer_sha256':htext(answer),'output_ids':ids,
                        'input_tokens':len(tokens),'output_tokens':len(ids),'cpu_seconds':time.process_time()-ts}
    result={'schema':SCHEMA+'.original-physical-answers','plan_sha256':digest(plan),
            'model_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
            'requests':len(pairs),'model_forwards':model.calls,'raw_answers':pairs,
            'cpu_seconds':time.process_time()-t0,'wall_seconds':time.perf_counter()-w0,
            'pretrained_model_executed':True,'independently_human_reviewed':False,
            'official_HF_parity':False,'reference_reader_executed':False,
            'source_independent_future':False,'production_authorized':False}
    sealed(dest,result)
    return result


def main():
    p=argparse.ArgumentParser()
    sp=p.add_subparsers(dest='command',required=True)
    def common(s):
        s.add_argument('--source',required=True);s.add_argument('--ranks',required=True)
        s.add_argument('--v16-plan',required=True);s.add_argument('--v17-plan',required=True)
    s=sp.add_parser('prepare'); common(s);s.add_argument('--out',required=True)
    s=sp.add_parser('run');common(s);s.add_argument('--plan',required=True)
    s.add_argument('--reader-dir',required=True);s.add_argument('--out',required=True)
    a=p.parse_args()
    src=read(a.source);ranks=read(a.ranks);v16=read(a.v16_plan);v17=read(a.v17_plan)
    if a.command=='prepare':
        sealed(a.out,build(src,ranks,v16,v17))
    else:
        plan=read(a.plan)
        print(json.dumps({k:v for k,v in run(plan,src,ranks,v16,v17,a.reader_dir,a.out).items() if k!='raw_answers'},sort_keys=True))

if __name__=='__main__':main()
