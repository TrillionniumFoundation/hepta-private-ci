"""Real original 135M CPU execution with private fsynced request/answer journal.

Not official HuggingFace parity, independent host attestation, a strong reader
comparison, or authority to select/promote/execute effects.
"""
import argparse
import json
import os
from pathlib import Path
import time
from hashlib import sha256

import source_first as spec

# Research source-contract mode must not import Torch, regex or safetensors.
WEIGHTS='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'

SCHEMA=spec.SCHEMA+'.original-135m-physical'


def checked(public_path,owner_path,plan_path,annotation_path,request_path):
    public,owner,plan,ann,packet=map(spec.read,(public_path,owner_path,plan_path,annotation_path,request_path))
    if (spec.select(public,owner)!=plan.get('case_ids') or
        plan.get('plan_sha256')!=spec.digest({k:v for k,v in plan.items() if k!='plan_sha256'}) or
        plan.get('arms')!=list(spec.ARMS) or plan.get('model_weight_sha256')!=WEIGHTS or
        plan.get('max_tokens')!=spec.OUTPUT_CAP or plan.get('authority')!='DENY_ALL' or
        plan.get('no_gold_answer_to_model') is not True or plan.get('production_accepted') is not False or
        ann.get('packet_sha256')!=spec.digest({k:v for k,v in ann.items() if k!='packet_sha256'}) or
        ann.get('source_sha256')!=spec.digest(public) or ann.get('plan_sha256')!=plan['plan_sha256'] or
        ann.get('answer_fields_exposed') is not False or
        packet.get('schema')!=spec.SCHEMA+'.model-requests' or
        packet.get('requests_sha256')!=spec.digest(packet.get('requests')) or
        packet.get('plan_sha256')!=plan['plan_sha256'] or
        packet.get('public_sha256')!=spec.digest(public) or
        packet.get('annotation_packet_sha256')!=ann['packet_sha256'] or
        packet.get('publisher_answer_text_never_supplied') is not True or
        packet.get('production_accepted') is not False or packet.get('authority')!='DENY_ALL'):
        raise ValueError('original source/plan/annotation/model output authority mismatch')
    rows={f['id']:f for f in public}
    request_ids=set()
    for cid in plan['case_ids']:
        root=cid.split('/')[0];f=rows[root]
        q=next((q for q in f['questions'] if q['id']==cid),None)
        if q is None:raise ValueError('question missing')
        docs={d['id']:d for d in f['utterances']}
        ranking=spec.bm25(q['question'],f['utterances'])
        witness=ann['source_ids'][cid]
        if not 1<=len(witness)<=3 or any(s not in docs for s in witness):raise ValueError('wrong witness')
        for arm,evidence_ids in (('none',[]),('retrieved',ranking[:3]),
                                  ('annotated',witness),('lesion',witness[1:])):
            rid=cid+'|'+arm;request_ids.add(rid)
            want=spec.prompt(q['question'],evidence_ids,docs)
            entry=packet['requests'].get(rid)
            if (type(entry) is not dict or entry.get('prompt')!=want or
                entry.get('request_sha256')!=spec.sha_text(want) or
                entry.get('case_id')!=cid or entry.get('arm')!=arm or
                entry.get('source_ids')!=evidence_ids or
                entry.get('source_sha256')!=spec.digest(f) or
                entry.get('question_sha256')!=spec.sha_text(q['question'])):
                raise ValueError('original model input detached from public source')
    if request_ids!=set(packet['requests']):raise ValueError('missing/substituted physical Reader job')
    return plan,packet


