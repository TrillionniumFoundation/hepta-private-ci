"""Fresh physical 135M V16 baseline replay on exactly reconstructed private prompts.

Research only / SHADOW_ONLY / DENY_ALL. Does not use Qwen, score publisher
answers, attest an independent host, train Cells, or authorize production.
The original model implementation is imported from the frozen V12 owner module.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

from v21_original_plan_rebuilder import (
    V16_PLAN_SHA, PRIVATE_ROUTE_SHA, SOURCE_SHA, READER_SHA, TOKEN_SHA,
    READER_CFG_SHA, ARMS, digest, htext, source_routes, canonical,
)

SCHEMA = 'hepta.stem.v16.original-literal-answer-witness.shadow.v1'
MAX_SOURCE_BYTES = 8_000_000
MAX_RESULT_BYTES = 2_000_000


def pairs_unique(pairs):
    o={}
    for k,v in pairs:
        if k in o:raise ValueError('duplicate private JSON key')
        o[k]=v
    return o


def read_private(path, cap=MAX_SOURCE_BYTES):
    p=Path(path)
    if (p.is_symlink() or not p.is_file() or not stat.S_ISREG(p.stat().st_mode)
        or not 0<p.stat().st_size<=cap):
        raise ValueError('missing/unsafe/oversized private record')
    return json.loads(p.read_bytes(),object_pairs_hook=pairs_unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite private JSON')))


def create_fd(path):
    p=Path(path)
    if p.is_symlink() or p.exists() or not p.parent.is_dir() or p.parent.is_symlink():
        raise ValueError('create-only local file would overwrite or escape')
    return os.fdopen(os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb')


def seal(path,packet):
    data=canonical(packet)+b'\n'
    if len(data)>MAX_RESULT_BYTES:raise ValueError('private answer packet too large')
    with create_fd(path) as fp:
        fp.write(data);fp.flush();os.fsync(fp.fileno())


def validate_inputs(source,routes,plan):
    if type(source)is not dict or digest(source)!=SOURCE_SHA:
        raise ValueError('original source-only identity mismatch')
    if type(routes)is not dict or digest(routes)!=PRIVATE_ROUTE_SHA:
        raise ValueError('original private BM25 envelope drift')
    if type(plan)is not dict or digest(plan)!=V16_PLAN_SHA:
        raise ValueError('original exact 128-request plan mismatch')
    if (plan.get('source_sha256')!=SOURCE_SHA or plan.get('bm25_routes_sha256')!=PRIVATE_ROUTE_SHA
        or plan.get('reader_sha256')!=READER_SHA or plan.get('tokenizer_sha256')!=TOKEN_SHA
        or plan.get('reader_config_sha256')!=READER_CFG_SHA
        or plan.get('frozen_arms')!=list(ARMS)
        or plan.get('answer_dependent_historical_selection') is not True
        or plan.get('label_text_entered_model_prompts') is not False
        or plan.get('production_authorized') is not False
        or type(plan.get('requests')) is not dict or len(plan['requests'])!=128
        or type(plan.get('cases')) is not list or len(plan['cases'])!=32):
        raise ValueError('unrecognized original experiment')
    if source_routes(source)!=routes:
        raise ValueError('private original BM25 not reproducible')
    lookup={d['id']:d['text'] for f in source['family_order'] for d in source['families'][f]['passages']}
    for key,row in plan['requests'].items():
        if (type(row)is not dict or set(row)!={'case_id','family','arm','prompt','source_ids','question_sha256'}
            or row['arm'] not in ARMS or row['family'] not in source['families']
            or type(row['source_ids']) is not list or len(set(row['source_ids']))!=len(row['source_ids'])
            or any(x not in lookup for x in row['source_ids'])
            or htext(row['prompt'])!=key):
            raise ValueError('altered original source/request id')
    return True


def replay(source,routes,plan,reader_dir,output,*,driver=None,tokenizer=None,limit=None):
    """Physical model forward required by default. Injection supports denial tests only."""
    validate_inputs(source,routes,plan)
    output=Path(output)
    starts=Path(str(output)+'.starts.jsonl')
    if output.exists() or starts.exists() or output.is_symlink() or starts.is_symlink():
        raise ValueError('refuse overwrite of physical model result or starts')
    if (driver is None) != (tokenizer is None):
        raise ValueError('model and tokenizer must be paired')
    actual_model_backend = driver is None
    if driver is None:
        import torch
        from v12_reader_runtime import check_original,OriginalCandidateBPE,OriginalCandidateLlama
        check_original(reader_dir)
        torch.set_num_threads(2)
        tokenizer=OriginalCandidateBPE(reader_dir)
        driver=OriginalCandidateLlama(reader_dir)
    if limit is not None and (type(limit) is not int or limit<1 or limit>=128):
        raise ValueError('limit only for explicitly incomplete denial probes')
    t_cpu=time.process_time();t_wall=time.perf_counter();answers={}
    with create_fd(starts) as journal:
        for index,(rid,row) in enumerate(sorted(plan['requests'].items())):
            if limit is not None and index==limit:break
            tokens=tokenizer.encode(row['prompt'])
            if (type(tokens)is not list or not 1<=len(tokens)<=1000 or
                any(type(t) is not int or not 0<=t<49152 for t in tokens)):
                raise ValueError('actual original tokens unsupported')
            start={'request_id':rid,'plan_sha256':V16_PLAN_SHA,
                   'input_ids_sha256':digest(tokens),'input_token_count':len(tokens)}
            journal.write(canonical(start)+b'\n');journal.flush();os.fsync(journal.fileno())
            tick=time.process_time();out_ids=driver.generate(tokens,max_tokens=24)
            if (type(out_ids)is not list or not 1<=len(out_ids)<=24 or
                any(type(t) is not int or not 0<=t<49152 for t in out_ids)):
                raise ValueError('invalid real generated token sequence')
            answer=tokenizer.decode(out_ids)
            if type(answer) is not str:raise ValueError('undecodable original answer')
            cost=time.process_time()-tick
            if not math.isfinite(cost) or cost<0:raise ValueError('invalid CPU observation')
            answers[rid]={'case_id':row['case_id'],'arm':row['arm'],
                 'source_ids':row['source_ids'],'answer_text':answer,'answer_sha256':htext(answer),
                 'token_ids':out_ids,'input_tokens':len(tokens),'output_tokens':len(out_ids),
                 'cpu_seconds':cost}
            if actual_model_backend and (index+1)%16==0:
                print('original-physical-progress',index+1,'of 128',flush=True)
    if len(answers)!=128:
        raise ValueError('incomplete original-model run deliberately NOT sealed')
    cpu=time.process_time()-t_cpu;wall=time.perf_counter()-t_wall
    if not all(math.isfinite(x) and x>=0 for x in (cpu,wall)):
        raise ValueError('invalid complete model work measurements')
    packet={'schema':SCHEMA+'.actual-original-reader-results',
        'plan_sha256':V16_PLAN_SHA,'model_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
        'reader_config_sha256':READER_CFG_SHA,'model_forwards':driver.calls,
        'requests':128,'raw_answers':answers,'execution_cpu_seconds':cpu,
        'execution_wall_seconds':wall,'stronger_reference_reader_executed':False,
        'human_verified_sufficiency':False,'independent_semantic_correctness':None,
        'hf_operator_tokenizer_parity':False,'production_authorized':False}
    seal(output,packet)
    return {'requests':128,'real_model_forward_calls':driver.calls,
            'cpu_seconds':cpu,'wall_seconds':wall,
            'candidate_is_original_135m':True,'stronger_reference_reader_executed':False,
            'production_authorized':False}


def main():
    p=argparse.ArgumentParser()
    for key in ('source','routes','plan','reader','answers'):
        p.add_argument('--'+key,required=True)
    a=p.parse_args()
    source=read_private(a.source)
    routes=read_private(a.routes)
    plan=read_private(a.plan)
    result=replay(source,routes,plan,a.reader,a.answers)
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
