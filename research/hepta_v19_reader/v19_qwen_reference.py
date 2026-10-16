"""V19: native-Qwen stronger-Reader original LoCoMo panel; research ONLY.

Uses the exact V17 source-first 30 questions and *same original evidence bytes*.
Model-specific native Qwen ChatML tokenization is intentional, not token-matched.
No publisher answer string is accessible to build/execute; no fallback model.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

import source_first as v17
import physical as base

SCHEMA = 'hepta.v19.original-locomo-native-qwen3-reference.shadow.v1'
REPO = 'Qwen/Qwen3-0.6B'
REVISION = '16706fc57485378d4ffaf54139b29ccc66ae08fa'
ARMS = tuple(v17.ARMS)
OUT_CAP = 24
INPUT_CAP = 2048
SYSTEM = ('Answer concisely from provided evidence only. If not supported, say unknown. '
          'Cite the evidence [E1], [E2], etc.')
PLAN_KEYS = {'schema', 'v17_plan_sha256', 'v17_requests_sha256', 'public_sha256',
             'owner_sha256','annotation_packet_sha256','model_repo','model_revision',
             'source_roots','cases','arms','output_cap','max_input_tokens','entries',
             'entry_sha256','publisher_answer_labels_not_exposed',
             'model_specific_tokenization_not_matched','source_time_prospective',
             'independent_human_sufficiency','authority','production_authorized',
             'decision','plan_sha256'}


def message(question, ids, docs):
    # Exactly the same utterance body as the frozen V17 original Reader.
    if any(tag in question or any(tag in docs[i]['text'] for i in ids)
           for tag in ('<|im_start|>', '<|im_end|>', '<|fim_prefix|>')):
        raise ValueError('untrusted role delimiter in source')
    body = '\n'.join('[E'+str(n)+'] '+src+' '+docs[src]['speaker']+': '
                     +docs[src]['text'][:240] for n,src in enumerate(ids,1))
    if not body:body='(no evidence provided)'
    return [{'role':'system','content':SYSTEM},
            {'role':'user','content':'Question: '+question+'\nEvidence:\n'+body}]


def derive(public_path,owner_path,plan_path,annotation_path,requests_path):
    frozen, original=base.checked(public_path,owner_path,plan_path,annotation_path,requests_path)
    public,owner,ann=map(v17.read,(public_path,owner_path,annotation_path))
    if (frozen['n_cases']!=30 or frozen['case_ids']!=sorted(frozen['case_ids']) or
        frozen['case_selection']!='sha256_lowest_three_per_original_root_NO_answer_filter' or
        frozen['arms']!=list(ARMS) or frozen['source_roots']!=list(v17.ROOTS) or
        frozen['source_time_prospective'] is not False or
        frozen['no_gold_answer_to_model'] is not True or
        frozen['publisher_witness_not_human_certified_sufficient'] is not True or
        original['publisher_answer_text_never_supplied'] is not True):
        raise ValueError('wrong frozen original question/authority cohort')
    contexts={f['id']:f for f in public}
    entries={}
    for cid in frozen['case_ids']:
        fam=contexts[cid.split('/')[0]]
        question=next(q['question'] for q in fam['questions'] if q['id']==cid)
        docs={u['id']:u for u in fam['utterances']}
        for arm in ARMS:
            ident=cid+'|'+arm
            frozen_request=original['requests'][ident]
            ids=frozen_request['source_ids']
            msgs=message(question,ids,docs)
            if v17.prompt(question,ids,docs)!=frozen_request['prompt']:
                raise ValueError('not the original V17 source-evidence bytes')
            entries[ident]={
                'case_id':cid,'arm':arm,'source_ids':ids,
                'source_sha256':frozen_request['source_sha256'],
                'question_sha256':v17.sha_text(question),
                'v17_request_sha256':frozen_request['request_sha256'],
                'message_sha256':v17.digest(msgs),
                'messages':msgs,
            }
    if len(entries)!=120 or set(entries)!={cid+'|'+arm for cid in frozen['case_ids'] for arm in ARMS}:
        raise ValueError('not a complete original 30x4 panel')
    item={
        'schema':SCHEMA+'.source-plan',
        'v17_plan_sha256':frozen['plan_sha256'],
        'v17_requests_sha256':original['requests_sha256'],
        'public_sha256':v17.digest(public),
        'owner_sha256':v17.digest(owner),
        'annotation_packet_sha256':ann['packet_sha256'],
        'model_repo':REPO,'model_revision':REVISION,
        'source_roots':list(v17.ROOTS),'cases':list(frozen['case_ids']),
        'arms':list(ARMS),'output_cap':OUT_CAP,'max_input_tokens':INPUT_CAP,
        'entries':entries,'entry_sha256':v17.digest(entries),
        'publisher_answer_labels_not_exposed':True,
        'model_specific_tokenization_not_matched':True,
        'source_time_prospective':False,'independent_human_sufficiency':False,
        'authority':'DENY_ALL','production_authorized':False,'decision':'HOLD_NO_GO',
    }
    item['plan_sha256']=v17.digest(item)
    return item


def validate(source_paths, plan_path):
    p=v17.read(plan_path)
    if type(p) is not dict or set(p)!=PLAN_KEYS:
        raise ValueError('unregistered original reference plan keys')
    expected=derive(*source_paths)
    if p!=expected or p.get('plan_sha256')!=v17.digest({k:v for k,v in p.items() if k!='plan_sha256'}):
        raise ValueError('model prompt/answer/source modified after source-first seal')
    return p


def build(source_paths, output):
    p=derive(*source_paths)
    v17.write_once(output,p)
    return {'schema':p['schema'],'plan_sha256':p['plan_sha256'],
            'cases':30,'logical_requests':120,'authority':'DENY_ALL'}


def run(source_paths, plan_path, model_dir, model_spec_path, output_path):
    p=validate(source_paths,plan_path)
    from v19_qwen_material import verify_snapshot
    model_spec=v17.read(model_spec_path)
    material_sha=verify_snapshot(model_dir,model_spec)
    # No synthetic model, fake weights or unpinned tokenizer runtime here.
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    torch.set_num_threads(2)
    tokenizer=AutoTokenizer.from_pretrained(model_dir,local_files_only=True,
                                             trust_remote_code=False,use_fast=True)
    model=AutoModelForCausalLM.from_pretrained(model_dir,local_files_only=True,
                                             trust_remote_code=False,
                                             use_safetensors=True,dtype=torch.float32).eval()
    if verify_snapshot(model_dir,model_spec)!=material_sha:
        raise ValueError('reference model changed while loading')
    tokenized={}
    logical={}
    for rid,entry in sorted(p['entries'].items()):
        ids=tokenizer.apply_chat_template(entry['messages'],tokenize=True,
                                           add_generation_prompt=True,enable_thinking=False)
        if (type(ids) is not list or not 1<=len(ids)<=INPUT_CAP or
            any(type(i) is not int or i<0 for i in ids)):
            raise ValueError('native reference tokenizer invalid or clipped')
        key=v17.digest(ids)
        if key in tokenized and tokenized[key]['input_ids']!=ids:
            raise ValueError('same logical token digest changed')
        tokenized.setdefault(key,{'input_ids':ids,'ids':[]})['ids'].append(rid)
        logical[rid]=key
    if len(logical)!=120 or len(tokenized)!=96:
        raise ValueError('physical reference request census differs from original')
    out=Path(output_path);journal=Path(str(out)+'.starts.jsonl')
    if out.exists() or out.is_symlink() or journal.exists() or journal.is_symlink():
        raise FileExistsError('original reference output must be private and create-only')
    hook_counts={'forward':0}
    def count_forward(_model,_inputs,_output):
        hook_counts['forward']+=1
    hook=model.register_forward_hook(count_forward)
    results={};cpu0=time.process_time();wall0=time.perf_counter()
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,'O_NOFOLLOW'):flags|=os.O_NOFOLLOW
    try:
        with os.fdopen(os.open(journal,flags,0o600),'w',encoding='utf8') as f,torch.inference_mode():
            for key,req in sorted(tokenized.items()):
                event=dict(token_ids_sha256=key,model_spec_sha256=material_sha,
                           plan_sha256=p['plan_sha256'],representative_id=req['ids'][0],
                           logical_ids=req['ids'],input_tokens=len(req['input_ids']),
                           physical_model_generation_started=True,authority='DENY_ALL')
                f.write(json.dumps(event,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
                c0,w0=time.process_time(),time.perf_counter()
                before=hook_counts['forward']
                original=model.generate(input_ids=torch.tensor([req['input_ids']],dtype=torch.long),
                                        do_sample=False,max_new_tokens=OUT_CAP,
                                        eos_token_id=tokenizer.eos_token_id,
                                        pad_token_id=tokenizer.eos_token_id)
                complete=original[0].tolist()
                if complete[:len(req['input_ids'])]!=req['input_ids']:
                    raise ValueError('physical token prefix changed')
                generation=complete[len(req['input_ids']):]
                if not 1<=len(generation)<=OUT_CAP:
                    raise ValueError('reference model output absent or unbounded')
                text=tokenizer.decode(generation,skip_special_tokens=True)
                results[key]=dict(representative_id=req['ids'][0],logical_ids=req['ids'],
                                  generated_token_ids=generation,answer=text,
                                  answer_sha256=v17.sha_text(text),
                                  input_sha256=key,input_tokens=len(req['input_ids']),
                                  output_tokens=len(generation),
                                  observed_root_model_forwards=hook_counts['forward']-before,
                                  cpu_ms=max(0,round(1000*(time.process_time()-c0))),
                                  wall_ms=max(0,round(1000*(time.perf_counter()-w0))))
        if verify_snapshot(model_dir,model_spec)!=material_sha:
            raise ValueError('model drift after completed generation')
    finally:
        hook.remove()
    result=dict(schema=SCHEMA+'.physical-private',plan_sha256=p['plan_sha256'],
        source_roots=list(v17.ROOTS),model_repo=REPO,model_revision=REVISION,
        model_spec_sha256=material_sha,model_weights_sha256=model_spec['files_sha256']['model.safetensors'],
        requests_by_id=logical,requests_by_id_sha256=v17.digest(logical),
        physical_outputs=results,physical_outputs_sha256=v17.digest(results),
        original_archive_sha256=v17.ARCHIVE_SHA,
        journal_sha256=sha256(journal.read_bytes()).hexdigest(),
        actual_unique_qwen_requests=len(results),logical_arm_requests=len(logical),
        measured_root_forward_calls=hook_counts['forward'],
        wall_ms=max(0,round(1000*(time.perf_counter()-wall0))),
        cpu_ms=max(0,round(1000*(time.process_time()-cpu0))),
        original_pretrained_qwen3_executed=True,
        physical_model_host_independently_signed=False,
        current_135m_model_executed_by_this_runner=False,
        task_semantic_correctness_independently_verified=False,
        publisher_witness_sufficiency_human_certified=False,
        model_token_budget_matched_to_135m=False,
        ndu_fbsde_solves=0,authority='DENY_ALL',production_authorized=False,
        decision='HOLD_NO_GO')
    v17.write_once(out,result)
    return {k:result[k] for k in ('schema','actual_unique_qwen_requests',
        'logical_arm_requests','measured_root_forward_calls','cpu_ms','wall_ms','decision')}


def cli():
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=('plan','run'))
    for field in ('public','owner','v17-plan','annotation','v17-requests','reference-plan',
                  'model-dir','model-spec','output'):
        ap.add_argument('--'+field)
    a=ap.parse_args()
    src=tuple(getattr(a,k.replace('-','_')) for k in ('public','owner','v17-plan','annotation','v17-requests'))
    if any(not item for item in src) or not a.output:
        ap.error('source-first owner and create-only output required')
    if a.action=='plan':result=build(src,a.output)
    else:
        if not all((a.reference_plan,a.model_dir,a.model_spec)):
            ap.error('frozen plan and physical model snapshot required')
        result=run(src,a.reference_plan,a.model_dir,a.model_spec,a.output)
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':cli()