def run(public_path,owner_path,plan_path,annotation_path,requests_path,reader_dir,output_path):
    plan,packet=checked(public_path,owner_path,plan_path,annotation_path,requests_path)
    # Verify original model tensors before allocating model or creating output.
    from original_135m import BPE, Llama135M, verify, file_sha, WEIGHTS, TOKENIZER, CONFIG
    model_root=verify(reader_dir)
    import torch
    torch.set_num_threads(2)
    tokenizer=BPE(model_root)
    unique={}; logical=[]
    for rid,row in sorted(packet['requests'].items()):
        ids=tokenizer.encode(row['prompt'])
        if not 1<=len(ids)<=1000 or len(ids)+plan['max_tokens']>1024:
            raise ValueError('Reader context overflow, no silent truncation')
        key=spec.sha_text(row['prompt'])
        if key not in unique:unique[key]=dict(token_ids=ids,representative_id=rid)
        if unique[key]['token_ids']!=ids:raise ValueError('same prompt, inconsistent tokenization')
        logical.append((rid,key))
    if len(logical)!=4*len(plan['case_ids']) or len(unique)<len(plan['case_ids']):
        raise ValueError('original Reader population invalid')
    physical=Llama135M(model_root)
    verify(model_root)
    output=Path(output_path); starts=Path(str(output)+'.starts.jsonl')
    if output.exists() or starts.exists() or output.is_symlink() or starts.is_symlink():
        raise FileExistsError('private original model output is create only')
    cpu0,wall0=time.process_time(),time.perf_counter()
    physical_outputs={}
    flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY
    if hasattr(os,'O_NOFOLLOW'):flags|=os.O_NOFOLLOW
    with os.fdopen(os.open(starts,flags,0o600),'w',encoding='utf-8') as writer:
        for prompt_sha,row in sorted(unique.items()):
            input_ids=row['token_ids']
            event=dict(representative_id=row['representative_id'],prompt_sha256=prompt_sha,
                       model_sha256=WEIGHTS,token_ids_sha256=spec.digest(input_ids),
                       input_tokens=len(input_ids),started_real_forward=True,production_authorized=False)
            writer.write(json.dumps(event,sort_keys=True)+'\n');writer.flush();os.fsync(writer.fileno())
            c0,w0=time.process_time(),time.perf_counter()
            generated=physical.generate(input_ids,max_tokens=plan['max_tokens'])
            answer=tokenizer.decode(generated)
            physical_outputs[prompt_sha]=dict(representative_id=row['representative_id'],
                output_ids=generated,original_answer=answer,answer_sha256=spec.sha_text(answer),
                token_ids_sha256=spec.digest(input_ids),input_tokens=len(input_ids),
                output_tokens=len(generated),cpu_ms=round(1000*(time.process_time()-c0)),
                wall_ms=round(1000*(time.perf_counter()-w0)))
    verify(model_root)
    result=dict(schema=SCHEMA,plan_sha256=plan['plan_sha256'],requests_sha256=packet['requests_sha256'],
        model_sha256=WEIGHTS,tokenizer_sha256=TOKENIZER,model_config_sha256=CONFIG,
        runtime_sha256=file_sha(__import__('original_135m').__file__),
        original_archive_sha256=spec.ARCHIVE_SHA,journal_sha256=file_sha(starts),
        physical_outputs=physical_outputs,outputs_sha256=spec.digest(physical_outputs),
        physical_unique_requests=len(physical_outputs),logical_arm_requests=len(logical),
        model_forward_calls=physical.calls,
        model_cpu_ms=round(1000*(time.process_time()-cpu0)),
        model_wall_ms=round(1000*(time.perf_counter()-wall0)),
        source_from_original_archive=True,reader_original_weights_executed=True,
        original_torch_fp32_research_path=True,official_hf_parity_verified=False,
        stronger_reference_reader_executed=False,independent_host_attestation_verified=False,
        independently_adjudicated_answer_quality=False,publisher_witness_human_sufficiency_verified=False,
        publication_raw_answers_forbidden=True,production_authorized=False,
        decision='HOLD_NO_GO')
    spec.write_once(output,result)
    return {k:result[k] for k in ('schema','plan_sha256','physical_unique_requests',
        'logical_arm_requests','model_forward_calls','model_cpu_ms','model_wall_ms','decision')}


def main():
    ap=argparse.ArgumentParser()
    for k in ('public','owner','plan','annotation','requests','reader-dir','private-output'):
        ap.add_argument('--'+k,required=True)
    a=ap.parse_args()
    receipt=run(a.public,a.owner,a.plan,a.annotation,a.requests,a.reader_dir,a.private_output)
    print(json.dumps(receipt,sort_keys=True))

if __name__=='__main__':main()
