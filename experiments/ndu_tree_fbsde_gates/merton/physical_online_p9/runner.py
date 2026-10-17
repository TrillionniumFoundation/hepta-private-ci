"""P9 original Qwen3 two-resource (physical tokens + call slots) online trial.

Only TRAIN carries labels. Physical calls are durably journaled, and a checker
cannot start without committing its full max-new-token reservation first.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
from collections import Counter

from portfolio import (SCHEMA,POLICIES,MAX_CHECKS,TOKEN_ENDOWMENT,CHECK_CAP,
                       Controller,TokenEscrow)
from source import SOURCE_SCHEMA,RULE
from parent import load_p8

ORIGINAL_RUNTIME='qwen3-p9-hard-prepaid-1500-4calls-fourth-fifth-training-third-held-v1'
P8=load_p8('online')
write_new=P8.write_new
read=P8.read
digest=P8.digest
rotate=P8.rotate


def source_packets(train,held):
    if type(train) is not dict or type(held) is not dict or set(train)!={'schema','source','rows'} or set(held)!={'schema','source','rows'}:
        raise ValueError('wrong P9 exact original packet fields')
    if train['schema']!=SOURCE_SCHEMA+'.train' or held['schema']!=SOURCE_SCHEMA+'.held-public' or train['source']!=held['source']:
        raise ValueError('P9 source identity mismatch')
    previous=load_p8('source').original_module().original_manifest()
    manifest={**previous,'split_rule':RULE,'historical_publisher_not_future_source':True,
              'prior_p5_p8_cohort_disjoint':True}
    if train['source']!=manifest:raise ValueError('publisher/source-lock drift')
    if type(train['rows']) is not list or type(held['rows']) is not list or len(train['rows'])!=32 or len(held['rows'])!=16:
        raise ValueError('invalid P9 source census')
    ids=set();texts=set();train_strata=Counter()
    for phase,rs in (('train',train['rows']),('held',held['rows'])):
        for row in rs:
            fields={'task_id','text','text_sha256','bucket','group'}|({'label'} if phase=='train' else set())
            if type(row) is not dict or set(row)!=fields or type(row['text']) is not str or not 16<=len(row['text'])<=2500:
                raise ValueError('unexpected source fields or label leakage')
            if row['text_sha256']!=hashlib.sha256(row['text'].encode()).hexdigest():
                raise ValueError('invalid original text digest')
            m=re.fullmatch(phase+r'-([0-9]{5})',row['task_id'])
            if (not m or row['group']!=phase+'-row-parity-'+str(int(m.group(1))%2)
                or row['bucket']!=('short' if len(row['text'])<=180 else 'long')):
                raise ValueError('untrustworthy original identity or difficulty')
            if row['task_id'] in ids or row['text_sha256'] in texts:
                raise ValueError('duplicated original source identity')
            ids.add(row['task_id']);texts.add(row['text_sha256'])
            if phase=='train':
                if type(row['label']) is not int or row['label'] not in range(4):
                    raise ValueError('malformed original TRAIN truth')
                train_strata[row['label'],row['bucket'],int(m.group(1))%2]+=1
    if len(train_strata)!=16 or set(train_strata.values())!={2}:
        raise ValueError('TRAIN class/bucket/parity source support missing')
    return train['rows'],held['rows']


class QwenReader:
    physical=True
    def __init__(self):
        parent=load_p8('online').QwenReader()
        self.parent=parent
        self.identity={**parent.identity,'runtime':ORIGINAL_RUNTIME}
        self.load_cpu=parent.load_cpu;self.load_wall=parent.load_wall

    def quote(self,text:str,action:str,previous:str)->int:
        if action not in ('check_plain','check_think'):
            raise ValueError('only checker quotes are admissible')
        p=P8.make_prompt(text,action,previous)
        ids=self.parent.tok.apply_chat_template(p,tokenize=True,add_generation_prompt=True,
                enable_thinking=action=='check_think')
        if type(ids) is not list or not 1<=len(ids)<=1024 or any(type(v) is not int or v<0 for v in ids):
            raise ValueError('tokenizer quote invalid')
        return len(ids)

    def infer(self,text,action,previous=None):
        return self.parent.infer(text,action,previous)


def paid(reader,text,action,case,phase,policy,previous,journal):
    return P8.invoke(reader,text,action,case,phase,policy,previous,journal)


def execute(train,held,reader,output:Path):
    training,public=source_packets(train,held)
    if output.exists():raise FileExistsError('cannot overwrite original evidence')
    output.mkdir(parents=True,exist_ok=False)
    journal=P8.Journal(output/'original-starts-and-dones.jsonl')
    paid_train=[];paid_held=[];decisions=[]
    try:
        for row in training:
            base=paid(reader,row['text'],'direct',row['task_id'],'train','train',None,journal)
            paid_train.append(base)
            for choice in ('check_plain','check_think'):
                paid_train.append(paid(reader,row['text'],choice,row['task_id'],'train','train',
                                      base['result']['answer'],journal))
        p8profile=__import__('policy').train_profile(training,paid_train)
        buckets=tuple(x['bucket'] for x in public)
        plan={'schema':SCHEMA+'.frozen-plan','train_source_digest':digest(train),
              'held_public_digest':digest(held),'train_profile':p8profile,
              'held_task_ids':[x['task_id'] for x in public],
              'buckets':list(buckets),'policies':list(POLICIES),
              'incremental_token_endowment_per_policy':TOKEN_ENDOWMENT,
              'max_checker_calls_per_policy':MAX_CHECKS,'max_checker_generated_tokens':CHECK_CAP,
              'original_model':reader.identity,'train_original_calls':len(paid_train),
              'source_owner_held_labels_absent':True,'authority':'DENY_ALL'}
        write_new(output/'frozen-plan.json',plan)
        plan_sha=hashlib.sha256((output/'frozen-plan.json').read_bytes()).hexdigest()
        journal.emit('plan','frozen','system','seal','sealed',plan_sha)
        controllers={n:Controller(p8profile,buckets,n) for n in POLICIES}
        wallets={n:TokenEscrow() for n in POLICIES}
        for index,row in enumerate(public):
            for name in rotate(POLICIES,index):
                base=paid(reader,row['text'],'direct',row['task_id'],'held',name,None,journal)
                paid_held.append(base)
                quotes={a:reader.quote(row['text'],a,base['result']['answer'])
                        for a in ('check_plain','check_think')}
                wallet=wallets[name]
                choice=controllers[name].choose(index,wallet,row['bucket'],
                              base['result']['predicted_class'],quotes)
                d={'index':index,'case_id':row['task_id'],'policy':name,'choice':choice,
                   'base_answer_sha256':hashlib.sha256(base['result']['answer'].encode()).hexdigest(),
                   'input_quotes':quotes,'tokens_before':wallet.available,
                   'calls_before':wallet.remaining_calls}
                journal.emit('held',row['task_id'],name,choice,'decision',digest(d))
                if choice!='stop':
                    identity=f'held/{row["task_id"]}/{name}/{choice}'
                    reservation=wallet.reserve(identity,quotes[choice],CHECK_CAP)
                    journal.emit('held',row['task_id'],name,choice,'reserve',digest(reservation))
                    paid_check=paid(reader,row['text'],choice,row['task_id'],'held',name,
                                    base['result']['answer'],journal)
                    paid_held.append(paid_check)
                    settlement=wallet.settle(identity,paid_check['result']['input_tokens'],
                                            paid_check['result']['output_tokens'])
                    journal.emit('held',row['task_id'],name,choice,'settle',digest(settlement))
                decisions.append(d)
        final={'schema':SCHEMA+'.completed-original',
               'source_kind':'original_physical' if reader.physical is True else 'synthetic_fixture',
               'frozen_plan_sha256':plan_sha,'train_calls':paid_train,'held_calls':paid_held,
               'policy_decisions':decisions,
               'wallets':{name:w.wire() for name,w in wallets.items()},
               'journal_events':journal.seq,'model':reader.identity,
               'load_cpu_seconds':round(reader.load_cpu,9),
               'load_wall_seconds':round(reader.load_wall,9),
               'claim':'RESEARCH_ONLY_NO_NDU_SUPERIORITY_OR_REAL_SAVINGS_ESTABLISHED',
               'authority':'DENY_ALL'}
        write_new(output/'completed-original.json',final)
        return final
    finally:
        journal.close()


def main():
    ap=argparse.ArgumentParser()
    for k in ('train-public','held-public','output'):ap.add_argument('--'+k,type=Path,required=True)
    args=ap.parse_args()
    train,held=read(args.train_public),read(args.held_public)
    source_packets(train,held)
    model=QwenReader()
    result=execute(train,held,model,args.output)
    print(json.dumps({'posture':'RESEARCH_ONLY_DENY_ALL',
           'original_model_invocations':len(result['train_calls'])+len(result['held_calls']),
           'held_gold_available_to_worker':False},sort_keys=True))

if __name__=='__main__':main()
