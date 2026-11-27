"""V18 source-first prompt-serialization lesion for original frozen 135M Reader.

No task label, answer or human adjudication enters the proposer or model process.
The distinct frozen variants have unequal token budgets, thus outcomes are
mechanistic descriptive contrasts, never matched-cost learning or NDU gains.
"""
import argparse
import json
import os
from pathlib import Path
import time

import source_first as v17
import physical as parent

SCHEMA = 'hepta.v18.original-reader-prompt-serialization.shadow.v1'
ARMS = ('plain_none', 'plain_annotated', 'role_annotated')
WEIGHT_SHA = parent.WEIGHTS
PLAN_FIELDS = frozenset(('schema','parent_plan_sha256','parent_requests_sha256',
    'public_sha256','owner_sha256','annotation_packet_sha256','original_corpus_sha256',
    'model_sha256','max_output_tokens','original_roots','cases','arms','proposed',
    'request_sha256','answer_text_never_read','original_publisher_answer_fields_not_used',
    'source_time_prospective','retrospective_historical_cohort',
    'human_witness_sufficiency_unverified','model_selected','nd_u_utility_not_evaluated',
    'production_authorized','authority','decision','proposal_sha256'))


def evidence(ids, docs):
    # Same 240-character original source excerpt as V17; no answer-aware editing.
    if not ids:
        return '(no evidence provided)'
    return '\n'.join('[E'+str(j)+'] '+source_id+' '+docs[source_id]['speaker']+': '
                     +docs[source_id]['text'][:240]
                     for j,source_id in enumerate(ids,1))


def render(question, ids, docs, arm):
    if arm not in ARMS:
        raise ValueError('unknown frozen prompt arm')
    content=evidence(ids,docs)
    if any(s in question or s in content for s in ('<|im_start|>','<|im_end|>')):
        raise ValueError('role injection in source')
    if arm.startswith('plain_'):
        return ('You are given a question and evidence. Answer using only the evidence. '
                'If the evidence is insufficient, answer unknown.\nEvidence:\n'+content+
                '\nQuestion: '+question+'\nAnswer:')
    return ('<|im_start|>system\nGive only the shortest answer supported by evidence. '
            'If unknown, respond unknown. Cite an evidence marker only when available.\n'
            '<|im_end|>\n<|im_start|>user\nEvidence:\n'+content+
            '\nQuestion: '+question+'\n<|im_end|>\n<|im_start|>assistant\n')


def checked_origins(public, owner, plan, annotation, previous):
    frozen, parent_requests=parent.checked(public,owner,plan,annotation,previous)
    if (frozen['max_tokens']!=24 or frozen['n_cases']!=30 or
        frozen['source_roots']!=list(v17.ROOTS) or frozen['arms']!=list(v17.ARMS) or
        frozen['case_selection']!='sha256_lowest_three_per_original_root_NO_answer_filter' or
        frozen['no_gold_answer_to_model'] is not True or
        frozen['publisher_witness_not_human_certified_sufficient'] is not True or
        frozen['production_accepted'] is not False):
        raise ValueError('source-first parent changed')
    return frozen,parent_requests


def build(public_path,owner_path,plan_path,annotation_path,previous_requests_path,out):
    frozen,previous=checked_origins(public_path,owner_path,plan_path,annotation_path,previous_requests_path)
    public,owner,annot=v17.read(public_path),v17.read(owner_path),v17.read(annotation_path)
    groups={g['id']:g for g in public}; proposed={}
    for cid in frozen['case_ids']:
        family=groups[cid.split('/')[0]]
        docs={x['id']:x for x in family['utterances']}
        question=next((q['question'] for q in family['questions'] if q['id']==cid),None)
        if question is None:raise ValueError('question not present')
        support=annot['source_ids'][cid]
        prior=previous['requests'][cid+'|annotated']
        if prior['source_ids']!=support or prior['prompt']!=v17.prompt(question,support,docs):
            raise ValueError('original V17 annotated input changed')
        for arm in ARMS:
            ids=[] if arm=='plain_none' else support
            prompt=render(question,ids,docs,arm)
            proposed[cid+'|'+arm]=dict(case_id=cid,arm=arm,
                source_ids=list(ids),question_sha256=v17.sha_text(question),
                source_sha256=v17.digest(family),prompt_sha256=v17.sha_text(prompt),prompt=prompt)
    if len(proposed)!=90:raise ValueError('incomplete V18 study')
    p=dict(schema=SCHEMA+'.proposal',parent_plan_sha256=frozen['plan_sha256'],
           parent_requests_sha256=previous['requests_sha256'],
           public_sha256=v17.digest(public),owner_sha256=v17.digest(owner),
           annotation_packet_sha256=annot['packet_sha256'],
           original_corpus_sha256=v17.CORPUS_SHA,
           model_sha256=WEIGHT_SHA,max_output_tokens=24,
           original_roots=list(v17.ROOTS),cases=list(frozen['case_ids']),
           arms=list(ARMS),proposed=proposed,request_sha256=v17.digest(proposed),
           answer_text_never_read=True,original_publisher_answer_fields_not_used=True,
           source_time_prospective=False,retrospective_historical_cohort=True,
           human_witness_sufficiency_unverified=True,model_selected=False,
           nd_u_utility_not_evaluated=True,production_authorized=False,
           authority='DENY_ALL',decision='HOLD_NO_GO')
    p['proposal_sha256']=v17.digest(p)
    v17.write_once(out,p)
    return p


