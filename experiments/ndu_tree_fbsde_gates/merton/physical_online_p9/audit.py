"""Separated postseal P9 publisher and original-token escrow reviewer.

Replays every booked model call, tokenizer quote, start/done journal event,
reserve/refund, TRAIN-only policy, independent held publisher truth and result.
No production/selection authority, no neural FBSDE or hardware attestation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from collections import Counter
from fractions import Fraction as Q
from pathlib import Path

from portfolio import (SCHEMA,POLICIES,MAX_CHECKS,TOKEN_ENDOWMENT,CHECK_CAP,TARIFF,
                       Controller,TokenEscrow)
from source import SOURCE_SCHEMA
from runner import (source_packets,digest,read,write_new,rotate,P8,ORIGINAL_RUNTIME)
from parent import load_p8

P8REVIEW=load_p8('review')


def insist(ok,reason):
    if not ok:raise ValueError(reason)


class IndependentFrozenTokenizerQuote:
    """Re-read original *tokenizer bytes* without the model's generated outputs."""
    def __init__(self):
        from huggingface_hub import snapshot_download
        from transformers import AutoTokenizer
        root=Path(snapshot_download(repo_id=P8REVIEW.MODEL_REPO,revision=P8REVIEW.MODEL_REV,
                                     allow_patterns=['tokenizer.json','tokenizer_config.json',
                                                     'config.json','special_tokens_map.json']))
        tokenizer=root/'tokenizer.json'
        insist(tokenizer.is_file() and hashlib.sha256(tokenizer.read_bytes()).hexdigest()==P8REVIEW.TOKENIZER,
               'original tokenizer SHA256 drift')
        self.tok=AutoTokenizer.from_pretrained(root,local_files_only=True,use_fast=True,trust_remote_code=False)
        insist(self.tok.convert_tokens_to_ids('</think>')==151668,'original thinking marker mismatch')

    def __call__(self,text,action,previous):
        insist(action in ('check_plain','check_think'),'unsupported tokenizer price action')
        prompt=P8.make_prompt(text,action,previous)
        ids=self.tok.apply_chat_template(prompt,tokenize=True,add_generation_prompt=True,
                  enable_thinking=action=='check_think')
        insist(type(ids) is list and 1<=len(ids)<=1024 and all(type(k) is int and k>=0 for k in ids),
               'invalid original tokenizer quote')
        return len(ids)


