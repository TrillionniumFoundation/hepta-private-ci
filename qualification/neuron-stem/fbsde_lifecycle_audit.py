"""Independent finite-table, source-call and current-use ledger reconstruction.

Imports neither the lifecycle controller nor a learning/planning implementation.
Byte consistency cannot establish a trustworthy external owner or source.
"""
from pathlib import Path
import hashlib
import random
from four_gate_common import digest, require, strict_loads
from fbsde_transfer_reference import STATES, tables, source_effect

PROFILE='revocable_rule_transfer_v1'
MODES=('unguarded_snapshot','generation_only','sentinel_once','verify_each','direct_observation')
SCENARIOS=('stable','announced_successor','silent_successor','silent_copy')


def reference(old, scenario, mode):
    family=tables(); new=old if scenario=='stable' else None if scenario=='silent_copy' else (old+1)%33
    calls=[]; effects=family[old]; status='active'; attempts=0
    def observed(state, initial=False):
        return source_effect(old if initial else new,STATES[state]) if initial or new is not None else (0,0,1)
    def learn(initial=False):
        nonlocal effects,status,attempts
        ids=list(range(33));used=0
        while len({family[i] for i in ids})>1 and (used if initial else attempts)<5:
            s=next(s for s in range(6) if len({family[i][s] for i in ids})>1)
            o=observed(s,initial);calls.append(('initial' if initial else 'deployment','initial' if initial else 'relearn',s,o))
            used+=1
            if not initial:attempts+=1
            if o not in STATES:status='refused';return
            ids=[i for i in ids if family[i][s]==STATES.index(o)]
            require(ids,'reference inconsistent stationary source')
        if len({family[i] for i in ids})==1:effects=family[ids[0]];status='active'
    if mode!='direct_observation':learn(True)
    if scenario=='announced_successor' and mode not in ('unguarded_snapshot','direct_observation'):status='quarantined'
    outputs=[]
    for s,state in enumerate(STATES):
        value=None;verified=False
        if mode=='unguarded_snapshot':value=tuple(state[j] for j in STATES[effects[s]])
        elif mode=='direct_observation':
            o=observed(s);calls.append(('deployment','direct',s,o));value=tuple(state[j] for j in o);verified=True
        else:
            if status=='quarantined':learn()
            if status=='active':
                for attempt in range(2):
                    if status!='active':break
                    check=mode=='verify_each' or mode=='sentinel_once' and s==0
                    if check:
                        o=observed(s);calls.append(('deployment','verify_use',s,o))
                        if o!=STATES[effects[s]]:
                            status='quarantined'
                            if attempt==0:learn()
                            continue
                    value=tuple(state[j] for j in STATES[effects[s]]);verified=check;break
        outputs.append((value,verified))
    return outputs,calls