def validate(public_path,owner_path,plan_path,annotation_path,previous_requests_path,proposal_path):
    original=v17.read(proposal_path)
    # Reconstruct all original task/evidence identities without ever using gold.
    # No temporary fixture files are needed for the actual model path.
    frozen,prior=checked_origins(public_path,owner_path,plan_path,annotation_path,previous_requests_path)
    public,owner,ann=map(v17.read,(public_path,owner_path,annotation_path))
    if (type(original) is not dict or set(original)!=PLAN_FIELDS or
        original.get('schema')!=SCHEMA+'.proposal' or
        original.get('proposal_sha256')!=v17.digest({k:v for k,v in original.items() if k!='proposal_sha256'}) or
        original.get('parent_plan_sha256')!=frozen['plan_sha256'] or
        original.get('parent_requests_sha256')!=prior['requests_sha256'] or
        original.get('public_sha256')!=v17.digest(public) or
        original.get('owner_sha256')!=v17.digest(owner) or
        original.get('annotation_packet_sha256')!=ann['packet_sha256'] or
        original.get('original_corpus_sha256')!=v17.CORPUS_SHA or
        original.get('model_sha256')!=WEIGHT_SHA or original.get('arms')!=list(ARMS) or
        original.get('cases')!=frozen['case_ids'] or
        original.get('original_roots')!=list(v17.ROOTS) or
        original.get('request_sha256')!=v17.digest(original.get('proposed')) or
        original.get('answer_text_never_read') is not True or
        original.get('original_publisher_answer_fields_not_used') is not True or
        original.get('nd_u_utility_not_evaluated') is not True or
        original.get('source_time_prospective') is not False or
        original.get('retrospective_historical_cohort') is not True or
        original.get('human_witness_sufficiency_unverified') is not True or
        original.get('model_selected') is not False or
        original.get('production_authorized') is not False or
        original.get('decision')!='HOLD_NO_GO' or
        original.get('authority')!='DENY_ALL' or
        original.get('max_output_tokens')!=24):
        raise ValueError('unbound original V18 proposal or elevated authority')
    seen=set();groups={g['id']:g for g in public}
    for cid in frozen['case_ids']:
        f=groups[cid.split('/')[0]]
        q=next(z['question'] for z in f['questions'] if z['id']==cid)
        docs={z['id']:z for z in f['utterances']}
        witness=ann['source_ids'][cid]
        if witness!=prior['requests'][cid+'|annotated']['source_ids']:
            raise ValueError('mutated publisher annotation')
        for arm in ARMS:
            k=cid+'|'+arm;seen.add(k)
            s=[] if arm=='plain_none' else witness
            prompt=render(q,s,docs,arm)
            e=original['proposed'].get(k)
            if (type(e) is not dict or set(e)!=set(('case_id','arm','source_ids',
                'question_sha256','source_sha256','prompt_sha256','prompt')) or
                e['case_id']!=cid or e['arm']!=arm or e['source_ids']!=s or
                e['question_sha256']!=v17.sha_text(q) or
                e['source_sha256']!=v17.digest(f) or
                e['prompt_sha256']!=v17.sha_text(prompt) or e['prompt']!=prompt):
                raise ValueError('prompt/input/source drift in physical original trial')
    if seen!=set(original['proposed']) or len(seen)!=90:
        raise ValueError('missing or foreign original prompts')
    return original