def audit(train,held,gold,plan,completed,journal_path:Path,plan_path:Path,
          quote_fn=None,require_physical=True):
    training,public=source_packets(train,held)
    insist(type(gold) is dict and set(gold)=={'schema','source','rows'} and
           gold['schema']==SOURCE_SCHEMA+'.held-private-labels' and gold['source']==train['source'],
           'publisher original label provenance')
    gm={}
    for row in gold['rows']:
        insist(type(row) is dict and set(row)=={'task_id','label','text_sha256'} and
               type(row['label']) is int and row['label'] in range(4) and row['task_id'] not in gm,
               'invalid/duplicate publisher labels')
        gm[row['task_id']]=row
    insist(len(gm)==16 and set(gm)=={c['task_id'] for c in public} and
           all(gm[c['task_id']]['text_sha256']==c['text_sha256'] for c in public),
           'mismatched original publisher gold')
    strata=Counter((gm[c['task_id']]['label'],c['bucket'],int(c['task_id'][-5:])%2) for c in public)
    insist(len(strata)==16 and set(strata.values())=={1},'held publisher class/length/parity identity')
    insist(type(plan) is dict and plan.get('schema')==SCHEMA+'.frozen-plan' and
           plan.get('train_source_digest')==digest(train) and plan.get('held_public_digest')==digest(held) and
           plan.get('held_task_ids')==[r['task_id'] for r in public] and
           plan.get('buckets')==[r['bucket'] for r in public] and
           plan.get('policies')==list(POLICIES) and plan.get('authority')=='DENY_ALL' and
           plan.get('source_owner_held_labels_absent') is True and
           plan.get('incremental_token_endowment_per_policy')==TOKEN_ENDOWMENT and
           plan.get('max_checker_calls_per_policy')==MAX_CHECKS and
           plan.get('max_checker_generated_tokens')==CHECK_CAP and
           plan.get('train_original_calls')==96,
           'frozen TRAIN and legal budget contract mismatch')
    raw_plan=plan_path.read_bytes()
    insist(raw_plan==P8.canonical(plan)+b'\n','frozen plan bytes changed')
    insist(type(completed) is dict and completed.get('schema')==SCHEMA+'.completed-original' and
           completed.get('frozen_plan_sha256')==hashlib.sha256(raw_plan).hexdigest() and
           completed.get('authority')=='DENY_ALL', 'original completed plan binding')
    identity=plan['original_model']
    insist(completed.get('model')==identity,'model changed after TRAIN freeze')
    if require_physical:
        insist(completed.get('source_kind')=='original_physical' and
               type(identity) is dict and identity.get('repo')==P8REVIEW.MODEL_REPO and
               identity.get('revision')==P8REVIEW.MODEL_REV and
               identity.get('weights_sha256')==P8REVIEW.WEIGHTS and
               identity.get('tokenizer_sha256')==P8REVIEW.TOKENIZER and
               identity.get('actual_pretrained_model_loaded') is True and
               identity.get('runtime')==ORIGINAL_RUNTIME,
               'forged original pretrained model identity')
        insist(quote_fn is not None,'no separate original tokenizer quote evaluator')
    else:
        insist(completed.get('source_kind')=='synthetic_fixture','fixture mislabeled physical')
        insist(quote_fn is not None,'test must supply independent bounded quote function')
    insist(isinstance(completed.get('train_calls'),list) and len(completed['train_calls'])==96 and
           isinstance(completed.get('held_calls'),list) and isinstance(completed.get('policy_decisions'),list) and
           len(completed['policy_decisions'])==16*len(POLICIES),
           'complete physical train and decision census')
    events=[]
    train_map={r['task_id']:r for r in training}
    ptr=0
    train_paid=0
    for row in training:
        previous=None
        for action in ('direct','check_plain','check_think'):
            c=completed['train_calls'][ptr];ptr+=1
            P8REVIEW.validate_original_call(c,row,'train','train',action,previous,require_physical)
            previous=c['result']['answer'] if action=='direct' else previous
            begin={'phase':'train','task_id':row['task_id'],'policy':'train','action':action,
                   'prompt_sha256':c['prompt_sha256']}
            events.extend([('train',row['task_id'],'train',action,'start',digest(begin)),
                           ('train',row['task_id'],'train',action,'done',digest(c))])
            train_paid+=c['result']['input_tokens']+c['result']['output_tokens']
    frozen_train=__import__('policy').train_profile(training,completed['train_calls'])
    insist(plan.get('train_profile')==frozen_train,'TRAIN-only original fitted model changed')
    plan_sha=hashlib.sha256(raw_plan).hexdigest()
    events.append(('plan','frozen','system','seal','sealed',plan_sha))
    controllers={name:Controller(frozen_train,tuple(r['bucket'] for r in public),name) for name in POLICIES}
    wallets={name:TokenEscrow() for name in POLICIES}
    outcomes={name:[] for name in POLICIES}
    cursor=0;decisions=iter(completed['policy_decisions'])
    for index,row in enumerate(public):
        for name in rotate(POLICIES,index):
            insist(cursor<len(completed['held_calls']),'missing paid direct call')
            base=completed['held_calls'][cursor];cursor+=1
            P8REVIEW.validate_original_call(base,row,'held',name,'direct',None,require_physical)
            begin={'phase':'held','task_id':row['task_id'],'policy':name,'action':'direct',
                   'prompt_sha256':base['prompt_sha256']}
            events.extend([('held',row['task_id'],name,'direct','start',digest(begin)),
                           ('held',row['task_id'],name,'direct','done',digest(base))])
            d=next(decisions)
            insist(type(d) is dict and set(d)=={'index','case_id','policy','choice','base_answer_sha256',
                                                'input_quotes','tokens_before','calls_before'} and
                   (d['index'],d['case_id'],d['policy'])==(index,row['task_id'],name) and
                   d['base_answer_sha256']==hashlib.sha256(base['result']['answer'].encode()).hexdigest(),
                   'budget decision origin or provisional answer substitution')
            quotes=d['input_quotes']
            insist(type(quotes) is dict and set(quotes)=={'check_plain','check_think'},'missing both option prices')
            for action,q in quotes.items():
                insist(type(q) is int and q==quote_fn(row['text'],action,base['result']['answer']),
                       'nonphysical/artificial tokenizer option quote')
            w=wallets[name]
            insist(d['tokens_before']==w.available and d['calls_before']==w.remaining_calls,
                   'token/call ledger state changed prior to decision')
            choice=controllers[name].choose(index,w,row['bucket'],base['result']['predicted_class'],quotes)
            insist(d['choice']==choice,'reselected held policy with illicit information')
            events.append(('held',row['task_id'],name,choice,'decision',digest(d)))
            final=base
            if choice!='stop':
                identity_key=f'held/{row["task_id"]}/{name}/{choice}'
                reservation=w.reserve(identity_key,quotes[choice],CHECK_CAP)
                events.append(('held',row['task_id'],name,choice,'reserve',digest(reservation)))
                insist(cursor<len(completed['held_calls']),'missing physically paid checker')
                checker=completed['held_calls'][cursor];cursor+=1
                P8REVIEW.validate_original_call(checker,row,'held',name,choice,base['result']['answer'],require_physical)
                begin={'phase':'held','task_id':row['task_id'],'policy':name,'action':choice,
                       'prompt_sha256':checker['prompt_sha256']}
                events.extend([('held',row['task_id'],name,choice,'start',digest(begin)),
                               ('held',row['task_id'],name,choice,'done',digest(checker))])
                settlement=w.settle(identity_key,checker['result']['input_tokens'],checker['result']['output_tokens'])
                events.append(('held',row['task_id'],name,choice,'settle',digest(settlement)))
                final=checker
            total_paid=(base['result']['input_tokens']+base['result']['output_tokens']+
                        (final['result']['input_tokens']+final['result']['output_tokens'] if final is not base else 0))
            outcomes[name].append({'correct':int(final['result']['predicted_class']==gm[row['task_id']]['label']),
                'direct_correct':int(base['result']['predicted_class']==gm[row['task_id']]['label']),
                'choice':choice,'paid_tokens':total_paid,
                'cpu':base['measured_cpu_seconds']+(final['measured_cpu_seconds'] if final is not base else 0),
                'wall':base['measured_wall_seconds']+(final['measured_wall_seconds'] if final is not base else 0),
                'unfinished_thought':choice=='check_think' and not final['result']['thinking_complete']})
    insist(cursor==len(completed['held_calls']),'original model calls left outside cost accounting')
    insist(completed.get('wallets')=={n:w.wire() for n,w in wallets.items()},
           'actual hard token escrow not conserved')
    insist(completed.get('journal_events')==len(events),'original journal event count drift')
    P8REVIEW.journal_validate(journal_path,events,raw_plan)
    insist([v['choice'] for v in outcomes['ndu_shadow']]==
           [v['choice'] for v in outcomes['ordinary_same_profile']],
           'same-objective ordinary controller differs from NDU')
    summary={}
    for name,items in outcomes.items():
        correct=sum(r['correct'] for r in items);tokens=sum(r['paid_tokens'] for r in items)
        summary[name]={'correct':correct,'total':len(items),'full_serving_tokens':tokens,
            'checker_calls':sum(r['choice']!='stop' for r in items),
            'checker_tokens':wallets[name].paid,
            'checker_remaining_tokens':wallets[name].available,
            'unfinished_thinking':sum(r['unfinished_thought'] for r in items),
            'cpu_seconds':round(sum(r['cpu'] for r in items),9),
            'wall_seconds':round(sum(r['wall'] for r in items),9),
            'external_net_correct_minus_full_serving_tokens':str(Q(correct)-TARIFF*tokens)}
    return {'schema':SCHEMA+'.postseal-original-independent-token-accounting.v1',
            'status':'RESEARCH_ONLY_DENY_ALL','original_reader_model_calls':len(completed['train_calls'])+len(completed['held_calls']),
            'train_forward_calls':len(completed['train_calls']),'held_forward_calls':len(completed['held_calls']),
            'original_journal_events':len(events),'training_full_paid_tokens':train_paid,
            'actual_original_physical_source':require_physical,
            'retrospective_known_public_publisher_not_future_source':True,
            'original_reported_load_cpu_seconds':completed.get('load_cpu_seconds'),
            'original_reported_load_wall_seconds':completed.get('load_wall_seconds'),
            'per_policy':summary,
            'ndu_ordinary_same_profile_parity':True,'independent_hardware_meter':False,
            'semantic_result':'NO_NDU_SUPERIORITY_OR_TOKEN_SAVINGS_CERTIFIED',
            'authority':'DENY_ALL'}


def main():
    ap=argparse.ArgumentParser()
    for key in ('train','held','gold','plan','original','journal','output'):
        ap.add_argument('--'+key,type=Path,required=True)
    args=ap.parse_args()
    quote=IndependentFrozenTokenizerQuote()
    r=audit(read(args.train),read(args.held),read(args.gold),read(args.plan),
            read(args.original),args.journal,args.plan,quote_fn=quote)
    write_new(args.output,r)
    print(json.dumps({'status':'RESEARCH_ONLY_DENY_ALL','census':r['original_reader_model_calls'],
                      'per_policy':r['per_policy']},sort_keys=True))

if __name__=='__main__':main()
