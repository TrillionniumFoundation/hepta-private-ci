"""Original 135M Reader: physical evidence-absence abstention intervention.

SHADOW_ONLY / DENY_ALL. Deterministic no-source abstention is a protocol guard,
not neural learning, reader capacity, semantic correctness or production authority.
Exactly 32 source-free requests bypass the model; 96 original V16 requests still
require genuine pretrained model execution on the frozen source/weights.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import time

from v21_original_plan_rebuilder import V16_PLAN_SHA, READER_SHA, TOKEN_SHA, READER_CFG_SHA, ARMS, digest, htext, canonical
from v22_original_crosshost_execute import validate_inputs, read_private, create_fd, seal

SCHEMA = 'hepta.stem.v23.original-evidence-absence-gate.shadow.v1'
EXPECTED = {'none':32, 'retrieved':32, 'witness':32, 'lesion':32}
GUARD = 'deterministic_no_evidence_abstain'
MODEL = 'original_pretrained_reader'


def admitted_roster(source, routes, plan):
    validate_inputs(source,routes,plan)
    census = {a:0 for a in ARMS}
    for rid, row in plan['requests'].items():
        arm = row['arm']; ids = row['source_ids']
        if arm not in census or type(ids) is not list or any(type(x) is not str for x in ids):
            raise ValueError('unrecognized original evidence inventory')
        if (arm == 'none') != (len(ids) == 0):
            raise ValueError('no evidence mask inconsistent with frozen arm')
        if arm == 'retrieved' and len(ids) != 3:
            raise ValueError('retrieved top3 incomplete')
        if arm == 'witness' and len(ids) != 3:
            raise ValueError('annotated witness evidence incomplete')
        if arm == 'lesion' and len(ids) != 2:
            raise ValueError('lesion two-source restriction missing')
        census[arm] += 1
    if census != EXPECTED:
        raise ValueError('original 32x4 source-first roster incomplete')
    return census


def guard_decision(arm, ids):
    """No reliance on a learned confidence score or publisher gold."""
    if type(arm) is not str or type(ids) is not list:
        raise ValueError('wrong typed route')
    if arm not in EXPECTED or any(type(x) is not str or not x for x in ids):
        raise ValueError('unknown original arm/source identity')
    if arm == 'none':
        if ids: raise ValueError('source-free control cannot have evidence')
        return GUARD
    if not ids:raise ValueError('cannot silently generate without admitted evidence')
    return MODEL


def execute(source,routes,plan,reader_dir,output,*,driver=None,tokenizer=None,limit=None):
    admitted_roster(source,routes,plan)
    out_path=Path(output);journal_path=Path(str(out_path)+'.decisions.jsonl')
    if out_path.exists() or journal_path.exists() or out_path.is_symlink() or journal_path.is_symlink():
        raise ValueError('sealed output and attempt journal must be create-only')
    if (driver is None) != (tokenizer is None):
        raise ValueError('mixed physical model and test-only fake tokenizer forbidden')
    actual = driver is None
    if actual:
        import torch
        from v12_reader_runtime import check_original, OriginalCandidateBPE,OriginalCandidateLlama
        check_original(reader_dir)
        torch.set_num_threads(2)
        tokenizer=OriginalCandidateBPE(reader_dir)
        driver=OriginalCandidateLlama(reader_dir)
    if limit is not None and (type(limit)is not int or not 1<=limit<128):
        raise ValueError('limit is only for incomplete denial tests')
    records={};guard_n=model_n=0;observed_input=observed_output=0
    cpu0=time.process_time();wall0=time.perf_counter()
    with create_fd(journal_path) as journal:
        for i,(rid,row) in enumerate(sorted(plan['requests'].items())):
            if limit is not None and i >= limit:break
            route=guard_decision(row['arm'],row['source_ids'])
            if route == GUARD:
                input_ids=[]
            else:
                input_ids=tokenizer.encode(row['prompt'])
                if (type(input_ids)is not list or not 1<=len(input_ids)<=1000 or
                    any(type(t)is not int or not 0<=t<49152 for t in input_ids)):
                    raise ValueError('actual source-bound input tokenizer invalid')
            started={'request_id':rid,'plan_sha256':V16_PLAN_SHA,'route':route,
                     'input_tokens':len(input_ids),
                     'input_ids_sha256':digest(input_ids) if input_ids else None}
            journal.write(canonical(started)+b'\n');journal.flush();os.fsync(journal.fileno())
            if route==GUARD:
                guard_n+=1
                text='unknown';out_ids=[];cost=0.0
            else:
                tick=time.process_time()
                out_ids=driver.generate(input_ids,max_tokens=24)
                cost=time.process_time()-tick
                if (type(out_ids)is not list or not 1<=len(out_ids)<=24
                    or any(type(k)is not int or not 0<=k<49152 for k in out_ids)
                    or not math.isfinite(cost) or cost<0):
                    raise ValueError('actual neural forward did not produce a valid bounded result')
                text=tokenizer.decode(out_ids)
                model_n+=1;observed_input+=len(input_ids);observed_output+=len(out_ids)
                if actual and model_n%16==0:
                    print('v23-original-model-physical-progress',model_n,'of 96',flush=True)
            if type(text)is not str:
                raise ValueError('wrong output type')
            records[rid]={'case_id':row['case_id'],'arm':row['arm'],
                          'source_ids':row['source_ids'],'route':route,
                          'answer_text':text,'answer_sha256':htext(text),
                          'token_ids':out_ids,'input_tokens':len(input_ids),
                          'output_tokens':len(out_ids),'model_cpu_seconds':cost}
    if len(records)!=128 or guard_n!=32 or model_n!=96:
        raise ValueError('incomplete original physical guard experiment; refuse sealed output')
    full_cpu=time.process_time()-cpu0;full_wall=time.perf_counter()-wall0
    if any(not math.isfinite(t) or t<0 for t in (full_cpu,full_wall)):
        raise ValueError('nonfinite time observations')
    packet={'schema':SCHEMA+'.sealed-private-original-answers','plan_sha256':V16_PLAN_SHA,
            'model_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
            'reader_config_sha256':READER_CFG_SHA,
            'requests':128,'model_requests':model_n,'guard_requests':guard_n,
            'model_forwards':driver.calls,'model_input_tokens':observed_input,
            'model_output_tokens':observed_output,'total_cpu_seconds':full_cpu,
            'total_wall_seconds':full_wall,'raw_answers':records,
            'true_pretrained_backend':actual,'reference_qwen_executed':False,
            'human_semantic_correctness':None,'production_authorized':False}
    seal(out_path,packet)
    return {'guard_abstentions':guard_n,'original_model_calls':model_n,
            'original_pretrained_forwards':driver.calls,'input_tokens':observed_input,
            'output_tokens':observed_output,'cpu_seconds':full_cpu,
            'wall_seconds':full_wall,'true_pretrained_backend':actual,
            'production_authorized':False}


def main():
    p=argparse.ArgumentParser()
    for k in ('source','routes','plan','reader','answers'):p.add_argument('--'+k,required=True)
    a=p.parse_args()
    print(json.dumps(execute(read_private(a.source),read_private(a.routes),read_private(a.plan),
                             a.reader,a.answers),sort_keys=True))

if __name__=='__main__':main()