def run(public,owner,plan,annotation,previous,proposal,model_dir,out):
    p=validate(public,owner,plan,annotation,previous,proposal)
    # Heavy imports only after all source-only checks passed.
    from original_135m import verify,BPE,Llama135M,file_sha,TOKENIZER,CONFIG
    import torch
    modelroot=verify(model_dir)
    torch.set_num_threads(2)
    tokenizer=BPE(modelroot)
    unique={}
    for rid,entry in sorted(p['proposed'].items()):
        t=tokenizer.encode(entry['prompt'])
        if not 1<=len(t)<=1000 or len(t)+24>1024:
            raise ValueError('original Reader exceeds the bounded context')
        key=entry['prompt_sha256']
        if key not in unique:unique[key]=dict(representative_id=rid,input_ids=t)
        if unique[key]['input_ids']!=t:raise ValueError('same SHA but different token ids')
    if len(unique)!=90:raise ValueError('unexpected prompt dedup cannot silently alter census')
    output=Path(out); journal=Path(str(output)+'.starts.jsonl')
    if output.exists() or output.is_symlink() or journal.exists() or journal.is_symlink():
        raise FileExistsError('private model output must be create only')
    model=Llama135M(modelroot)
    verify(modelroot)
    started=time.process_time();wall_started=time.perf_counter()
    responses={}
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,'O_NOFOLLOW'):flags|=os.O_NOFOLLOW
    with os.fdopen(os.open(journal,flags,0o600),'w') as f:
        for key,req in sorted(unique.items()):
            attempt=dict(prompt_sha256=key,representative_id=req['representative_id'],
                         token_ids_sha256=v17.digest(req['input_ids']),
                         actual_start=True,model_sha256=WEIGHT_SHA,authority='DENY_ALL')
            f.write(json.dumps(attempt,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
            t0=time.process_time();w0=time.perf_counter()
            generated=model.generate(req['input_ids'],max_tokens=24)
            answer=tokenizer.decode(generated)
            responses[key]=dict(representative_id=req['representative_id'],
                generated_token_ids=generated,answer=answer,answer_sha256=v17.sha_text(answer),
                input_sha256=v17.digest(req['input_ids']),input_tokens=len(req['input_ids']),
                output_tokens=len(generated),cpu_ms=round(1000*(time.process_time()-t0)),
                wall_ms=round(1000*(time.perf_counter()-w0)))
    verify(modelroot)
    data=dict(schema=SCHEMA+'.real-135m-private-output',
        proposal_sha256=p['proposal_sha256'],model_sha256=WEIGHT_SHA,
        tokenizer_sha256=TOKENIZER,config_sha256=CONFIG,
        model_source_digest=file_sha(__import__('original_135m').__file__),
        responses=responses,responses_sha256=v17.digest(responses),
        journal_sha256=file_sha(journal),physical_unique_requests=len(responses),
        model_forward_calls=model.calls,
        cpu_ms=round(1000*(time.process_time()-started)),
        wall_ms=round(1000*(time.perf_counter()-wall_started)),
        real_original_model_forward=True,model_not_HF_operator_parity=True,
        real_reference_qwen_forwards=0,answer_quality_independently_reviewed=False,
        human_sufficiency_not_certified=True,production_authorized=False,
        decision='HOLD_NO_GO',authority='DENY_ALL')
    v17.write_once(output,data)
    return {k:data[k] for k in ('schema','physical_unique_requests','model_forward_calls','cpu_ms','wall_ms','decision')}


def cli():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='cmd',required=True)
    for action in ('plan','run'):
        a=sub.add_parser(action)
        for k in ('public','owner','plan','annotation','previous','out'):
            a.add_argument('--'+k,required=True)
        if action=='run':
            for k in ('proposal','model-dir'):a.add_argument('--'+k,required=True)
    args=ap.parse_args()
    if args.cmd=='plan':
        p=build(args.public,args.owner,args.plan,args.annotation,args.previous,args.out)
        print(json.dumps({k:p[k] for k in ('schema','proposal_sha256','request_sha256','decision')}))
    else:
        print(json.dumps(run(args.public,args.owner,args.plan,args.annotation,args.previous,
                             args.proposal,args.model_dir,args.out)))

if __name__=='__main__':cli()
