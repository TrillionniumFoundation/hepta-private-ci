"""Read-only source, conditional-world, selected-feedback and cost reconstruction."""
import hashlib
from pathlib import Path
from four_gate_common import canonical, digest, require, strict_loads
from fbsde_conditional_data import generate, FRAMES, SEED, STRATA
from fbsde_conditional_reference import Reference, actual, OPS
from fbsde_effect_audit import Reference as OldReference

ARMS=('constant_two','conditional_one','conditional_two','conditional_probe',
      'conditional_no_checks','event_probe','legacy_expand_audit','exact')


def audit(root):
    root=Path(root)
    def read(name):
        p=root/(name+'.json'); require(p.is_file() and not p.is_symlink() and p.stat().st_size<=64*1024*1024,'bounded artifact')
        return strict_loads(p.read_bytes())
    def ns(x):require(type(x) is int and x>=0,'CPU nanoseconds');return x
    require(not (root/'failure.json').exists(),'failed study is not complete')
    inputs=read('inputs');design=read('design');results=read('results');streams=read('streams')
    require(inputs==generate() and digest(inputs)==design['input_sha256'] and design['arms']==list(ARMS) and
        design['frames']==list(FRAMES) and (design['seed'],design['checks'],design['nodes'],design['cpu_ns'],design['worlds'])==
        (SEED,2,20000,100_000_000,8192),'frozen design and complete controls')
    require(results['profile']==design['profile']=='conditional_program_induction_v1' and
        results['independent_risk_certified'] is False and results['new_pretrained_forward'] is False and
        results['production_promotion_permitted'] is False,'non-authorizing scope')
    outputs={a:read(a) for a in ARMS};require(set(streams)==set(ARMS),'stream inventory');payload=0
    for a,rows in outputs.items():
        require([r['source_id'] for r in rows]==[r['public']['source_id'] for r in inputs],'paired task denominator')
        size=sum(len(canonical(r)) for r in rows);raw=(root/(a+'.json')).read_bytes();payload+=size
        require(streams[a]==dict(file_sha256=hashlib.sha256(raw).hexdigest(),rows=len(rows),
            serialized_payload_bytes=size,native_durability_claimed=False),'original stream bytes')
    summary={s:{a:dict(cases=0,correct=0,answered=0,checks=0,cpu_ns=0) for a in ARMS} for s in STRATA};targets={}
    for i,item in enumerate(inputs):
        public=item['public'];effects,truth=actual(public);targets[public['source_id']]=truth
        for arm in ARMS:
            r=outputs[arm][i];h=();used=0;holder=None;reason=None;p=None
            require(r['arm']==arm and r['semantic_certificate'] is False and r['production_promotion_permitted'] is False,'non-authorizing output')
            if arm=='exact':
                holder=truth;reason='exact_registered_simulator';require(not r['checks'] and not r['decisions'],'exact control work')
            elif arm in ('event_probe','legacy_expand_audit'):
                # Reconstruct the OLD model as an independent control, not using its executor.
                grouping='event' if arm=='event_probe' else 'frame';ref=OldReference(public,grouping,None,0)
                if grouping=='event':ref=OldReference(public,grouping,[tuple(range(6))]*len(effects),0)
                require(r['initial_sha256']==ref.identity,'old initial family');rev=0
                for turn,d in enumerate(r['decisions']):
                    p,available,_=ref.state(h);unread=[j for j in range(len(effects)) if j not in dict(h)]
                    repeated=arm=='legacy_expand_audit' and turn==1 and any(ref.groups[j]==ref.groups[r['checks'][0]['event']] for j in unread)
                    if arm=='legacy_expand_audit' and turn==0:action='verify:0'
                    elif repeated:action=f'verify:{next(j for j in reversed(unread) if ref.groups[j]==ref.groups[r["checks"][0]["event"]])}'
                    elif arm=='event_probe':
                        supp=[j for j,q in enumerate(p) if q>0]
                        action=f'answer:{supp[0]}' if len(supp)==1 else f'verify:{available[0]}' if available and used<2 else 'abstain'
                    else:action=ref.choose(h,2-used)[1]
                    require(d['known']==[list(t) for t in h] and d['action']==action and d['probabilities']==p and
                            d['problem_sha256']==ref.identity and ns(d['cpu_ns'])<=100_000_000,'old public decision')
                    if not action.startswith('verify:'):
                        holder=None if action=='abstain' else int(action.split(':')[1]);reason='family_conditional_answer' if holder is not None else 'insufficient_support';break
                    e=int(action.split(':')[1]);check=r['checks'][used];used+=1
                    require(used<=2 and check['event']==e and check['known_before']==[list(t) for t in h] and
                        check['receipt']==dict(effect=list(effects[e]),source_sha256=digest(public),event_sha256=digest(public['events'][e]),known_sha256=digest(h)),'old paid source')
                    if effects[e] not in OPS:reason='unsupported_nonbijective_effect';p=None;break
                    nxt=tuple(sorted(h+((e,OPS.index(effects[e])),)));kind,obs=ref.conflict(nxt)
                    if kind:
                        require(arm=='legacy_expand_audit','event contradiction');entry=r['revisions'][rev];rev+=1
                        grouping='event' if kind=='frame_conflict' else ref.grouping
                        supports=[tuple(range(6))]*len(effects) if kind=='frame_conflict' else [tuple(range(6)) if g in obs and obs[g] not in s else s for g,s in enumerate(ref.supports)]
                        new=OldReference(public,grouping,supports,ref.revision+1);new.state(nxt)
                        require(entry['from_sha256']==ref.identity and entry['to_sha256']==new.identity and
                            entry['history_sha256']==digest(nxt) and entry['remaining_checks']==2-used,'old evidence-preserving revision')
                        ref=new
                    h=nxt
                require(used==len(r['checks']) and rev==len(r['revisions']) and r['final_sha256']==ref.identity and
                        r['final_known']==[list(t) for t in h] and r['probabilities']==p,'old final evidence')
            else:
                ref=Reference(public,'constant' if arm=='constant_two' else 'conditional')
                require(r['problem_sha256']==ref.identity,'conditional source binding')
                for turn,d in enumerate(r['decisions']):
                    p,available,_,posterior=ref.state(h)
                    if arm=='conditional_probe':
                        supp=[j for j,q in enumerate(p) if q>0]
                        action=f'answer:{supp[0]}' if len(supp)==1 else f'verify:{available[0]}' if available and used<2 else 'abstain'
                    else:
                        depth=0 if arm=='conditional_no_checks' else min(2-used,1 if arm=='conditional_one' else 2)
                        value,action=ref.choose(h,depth)
                        require(d['plan']['action']==action and abs(d['plan']['value']-value)<1e-10,'original conditional Bellman law')
                    require(d['known']==[list(t) for t in h] and d['action']==action and d['probabilities']==p and
                        d['posterior']==posterior and d['problem_sha256']==ref.identity and ns(d['cpu_ns'])<=100_000_000 and
                        0<=ns(d['nodes'])<=20000,'conditional public decision')
                    if not action.startswith('verify:'):
                        holder=None if action=='abstain' else int(action.split(':')[1]);reason='conditional_family_answer' if holder is not None else 'insufficient_support';break
                    e=int(action.split(':')[1]);check=r['checks'][used];used+=1
                    require(e in available and used<=2 and check['event']==e and check['known_before']==[list(t) for t in h] and
                        check['receipt']==dict(effect=list(effects[e]),source_sha256=digest(public),event_sha256=digest(public['events'][e]),known_sha256=digest(h)),'selected-only effect evidence')
                    if effects[e] not in OPS:reason='unsupported_nonbijective_effect';p=None;break
                    nxt=tuple(sorted(h+((e,OPS.index(effects[e])),)))
                    if not any(all(w[1][j]==o for j,o in nxt) for w in ref.rows):reason='outside_conditional_family';p=None;break
                    h=nxt
                require(used==len(r['checks']) and r['final_known']==[list(t) for t in h] and r['probabilities']==p,'complete conditional history')
            require(arm=='exact' or turn==len(r['decisions'])-1,'ghost trailing decisions')
            require((r['holder'],r['reason'],r['text'])==(holder,reason,'Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]),'decoded answer')
            require(ns(r['cpu_ns'])>=sum(ns(d['cpu_ns']) for d in r['decisions'])+sum(ns(c['cpu_ns']) for c in r['checks']),'physical envelope')
            s=summary[item['stratum']][arm];s['cases']+=1;s['correct']+=holder==truth;s['answered']+=holder is not None;s['checks']+=len(r['checks']);s['cpu_ns']+=r['cpu_ns']
    for group in summary.values():
        for s in group.values():s['conditional_utility']=(2*s['correct']-s['answered']-.02*s['checks'])/s['cases']
    require(read('targets')==targets and results['summary']==summary and payload==results['record_payload_bytes'],'original score and costs')
    return dict(outputs_recomputed=len(inputs)*len(ARMS),true_predecessor_given_to_policy=False,
                families_assumed_not_authenticated=True,production_promotion_permitted=False)
