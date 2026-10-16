"""V24 original 135M: physical source-range-specific citation prompt intervention.

RESEARCH / SHADOW_ONLY / DENY_ALL. Thirty-two precommitted historical lesion
questions, exact same source IDs/text, original 135M model and 24-token decoding.
Change ONLY the system clause listing eligible citation IDs from E1/E2/E3 to
E1/E2. No labels enter plan preparation or physical inference. No production
selection, independent semantic accuracy, NDU/Cell training or Qwen claims.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import time

from v21_original_plan_rebuilder import (
    V16_PLAN_SHA, SOURCE_SHA, PRIVATE_ROUTE_SHA, READER_SHA, TOKEN_SHA,
    READER_CFG_SHA, digest, htext, canonical,
)
from v22_original_crosshost_execute import validate_inputs, read_private, create_fd, seal

SCHEMA = 'hepta.stem.v24.original-lesion-citation-scope.shadow.v1'
ORIGINAL = 'Cite supporting evidence using [E1], [E2] or [E3].'
INTERVENTION = 'Cite supporting evidence using [E1] or [E2].'
MAX_NEW = 24


def build(source, routes, original):
    validate_inputs(source,routes,original)
    requests={}; lineage=[]; selected=[]
    for old_id,row in sorted(original['requests'].items()):
        if row['arm']!='lesion': continue
        if (type(row['source_ids']) is not list or len(row['source_ids'])!=2
            or any(type(x) is not str or not x for x in row['source_ids'])
            or type(row['prompt']) is not str or row['prompt'].count(ORIGINAL)!=1):
            raise ValueError('old prompt not the exact 2-source lesion experiment')
        revised=row['prompt'].replace(ORIGINAL,INTERVENTION)
        if revised==row['prompt'] or revised.count(INTERVENTION)!=1:
            raise ValueError('citation range did not change exactly once')
        request_id=htext(revised)
        if request_id in requests or request_id in original['requests']:
            raise ValueError('colliding original/intervention request')
        requests[request_id]={
            'old_request_id':old_id, 'case_id':row['case_id'], 'family':row['family'],
            'source_ids':row['source_ids'], 'question_sha256':row['question_sha256'],
            'prompt':revised,
        }
        lineage.append([old_id,request_id,row['source_ids']])
        selected.append(row['case_id'])
    if len(requests)!=32 or len(set(selected))!=32 or len(set(selected))!=len(original['cases']):
        raise ValueError('missing/duplicate 32 original lesion cases')
    return {
        'schema':SCHEMA+'.private-frozen-plan',
        'original_plan_sha256':V16_PLAN_SHA,'source_sha256':SOURCE_SHA,
        'routes_sha256':PRIVATE_ROUTE_SHA,'original_model_sha256':READER_SHA,
        'tokenizer_sha256':TOKEN_SHA,'reader_config_sha256':READER_CFG_SHA,
        'changed_clause_only':True,'original_source_ids_and_text_unchanged':True,
        'original_gold_available_to_producer':False,'answer_dependent_retrospective_cohort':True,
        'original_correlated_roots':4,'original_lesion_cases':32,'max_new_tokens':MAX_NEW,
        'lineage_sha256':digest(lineage),'requests':requests,
        'human_semantic_accuracy':None,'reference_qwen_executed':False,
        'production_authorized':False,
    }


def execute(source,routes,original,plan,reader_dir,out,*,driver=None,tokenizer=None,limit=None):
    if build(source,routes,original)!=plan:raise ValueError('original source/plan or citation intervention changed')
    out=Path(out); starts=Path(str(out)+'.starts.jsonl')
    if out.exists() or out.is_symlink() or starts.exists() or starts.is_symlink():
        raise ValueError('private physical results must be new')
    if (driver is None)!=(tokenizer is None):raise ValueError('incompatible model and tokenizer injection')
    true_backend=driver is None
    if true_backend:
        import torch
        from v12_reader_runtime import check_original, OriginalCandidateBPE, OriginalCandidateLlama
        check_original(reader_dir)
        torch.set_num_threads(2)
        tokenizer=OriginalCandidateBPE(reader_dir)
        driver=OriginalCandidateLlama(reader_dir)
    if limit is not None and (type(limit) is not int or not 1<=limit<32):
        raise ValueError('partial execution only for explicit incomplete-test denial')
    records={};start_cpu=time.process_time();start_wall=time.perf_counter()
    with create_fd(starts) as journal:
        for i,(rid,row) in enumerate(sorted(plan['requests'].items())):
            if limit is not None and i>=limit:break
            ids=tokenizer.encode(row['prompt'])
            if (type(ids) is not list or not 1<=len(ids)<=1000
                or any(type(t) is not int or not 0<=t<49152 for t in ids)):
                raise ValueError('new source-scope prompt invalid for original Reader')
            begin={'request_id':rid,'plan_sha256':digest(plan),'input_ids_sha256':digest(ids),
                   'input_tokens':len(ids)}
            journal.write(canonical(begin)+b'\n');journal.flush()
            import os
            os.fsync(journal.fileno())
            before=time.process_time()
            output_ids=driver.generate(ids,max_tokens=MAX_NEW)
            cpu=time.process_time()-before
            if (type(output_ids) is not list or not 1<=len(output_ids)<=MAX_NEW
                or any(type(t) is not int or not 0<=t<49152 for t in output_ids)
                or not math.isfinite(cpu) or cpu<0):
                raise ValueError('original physical token generation invalid')
            decoded=tokenizer.decode(output_ids)
            if type(decoded)is not str: raise ValueError('invalid model decoded answer')
            records[rid]={'case_id':row['case_id'],'family':row['family'],
                          'source_ids':row['source_ids'],'answer_text':decoded,
                          'answer_sha256':htext(decoded),'token_ids':output_ids,
                          'input_tokens':len(ids),'output_tokens':len(output_ids),
                          'cpu_seconds':cpu}
            if true_backend and (i+1)%8==0:
                print('v24-original-physical',i+1,'of 32',flush=True)
    if len(records)!=32: raise ValueError('incomplete actual reference-prompt experiment not sealed')
    cpu=time.process_time()-start_cpu;wall=time.perf_counter()-start_wall
    if not all(math.isfinite(v) and 0<v<5000 for v in (cpu,wall)):
        raise ValueError('invalid process wall/cpu metering')
    packet={
        'schema':SCHEMA+'.physical-answers', 'plan_sha256':digest(plan),
        'original_plan_sha256':V16_PLAN_SHA,'original_model_sha256':READER_SHA,
        'tokenizer_sha256':TOKEN_SHA,'reader_config_sha256':READER_CFG_SHA,
        'physical_requests':len(records),'model_forwards':driver.calls,
        'original_model_input_tokens':sum(v['input_tokens'] for v in records.values()),
        'original_model_output_tokens':sum(v['output_tokens'] for v in records.values()),
        'cpu_seconds':cpu,'wall_seconds':wall,'raw_answers':records,
        'true_pretrained_backend':true_backend,'original_labels_loaded':False,
        'human_semantic_accuracy':None,'qwen_reference_executed':False,
        'production_authorized':False,
    }
    seal(out,packet)
    return {'physical_requests':32,'forwards':driver.calls,'cpu_seconds':cpu,
            'wall_seconds':wall,'true_pretrained_backend':true_backend,
            'production_authorized':False}


def main():
    p=argparse.ArgumentParser()
    s=p.add_subparsers(dest='action',required=True)
    for op in ('prepare','execute'):
        x=s.add_parser(op)
        for arg in ('source','routes','original-plan','plan'):
            x.add_argument('--'+arg,required=True)
        if op=='execute':
            x.add_argument('--reader',required=True);x.add_argument('--output',required=True)
    a=p.parse_args()
    source=read_private(a.source);routes=read_private(a.routes);original=read_private(a.original_plan)
    if a.action=='prepare':
        plan=build(source,routes,original);seal(a.plan,plan)
        print(json.dumps({'cases':len(plan['requests']),'private_plan_sha256':digest(plan),
                          'gold_loaded':False,'status':'SOURCE_ONLY_FROZEN_RESEARCH'}))
    else:
        plan=read_private(a.plan)
        print(json.dumps(execute(source,routes,original,plan,a.reader,a.output),sort_keys=True))

if __name__=='__main__':main()
