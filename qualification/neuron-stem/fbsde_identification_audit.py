"""Original-receipt and rational Bellman audit, not a deployment qualification."""
import random
from pathlib import Path
from four_gate_common import digest, require, strict_loads
from fbsde_identification_reference import Reference, STATES, source_effect, support, agreement

MODES=('optimal','greedy_coverage','first_informative','prior_fixed')
PROFILE='budgeted_rule_identification_v1'


def audit(root):
    root=Path(root)
    def read(name):
        path=root/(name+'.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<64*1024*1024,'bounded evidence')
        return strict_loads(path.read_bytes())
    def ns(x):require(type(x) is int and x>=0,'nonnegative CPU');return x
    plan=read('plan');cases=read('inputs');truth=read('targets');rows=read('outputs');prep=read('preparation');result=read('results')
    require(plan['profile']==PROFILE and plan['seed']==2026101331 and plan['modes']==list(MODES) and
        plan['budgets']==list(range(7)) and plan['rules']==33 and plan['decision_cpu_limit_ns']==100_000_000 and
        plan['planning_nodes']==20000 and plan['two_query_default_unchanged'] is True and
        plan['objective']=='complete_table_then_minimum_experiments' and plan['prior']=='uniform_33_programs', 'registered identification design')
    require(len(cases)==len(truth)==33 and len(rows)==33*7*4,'complete identification denominator')
    ref=Reference();table=ref.table;root_mask=(1<<33)-1;ceilings=[]
    require(len(prep['optimal'])==len(prep['fixed'])==7,'preparation inventory')
    for budget in range(7):
        prob,cost,state=ref.optimal(root_mask,budget);r=prep['optimal'][budget]
        require(r['budget']==budget and r['identified_mass']==prob*33 and r['query_mass']==cost*33 and
            r['total_mass']==33 and r['root_state']==state and 1<=r['compiled_nodes']<=20000,'exact Bellman identification ceiling')
        exact=Reference();exact.optimal(root_mask,budget)
        entries=[]
        for (mask,depth),(q,c,a) in exact.memo.items():
            ids=tuple(i for i in range(33) if mask>>i&1)
            entries.append((ids,depth,int(q*len(ids)),int(c*len(ids)),a))
        expected_id=digest([PROFILE,digest(table),budget,tuple(sorted(entries))])
        require(r['compiled_nodes']==len(entries) and r['policy_sha256']==expected_id,'compiled policy identity')
        ns(r['preparation_cpu_ns']);order,good,calls=ref.fixed_order(budget);f=prep['fixed'][budget]
        require(f['order']==list(order) and (f['identified_mass'],f['query_mass'],f['budget'])==(good,calls,budget)
            and f['family_sha256']==digest(table),'prior fixed experiment design')
        ns(f['preparation_cpu_ns']);ceilings.append(dict(budget=budget,identified_numerator=int(prob*33),
            prior_denominator=33,expected_source_calls=str(cost)))
    totals={};cursor=0;count_calls=0
    for i,public in enumerate(cases):
        sid=digest([PROFILE,2026101331,i]);expected=dict(source_id=sid,names=['Mira','Nolan','Orla'],
            event='Mira, Nolan and Orla execute the registered operation.')
        require(public==expected and truth[sid]==i,'unfiltered source inventory')
        ctx=dict(scope='budgeted-identification-study',generation=1,environment=sid)
        binding=digest([public,ctx]);frame=digest(['verified_role_program_v1','{R0}, {R1} and {R2} execute the registered operation.'])
        pid=digest(['counterfactual_rule_transfer_v1',binding,frame,table])
        order=[(b,m) for b in range(7) for m in MODES];random.Random(2026101331+i).shuffle(order)
        for budget,mode in order:
            row=rows[cursor];cursor+=1;r=row['result']
            require(row['source_id']==sid and row['context']==ctx and row['budget']==budget and row['mode']==mode and
                r['mode']==mode and r['budget']==budget and r['problem_sha256']==pid,'source/budget/mode identity')
            history=();di=0;ri=0
            while len(history)<budget:
                if all(v is not None for v in agreement(support(history))):break
                state=ref.action(mode,history,budget);require(di<len(r['decisions']),'missing decision')
                decision=r['decisions'][di];di+=1
                require(decision['state_index']==state and decision['known']==[list(h) for h in history] and
                    ns(decision['cpu_ns'])<=100_000_000,'changed action or decision budget')
                if mode=='optimal':
                    ids=support(history);p,c,s=ref.optimal(sum(1<<j for j in ids),budget-len(history))
                    require(decision['plan']==dict(state_index=s,identified_mass=int(p*len(ids)),query_mass=int(c*len(ids)),
                        support_size=len(ids),remaining=budget-len(history),policy_sha256=prep['optimal'][budget]['policy_sha256']), 'compiled continuation value')
                if state is None:break
                require(ri<len(r['records']),'missing selected experiment');rec=r['records'][ri];ri+=1
                request=dict(protocol='budgeted_controlled_reset_v1',problem_sha256=pid,binding=binding,
                    state=list(STATES[state]),sequence=len(history),history_sha256=digest(history),
                    declared_budget=budget,remaining=budget-len(history))
                actual=source_effect(i,STATES[state])
                require(rec['request']==request and rec['receipt']==dict(request_sha256=digest(request),effect=list(actual)),
                        'source receipt/sequence/remaining budget mismatch')
                ns(rec['cpu_ns']);history+=((state,STATES.index(actual)),);count_calls+=1
            require(ri==len(r['records']) and di==len(r['decisions']) and r['history']==[list(h) for h in history] and
                r['support']==list(support(history)) and r['failure'] is None,'complete nonanticipative history')
            agreed=agreement(support(history));complete=all(x is not None for x in agreed)
            require(r['agreed']==list(agreed) and r['identified']==complete,'false complete rule')
            snapshot=dict(frame=frame,context=digest(dict(binding=binding,**ctx)),effects=list(agreed),evidence=digest([pid,history])) if complete else None
            require(r['snapshot']==snapshot and len(row['applied'])==(36 if complete else 0),'export before complete identification')
            require(r['semantic_certificate'] is False and r['family_coverage_authenticated'] is False and
                r['production_promotion_permitted'] is False,'unjustified semantic certification')
            key=f'{budget}:{mode}';t=totals.setdefault(key,dict(cases=0,identified=0,experiments=0,agreed_states=0,
                correct_states=0,transferred=0,correct_transferred=0,unqueried_transferred=0,
                controller_cpu_ns=0,build_cpu_ns=0,apply_cpu_ns=0))
            t['cases']+=1;t['identified']+=complete;t['experiments']+=len(history)
            for s,e in enumerate(agreed):
                t['agreed_states']+=e is not None;t['correct_states']+=e is not None and STATES[e]==source_effect(i,STATES[s])
            for j,pred in enumerate(row['applied']):
                roles=STATES[j//6];state=STATES[j%6];names=['Ari','Bea','Cora']
                text=', '.join(names[k] for k in roles[:2])+' and '+names[roles[2]]+' execute the registered operation.'
                require(plan['targets'][j]==dict(event=text,names=names,state=list(state),roles=list(roles)), 'transfer domain drift')
                normalized=tuple(state[k] for k in roles);op=source_effect(i,normalized)
                expected=tuple(state[roles[op[roles.index(k)]]] for k in range(3))
                require(tuple(pred)==expected,'wrong transferred effect')
                t['transferred']+=1;t['correct_transferred']+=1;t['unqueried_transferred']+=STATES.index(normalized) not in {s for s,o in history}
            t['controller_cpu_ns']+=ns(r['cpu_ns']);t['build_cpu_ns']+=ns(row['build_cpu_ns']);t['apply_cpu_ns']+=ns(row['apply_cpu_ns'])
            require(row['total_cpu_ns']>=r['cpu_ns']+row['build_cpu_ns']+row['apply_cpu_ns'] and
                r['cpu_ns']>=sum(d['cpu_ns'] for d in r['decisions'])+sum(c['cpu_ns'] for c in r['records']), 'unpaid observed work')
    require(totals==result['summary'] and count_calls==result['source_experiments'],'scores/costs differ from original rows')
    require(all(result[k] is False for k in ('independent_sources_authenticated','family_coverage_authenticated','production_promotion_permitted')), 'unsupported result assurance')
    # Recompute the original byte commitment instead of accepting a PASS or stale stream hash.
    retention=read('retention');import hashlib
    require(retention['stream']['file_sha256']==hashlib.sha256((root/'outputs.json').read_bytes()).hexdigest()
        and retention['stream']['rows']==len(rows),'original stream bytes')
    return dict(outputs_recomputed=len(rows),source_experiments_recomputed=count_calls,exact_budget_frontier=ceilings,
        minimum_worst_case_resets_in_family=next(r['budget'] for r in ceilings if r['identified_numerator']==33),
        family_coverage_authenticated=False,production_promotion_permitted=False)