def audit(root):
    root=Path(root)
    def read(name):
        p=root/(name+'.json');require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded evidence')
        return strict_loads(p.read_bytes())
    def ns(v): require(type(v) is int and v>=0,'nonnegative CPU');return v
    plan=read('plan');publics=read('inputs');targets=read('targets');rows=read('outputs');results=read('results')
    require(plan['profile']==PROFILE and plan['seed']==2026101357 and plan['modes']==list(MODES) and
        plan['scenarios']==list(SCENARIOS) and plan['initial_reset_limit']==plan['recovery_reset_limit']==5 and
        plan['verification_max_per_target']==2 and len(publics)==len(targets)==132 and len(rows)==660,'complete fixed design')
    summary={};cursor=0;published=0;source_count=0;family=tables()
    for index,public in enumerate(publics):
        old=index//4;scenario=SCENARIOS[index%4];sid=digest([PROFILE,2026101357,old,scenario])
        require(public==dict(source_id=sid,names=['Mira','Nolan','Orla'],event='Mira, Nolan and Orla execute the registered operation.'),'public inventory')
        new=old if scenario=='stable' else None if scenario=='silent_copy' else (old+1)%33
        require(targets[sid]==dict(old=old,scenario=scenario,new=new),'private source mapping')
        order=list(MODES);random.Random(2026101357+index).shuffle(order)
        for mode in order:
            row=rows[cursor];cursor+=1
            require(row['source_id']==sid and row['mode']==mode and len(row['outputs'])==6 and
                row['production_promotion_permitted'] is False,'paired output inventory')
            expected,expected_calls=reference(old,scenario,mode);actual_calls=[]
            for call in row['source_calls']:
                req=call['request'];receipt=call['receipt'];state=STATES.index(tuple(req['state']))
                purpose='initial' if call['stage']=='initial' else req['purpose']
                require(receipt['request_sha256']==digest(req),'source receipt identity')
                if purpose!='initial':
                    require(req['environment']==sid and req['scope']=='rule-lifecycle-study' and
                        req['generation']==(2 if scenario=='announced_successor' else 1),'current source context')
                actual_calls.append((call['stage'],purpose,state,tuple(receipt['effect'])));ns(call['cpu_ns'])
            require(actual_calls==expected_calls,'source choices/counts/effects mismatch');source_count+=len(actual_calls)
            for out,(value,verified),state in zip(row['outputs'],expected,STATES):
                require(out['state']==list(state) and out['target']==STATES.index(state) and
                    out['value']==(list(value) if value is not None else None) and out['verified']==verified,'publication/value mismatch')
                ns(out['cpu_ns']);published+=value is not None
            ledger=row['ledger']
            deployment=[(c['request'],c['receipt']) for c in row['source_calls'] if c['stage']=='deployment']
            if mode not in ('unguarded_snapshot','direct_observation'):
                linked=[(e['request'],e['receipt']) for e in ledger if e['event'] in ('verification','recovery_receipt')]
                require(deployment==linked,'source calls not linked to lifecycle receipts')
            if mode!='direct_observation':
                initial=row['initial'];init_calls=[c for c in row['source_calls'] if c['stage']=='initial']
                require([(c['request'],c['receipt']) for c in init_calls]==[(c['request'],c['receipt']) for c in initial['records']]
                    and 0<len(init_calls)<=5 and initial['identified'] is True,'initial source evidence')
                ctx=dict(scope='rule-lifecycle-study',environment=sid,generation=1);binding=digest([public,ctx])
                frame=digest(['verified_role_program_v1','{R0}, {R1} and {R2} execute the registered operation.'])
                pid=digest(['counterfactual_rule_transfer_v1',binding,frame,family])
                hist=tuple((STATES.index(tuple(c['request']['state'])),STATES.index(tuple(c['receipt']['effect']))) for c in init_calls)
                require(initial['snapshot']==dict(frame=frame,context=digest(dict(binding=binding,**ctx)),
                    effects=list(family[old]),evidence=digest([pid,hist])) and ledger[0]['snapshot']==initial['snapshot'],
                    'initial table reconstruction')
            pending={};active=True;rev=0;last=None;recovery=0;h=()
            for i,e in enumerate(ledger):
                require(e['sequence']==i and e['previous']==(digest(last) if last is not None else None),'lifecycle chain')
                event=e['event']
                if event=='retire':
                    require(e['revision']==rev+1,'monotone revision');rev+=1;pending={};active=False;h=()
                else:require(e['revision']==rev,'current revision')
                if event=='begin':
                    ticket=e['ticket'];req=e['request']
                    require(active and ticket['revision']==rev and ticket['identity']==digest(req),'stale begin')
                    key=digest(ticket);require(key not in pending,'duplicate ticket');pending[key]=e['predicted']
                elif event=='finish':
                    key=digest(e['ticket']);require(active and key in pending and pending[key]==e['value'],'stale publication')
                    del pending[key]
                elif event=='recovery_request':
                    req=e['request'];require(not active and req['sequence']==recovery and
                        req['remaining']==5-recovery and req['history_sha256']==digest(h),'recovery allowance/history reset')
                    recovery+=1
                elif event=='recovery_receipt' and e['receipt'] is not None and tuple(e['receipt']['effect']) in STATES:
                    req=e['request'];h+=((STATES.index(tuple(req['state'])),STATES.index(tuple(e['receipt']['effect']))),)
                elif event=='reactivate':
                    support=[j for j in range(33) if all(family[j][s]==o for s,o in h)]
                    require(not active and support and len({family[j] for j in support})==1 and
                        e['snapshot']['effects']==list(family[support[0]]) and e['history']==[list(x) for x in h], 'unidentified rule reactivated')
                    active=True
                last=e
            if mode not in ('unguarded_snapshot','direct_observation'):
                finished=[e['value'] for e in ledger if e['event']=='finish']
                require(finished==[o['value'] for o in row['outputs'] if o['value'] is not None],'missing/stale finish')
                require(row['status']['recovery_attempts']==recovery<=5 and row['status']['pending']==0,'unpaid recovery')
            stats=summary.setdefault(scenario+':'+mode,dict(episodes=0,requests=0,published=0,correct=0,wrong=0,
                initial_calls=0,verification_calls=0,recovery_calls=0,direct_calls=0,cpu_ns=0))
            stats['episodes']+=1;stats['cpu_ns']+=ns(row['cpu_ns'])
            for out in row['outputs']:
                state=tuple(out['state']);effect=(0,0,1) if new is None else source_effect(new,state);truth=[state[j] for j in effect]
                stats['requests']+=1;stats['published']+=out['value'] is not None
                stats['correct']+=out['value'] is not None and out['value']==truth
                stats['wrong']+=out['value'] is not None and out['value']!=truth
            for _,purpose,_,_ in actual_calls: stats[dict(initial='initial_calls',verify_use='verification_calls',relearn='recovery_calls',direct='direct_calls')[purpose]]+=1
    require(summary==results['summary'] and results['complete'] is True and
        all(results[k] is False for k in ('independent_sources','new_neural_training','native_owner_integration','production_promotion_permitted')),'false score/cost/certificate')
    retention=read('retention')['stream']
    require(retention['rows']==len(rows) and retention['file_sha256']==hashlib.sha256((root/'outputs.json').read_bytes()).hexdigest(),'original bytes')
    return dict(episodes_recomputed=len(rows),target_requests=3960,published=published,source_calls=source_count,
                stale_publications_after_fence=0,independent_execution_attestation=False,production_promotion_permitted=False)
