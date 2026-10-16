"""V19: source-only concentric source windows around V17's selected sentence.

Physical original 135M Reader experiment. Historical answer-conditioned cohort.
No publisher answers in source-first plan, no model selection, no production use.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import time

from v17_source_focusing import SENTENCE, selected_sentences, original_prompt, read, sealed, digest, htext
from v18_factorial_original_reader import build as build_v18, SCHEMA as V18_SCHEMA
from v16_literal_witness_reader import READER_SHA, TOKEN_SHA, READER_CFG_SHA

SCHEMA = 'hepta.stem.v19.original-reader-concentric-witness.shadow.v1'
ARMS = ('window_plus_1', 'window_plus_2')
CAP = 24


def window_span(question: str, full: str, radius: int):
    """Verbatim contiguous source slice; never use target answers to choose a window."""
    if type(question) is not str or type(full) is not str or type(radius) is not int or radius not in (1, 2):
        raise ValueError('unregistered context radius')
    selected, offsets, _ = selected_sentences(question, full)
    slices = []
    for match in SENTENCE.finditer(full):
        start, end = match.span()
        while start < end and full[start].isspace(): start += 1
        while end > start and full[end - 1].isspace(): end -= 1
        if start < end: slices.append((start, end))
    at = [idx for idx, (start, end) in enumerate(slices) if [start, end] == offsets]
    if len(at) != 1 or full[offsets[0]:offsets[1]] != selected:
        raise ValueError('exact original selected sentence not located')
    idx = at[0]
    a = slices[max(0, idx - radius)][0]
    b = slices[min(len(slices) - 1, idx + radius)][1]
    text = full[a:b]
    if not text or text not in full or selected not in text:
        raise ValueError('context window is not original source bytes')
    return text, [a,b], len(slices)


def build(source, ranks, v16, v17, v18):
    if build_v18(source, ranks, v16, v17) != v18:
        raise ValueError('upstream original V18 byte lineage changed')
    cases = []; unique = {}; old17 = old18 = overlap = 0
    seen_cases = set()
    v17_cases = {x['case_id']:x for x in v17['cases']}
    for vcase in v18['cases']:
        qid = vcase['case_id']; fam = vcase['family']
        if qid in seen_cases or qid not in v17_cases: raise ValueError('question collision')
        seen_cases.add(qid)
        orig = v17_cases[qid]
        witness = orig['witness_id']
        docs = {x['id']:x['text'] for x in source['families'][fam]['passages']}
        question = next((x['text'] for x in source['families'][fam]['questions'] if x['id'] == qid),None)
        if question is None or witness not in docs: raise ValueError('original source/QA missing')
        ids = v17['requests'][orig['arms']['formatted_full']]['source_ids']
        if ids != [witness, *v16_case(v16, qid)['arms']['lesion']['evidence_ids']]:
            raise ValueError('source IDs changed')
        arms = {}
        for radius, arm in ((1, ARMS[0]), (2, ARMS[1])):
            chunk, offsets, n = window_span(question, docs[witness], radius)
            changed = dict(docs); changed[witness] = chunk
            prompt = original_prompt(question, ids, changed, focused=False)
            rid = htext(prompt)
            if rid in v17['requests']:
                old17 += 1; kind = 'v17'
                old_row = v17['requests'][rid]
                if old_row['case_id'] != qid or old_row['source_ids'] != ids or old_row['prompt'] != prompt:
                    raise ValueError('V17 source identity collision')
            elif rid in v18['new_requests']:
                old18 += 1;kind = 'v18'
                old_row = v18['new_requests'][rid]
                if old_row['case_id'] != qid or old_row['source_ids'] != ids or old_row['prompt'] != prompt:
                    raise ValueError('V18 source identity collision')
            elif rid in unique:
                overlap += 1; kind = 'new'
                if unique[rid]['case_id'] != qid or unique[rid]['prompt'] != prompt:
                    raise ValueError('two cases reused a model input')
            else:
                kind = 'new'
                unique[rid] = dict(case_id=qid, family=fam, arm=arm, prompt=prompt,
                                   source_ids=ids, question_sha256=htext(question),
                                   evidence_text_sha256=[htext(changed[i]) for i in ids])
            arms[arm] = dict(request_id=rid, reuse=kind, span=offsets,
                             text_sha256=htext(chunk), shortened=len(chunk)<len(docs[witness].strip()),
                             sentence_count=n)
        cases.append(dict(case_id=qid, family=fam, cohort=vcase['cohort'],
                          witness_id=witness, source_ids=ids, arms=arms))
    if (len(cases),len(unique),old17,old18,overlap) != (32,23,40,0,1):
        raise ValueError('unexpected original V19 window request census')
    return dict(schema=SCHEMA+'.source-only', source_sha256=digest(source),ranks_sha256=digest(ranks),
                v16_plan_sha256=digest(v16),v17_plan_sha256=digest(v17),v18_plan_sha256=digest(v18),
                reader_weights_sha256=READER_SHA,reader_tokenizer_sha256=TOKEN_SHA,
                reader_config_sha256=READER_CFG_SHA, original_historical_cohort=32,
                new_original_requests=23, reused_prior_V17_slots=40,
                reused_prior_V18_slots=0, duplicated_new_input_slots=1,
                arms=list(ARMS), max_new_tokens=CAP,cases=cases,new_requests=unique,
                publisher_answers_accessed_during_planning=False,
                historical_answer_conditioned_parent=True,
                independent_semantic_correctness=None,independently_reviewed_sufficient_evidence=False,
                pretrained_reference_reader_executed=False,source_independent_future_windows=0,
                production_authorized=False)


def v16_case(v16, qid):
    matches = [x for x in v16['cases'] if x['id']==qid]
    if len(matches)!=1:raise ValueError('wrong original parent case')
    return matches[0]


def run(plan, source, ranks, v16, v17, v18, reader_root, out):
    from v12_reader_runtime import check_original, OriginalCandidateBPE, OriginalCandidateLlama
    import torch
    if plan != build(source,ranks,v16,v17,v18): raise ValueError('V19 unsealed or mutated source-first plan')
    check_original(reader_root)
    torch.set_num_threads(2)
    tok=OriginalCandidateBPE(reader_root);model=OriginalCandidateLlama(reader_root)
    output=Path(out);starts=Path(str(output)+'.starts.jsonl')
    if output.exists() or output.is_symlink() or starts.exists():raise FileExistsError('create-only original Reader journal')
    t0=time.process_time();w0=time.perf_counter();answers={}
    with starts.open('x',encoding='utf-8') as journal:
        for rid,row in sorted(plan['new_requests'].items()):
            tokens=tok.encode(row['prompt'])
            if not 1<=len(tokens)<=1000:raise ValueError('model context would be truncated')
            start=dict(request_id=rid,plan_sha256=digest(plan),input_tokens=len(tokens),input_ids_sha256=digest(tokens))
            journal.write(json.dumps(start,sort_keys=True)+'\n');journal.flush();os.fsync(journal.fileno())
            a=time.process_time();generated=model.generate(tokens,max_tokens=CAP);response=tok.decode(generated)
            answers[rid]=dict(case_id=row['case_id'],arm=row['arm'],source_ids=row['source_ids'],
                              input_tokens=len(tokens),output_tokens=len(generated),output_ids=generated,
                              answer_text=response,answer_sha256=htext(response),cpu_seconds=time.process_time()-a)
    result=dict(schema=SCHEMA+'.original-physical',plan_sha256=digest(plan),model_sha256=READER_SHA,
                tokenizer_sha256=TOKEN_SHA,requests=len(answers),model_forwards=model.calls,
                input_tokens=sum(x['input_tokens'] for x in answers.values()),
                output_tokens=sum(x['output_tokens'] for x in answers.values()),
                cpu_seconds=time.process_time()-t0,wall_seconds=time.perf_counter()-w0,
                raw_answers=answers,pretrained_model_executed=True,independent_human_semantic_correctness=None,
                reference_reader_executed=False,official_HF_parity=False,production_authorized=False)
    sealed(output,result)
    return result


def main():
    ap=argparse.ArgumentParser();s=ap.add_subparsers(dest='cmd',required=True)
    for c in ('prepare','run'):
        x=s.add_parser(c)
        for arg in ('source','ranks','v16-plan','v17-plan','v18-plan'):x.add_argument('--'+arg,required=True)
        if c=='run':x.add_argument('--plan',required=True);x.add_argument('--reader-dir',required=True)
        x.add_argument('--out',required=True)
    a=ap.parse_args();load=read
    source=load(a.source);ranks=load(a.ranks);v16=load(a.v16_plan);v17=load(a.v17_plan);v18=load(a.v18_plan)
    if a.cmd=='prepare':sealed(a.out,build(source,ranks,v16,v17,v18))
    else:print(json.dumps({k:v for k,v in run(load(a.plan),source,ranks,v16,v17,v18,a.reader_dir,a.out).items() if k!='raw_answers'},sort_keys=True))

if __name__=='__main__':main()
