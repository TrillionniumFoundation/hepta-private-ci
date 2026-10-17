"""P8 separate postseal original-publisher audit; no model generation allowed.

Verifies complete paid-call/journal census, original prompt and TRAIN-only policy
replay. Publisher labels arrive ONLY AFTER the original worker has finished.
This is an independently staged reviewer, not independent hardware attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from fractions import Fraction as Q
from pathlib import Path

from policy import POLICIES, BUDGET, SCHEMA, TARIFF, Controller, train_profile
from online import read, write_new, source_packets, make_prompt, parse_answer, digest, rotate, random_seed

SOURCE_SCHEMA=SCHEMA+'.original-publisher-second-occurrence'
MODEL_REPO='Qwen/Qwen3-0.6B'
MODEL_REV='16706fc57485378d4ffaf54139b29ccc66ae08fa'
WEIGHTS='f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b'
TOKENIZER='aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4'
PROFILE='qwen3-p8-conditional-paid-second-cohort-12-256-0.6-0.95-20-v1'


def insist(ok:bool,message:str):
    if not ok:raise ValueError(message)


def validate_original_call(row:dict,case:dict,phase:str,policy:str,action:str,previous:str|None,require_physical:bool):
    insist(type(row) is dict and set(row)=={'phase','task_id','policy','action','prompt_sha256','result','measured_cpu_seconds','measured_wall_seconds','source_kind'},'call fields')
    insist((row['phase'],row['policy'],row['action'],row['task_id'])==(phase,policy,action,case['task_id']),'task/call identity')
    if require_physical:insist(row['source_kind']=='original_physical','original worker not measured')
    else:insist(row['source_kind']=='synthetic_fixture','synthetic source mismatch')
    res=row['result']
    insist(type(res) is dict and set(res)=={'prompt_sha256','input_ids_sha256','output_ids_sha256',
        'sampling_seed','input_tokens','output_tokens','thinking_mode','thinking_tokens',
        'thinking_complete','answer','predicted_class'},'original model result shape')
    prompt=make_prompt(case['text'],action,previous)
    insist(res['prompt_sha256']==digest(prompt)==row['prompt_sha256'],'model prompt binding')
    insist(res['sampling_seed']==random_seed(prompt),'model seed binding')
    insist(res['predicted_class']==parse_answer(res['answer']),'raw parsed final mismatch')
    cap=12 if action=='direct' else 256
    insist(type(res['input_tokens']) is int and 1<=res['input_tokens']<=1024 and
           type(res['output_tokens']) is int and 1<=res['output_tokens']<=cap,'original finite token meter')
    insist(type(res['thinking_mode']) is bool and res['thinking_mode']==(action=='check_think') and
           type(res['thinking_complete']) is bool and type(res['thinking_tokens']) is int and
           0<=res['thinking_tokens']<=res['output_tokens'],'mode / thought accounting')
    insist(action=='check_think' or (not res['thinking_complete'] and res['thinking_tokens']==0),'nonthinking fabricated thought')
    insist(action!='check_think' or res['thinking_complete'] or res['answer']=='','truncated thought passed as final')
    for h in ('input_ids_sha256','output_ids_sha256','prompt_sha256'):
        insist(type(res[h]) is str and len(res[h])==64 and all(c in '0123456789abcdef' for c in res[h]),'invalid original tensor hash')
    for k in ('measured_cpu_seconds','measured_wall_seconds'):
        insist(type(row[k]) in (float,int) and math.isfinite(row[k]) and 0<=row[k]<3600,'invalid original timing')


def journal_validate(journal_path:Path,expected:list[tuple],plan_bytes:bytes):
    raw=journal_path.read_bytes()
    insist(raw.endswith(b'\n') and len(raw)<8_000_000,'journal truncation')
    lines=raw.splitlines();insist(len(lines)==len(expected),'journal event count or extra activity')
    previous='0'*64
    for n,(line,req) in enumerate(zip(lines,expected),1):
        ev=json.loads(line,object_pairs_hook=lambda x:unique(x))
        insist(type(ev) is dict and set(ev)=={'sequence','previous','phase','task_id','policy','action','event','receipt','digest'},'journal event schema')
        current=ev['digest'];body={k:v for k,v in ev.items() if k!='digest'}
        insist(ev['sequence']==n and ev['previous']==previous and digest(body)==current,'journal chain')
        insist(tuple(ev[k] for k in ('phase','task_id','policy','action','event'))==req[:5],'start/done/source/plan ordering')
        insist(ev['receipt']==req[5],'journal exact record digest')
        previous=current
    return len(lines)


def unique(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ValueError('duplicate journal JSON field')
        d[k]=v
    return d


def expected_event_calls(calls:list[dict],phase:str,case_map:dict,expected:list[tuple]):
    for row in calls:
        c=case_map[row['task_id']]
        prompt=make_prompt(c['text'],row['action'],None if row['action']=='direct' else c.get('_previous'))
        start={'phase':phase,'task_id':row['task_id'],'policy':row['policy'],
               'action':row['action'],'prompt_sha256':digest(prompt)}
        expected.append((phase,row['task_id'],row['policy'],row['action'],'start',digest(start)))
        expected.append((phase,row['task_id'],row['policy'],row['action'],'done',digest(row)))


def review(train:dict,held:dict,gold:dict,frozen:dict,completed:dict,journal_path:Path,plan_path:Path,require_physical=True):
    training, public=source_packets(train,held)
    insist(type(gold) is dict and gold.get('schema')==SOURCE_SCHEMA+'.held-private-labels' and gold.get('source')==train['source'],'postseal original publisher gold')
    private=gold.get('rows')
    insist(type(private) is list and len(private)==16,'missing complete original labels')
    gold_map={}
    for r in private:
        insist(type(r) is dict and set(r)=={'task_id','label','text_sha256'} and
            type(r['label']) is int and r['label'] in range(4),'invalid original publisher label')
        insist(r['task_id'] not in gold_map,'duplicate held publisher label')
        gold_map[r['task_id']]=r
    insist(set(gold_map)=={c['task_id'] for c in public},'publisher truth mismatch')
    insist(all(gold_map[r['task_id']]['text_sha256']==r['text_sha256'] for r in public),'publisher content/truth mix')
    insist(Counter(gold_map[x]['label'] for x in gold_map)=={i:4 for i in range(4)},'original class balance mismatch')
    strata=Counter((gold_map[x['task_id']]['label'], x['bucket'],int(x['task_id'][-5:])%2) for x in public)
    insist(len(strata)==16 and set(strata.values())=={1},'original HELD 4x2x2 class/bucket/parity support missing')
    insist(type(frozen) is dict and frozen.get('schema')==SCHEMA+'.frozen-plan','wrong sealed plan')
    insist(frozen.get('train_sha256')==digest(train) and frozen.get('held_public_sha256')==digest(held),'source corruption')
    insist(frozen.get('policies')==list(POLICIES) and frozen.get('held_task_ids')==[x['task_id'] for x in public] and
           frozen.get('held_buckets')==[x['bucket'] for x in public] and frozen.get('max_additional_calls')==BUDGET and
           frozen.get('no_held_labels') is True,'frozen policy or input changes')
    insist(type(completed) is dict and completed.get('schema')==SCHEMA+'.completed-original' and
           completed.get('authority')=='DENY_ALL','invalid sealed original run')
    insist(hashlib.sha256(plan_path.read_bytes()).hexdigest()==completed.get('frozen_plan_sha256'),'frozen source bytes mismatch')
    identity={'repo':MODEL_REPO,'revision':MODEL_REV,'weights_sha256':WEIGHTS,
              'tokenizer_sha256':TOKENIZER,'runtime':PROFILE,'actual_pretrained_model_loaded':True}
    if require_physical:insist(frozen.get('model')==completed.get('model')==identity,'substituted model weights/tokenizer/runtime')
    else:insist(frozen.get('model')==completed.get('model'),'mock identity changed')
    insist(completed.get('source_kind')==('original_physical' if require_physical else 'synthetic_fixture'),'fake physical run')
    train_calls=completed.get('train_calls');held_calls=completed.get('held_calls')
    insist(type(train_calls) is list and len(train_calls)==96,'missing/extra original TRAIN calls')
    insist(type(held_calls) is list and 96<=len(held_calls)<=96+6*BUDGET,'held on-policy call ceiling')
    events=[]
    for c in training:
        prev=None
        for action_index,a in enumerate(('direct','check_plain','check_think')):
            row=train_calls[3*training.index(c)+action_index]
            validate_original_call(row,c,'train','train',a,prev,require_physical)
            if a=='direct':prev=row['result']['answer']
            begin={'phase':'train','task_id':c['task_id'],'policy':'train','action':a,'prompt_sha256':row['prompt_sha256']}
            events.extend([('train',c['task_id'],'train',a,'start',digest(begin)),
                           ('train',c['task_id'],'train',a,'done',digest(row))])
    trained=train_profile(training,train_calls)
    insist(frozen.get('policy_profile')==trained,'TRAIN-only coefficients not reproducible')
    events.append(('plan','frozen','system','seal','sealed',hashlib.sha256(plan_path.read_bytes()).hexdigest()))
    controllers={p:Controller(trained,tuple(x['bucket'] for x in public),p) for p in POLICIES}
    remaining={p:BUDGET for p in POLICIES}
    policy_rows={p:[] for p in POLICIES};cursor=0
    for index,c in enumerate(public):
        for p in rotate(POLICIES,index):
            insist(cursor<len(held_calls),'missing paid original direct')
            base=held_calls[cursor];cursor+=1
            validate_original_call(base,c,'held',p,'direct',None,require_physical)
            begin={'phase':'held','task_id':c['task_id'],'policy':p,'action':'direct','prompt_sha256':base['prompt_sha256']}
            events.extend([('held',c['task_id'],p,'direct','start',digest(begin)),('held',c['task_id'],p,'direct','done',digest(base))])
            choice=controllers[p].choose(index,remaining[p],c['bucket'],base['result'])
            end=base
            costs=base['result']['input_tokens']+base['result']['output_tokens']
            cpu=base['measured_cpu_seconds'];wall=base['measured_wall_seconds']
            if choice!='stop':
                insist(cursor<len(held_calls),'missing physically paid checker')
                check=held_calls[cursor];cursor+=1
                validate_original_call(check,c,'held',p,choice,base['result']['answer'],require_physical)
                begin={'phase':'held','task_id':c['task_id'],'policy':p,'action':choice,'prompt_sha256':check['prompt_sha256']}
                events.extend([('held',c['task_id'],p,choice,'start',digest(begin)),('held',c['task_id'],p,choice,'done',digest(check))])
                remaining[p]-=1;end=check
                costs+=check['result']['input_tokens']+check['result']['output_tokens']
                cpu+=check['measured_cpu_seconds'];wall+=check['measured_wall_seconds']
            policy_rows[p].append({'case_id':c['task_id'],'action':choice,
                'correct':int(end['result']['predicted_class']==gold_map[c['task_id']]['label']),
                'direct_correct':int(base['result']['predicted_class']==gold_map[c['task_id']]['label']),
                'full_paid_tokens':costs,'cpu_seconds':cpu,'wall_seconds':wall,
                'unfinished_thinking':choice=='check_think' and not end['result']['thinking_complete']})
    insist(cursor==len(held_calls),'paid model calls excluded from audit')
    insist(completed.get('remaining_check_budgets')==remaining,'paid check ledger inconsistent')
    insist(completed.get('journal_events')==len(events),'journal reported wrong count')
    journal_validate(journal_path,events,plan_path.read_bytes())
    checks={p:[r['action'] for r in policy_rows[p]] for p in POLICIES}
    insist(checks['ndu_discrete']==checks['ordinary_same_profile'],'same-profile ordinary Bellman parity')
    results={}
    for p in POLICIES:
        xs=policy_rows[p]
        correct=sum(x['correct'] for x in xs)
        tokens=sum(x['full_paid_tokens'] for x in xs)
        results[p]={'correct':correct,'of':16,'full_paid_tokens':tokens,
                    'checker_invocations':sum(x['action']!='stop' for x in xs),
                    'incomplete_thinking':sum(x['unfinished_thinking'] for x in xs),
                    'cpu_seconds':round(sum(x['cpu_seconds'] for x in xs),9),
                    'wall_seconds':round(sum(x['wall_seconds'] for x in xs),9),
                    'external_net_success_minus_serving_tokens':str(Q(correct)-TARIFF*tokens)}
    results['ndu_vs_direct']={'wins':sum(a['correct']>b['correct'] for a,b in zip(policy_rows['ndu_discrete'],policy_rows['direct'])),
                              'losses':sum(a['correct']<b['correct'] for a,b in zip(policy_rows['ndu_discrete'],policy_rows['direct']))}
    return {'schema':SCHEMA+'.postseal-review', 'authority':'RESEARCH_ONLY_DENY_ALL',
            'method':'paid_two_stage_online_conditional_compute_on_16_original_historical_public_publisher_held_rows',
            'model_identity':identity if require_physical else frozen.get('model'),
            'physical_original_forward_invocations':len(train_calls)+len(held_calls),
            'train_forward_invocations':len(train_calls),'held_forward_invocations':len(held_calls),
            'journal_events':len(events),'train_full_paid_tokens':sum(r['result']['input_tokens']+r['result']['output_tokens'] for r in train_calls),
            'complete_study_model_load_cpu_seconds':completed.get('load_cpu_seconds'),
            'complete_study_model_load_wall_seconds':completed.get('load_wall_seconds'),
            'observed_task_and_full_paid_serving_cost_by_arm':results,
            'same_profile_parity':True, 'not_prospective_external_source':True,
            'hardware_independent_attestation':False,'all_research_and_training_calls_are_paid':True,
            'observed_counterfactual_free_compute_savings':False,
            'unqualified_claims':['not_neural_FBSDE','not_production','not_globally_optimal_Merton',
                                  'not_independently_authenticated_hardware','not_source_family_generalization',
                                  'no_NDU_superiority_inferred_without_independent_future_evidence']}


def main():
    ap=argparse.ArgumentParser()
    for k in ('train','held','gold','original','plan','journal','output'):
        ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args()
    result=review(read(a.train),read(a.held),read(a.gold),read(a.plan),read(a.original),a.journal,a.plan)
    write_new(a.output,result)
    print(json.dumps({'authority':'DENY_ALL','reviewed':result['physical_original_forward_invocations'],
                      'results':result['observed_task_and_full_paid_serving_cost_by_arm']},sort_keys=True))

if __name__=='__main__':main()
