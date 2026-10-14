"""Saved-record audit, independent source/table/rational planner, no runtime learner import."""
import math
import random
from pathlib import Path
from four_gate_common import digest,require,strict_loads
from fbsde_transfer_reference import STATES,source_effect,tables,support,agreement,choose,fixed_pair,identification_ceiling

MODES=('map_without_evidence','support_only','fixed_two','best_fixed_two','first_informative','myopic_two','active_two','full_table_six')


def audit(root):
    root=Path(root)
    def read(name):
        p=root/(name+'.json');require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded evidence')
        return strict_loads(p.read_bytes())
    def ns(v):require(type(v) is int and v>=0,'nonnegative measured CPU');return v
    plan=read('plan');inputs=read('inputs');truth=read('targets');rows=read('outputs');result=read('results')
    require(plan['profile']=='counterfactual_rule_transfer_v1' and plan['modes']==list(MODES) and
        plan['cases']==198 and plan['ordinary_checks']==2 and plan['full_table_checks']==6 and
        plan['check_cost']==.02 and plan['source_actions']=='controlled_reset_v1','fixed experiment design')
    require(len(inputs)==198 and len(rows)==198*len(MODES) and len(truth)==198,'complete denominator')
    totals={m:dict(cases=0,identified=0,checks=0,effects_answered=0,effects_correct=0,
        transfer_predictions=0,transfer_correct=0,unqueried_transfer_predictions=0,controller_cpu_ns=0,build_cpu_ns=0,compile_cpu_ns=0,apply_cpu_ns=0) for m in MODES}
    calls=0;cursor=0;tbl=tables()
    for n,inp in enumerate(inputs):
        rule=n//6;first=n%6;sid=digest(['transfer-case-v1',rule,first,2026101327])
        require(inp['public']==dict(source_id=sid,names=['Mira','Nolan','Orla'],event='Mira, Nolan and Orla execute the registered operation.') and inp['first']==first and truth[sid]==rule,'source inventory/labels')
        order=list(MODES);random.Random(2026101327+n).shuffle(order)
        for mode in order:
            row=rows[cursor];cursor+=1;r=row['result'];t=totals[mode]
            ctx=dict(scope='counterfactual-transfer-research',generation=1,environment=sid)
            binding=digest([inp['public'],ctx]);frame=digest(['verified_role_program_v1','{R0}, {R1} and {R2} execute the registered operation.'])
            pid=digest([plan['profile'],binding,frame,tbl])
            require(row['source_id']==sid and row['first']==first and row['context']==ctx and r['mode']==mode and r['problem_sha256']==pid,'bound trial')
            limit=6 if mode=='full_table_six' else 0 if mode in MODES[:2] else 2
            require(r['checks_limit']==limit and len(r['records'])<=limit,'paid total experiments')
            h=();k=0
            for decision in r['decisions']:
                ids=support(h);agreed=agreement(ids);d=decision['plan']
                if mode in ('fixed_two','best_fixed_two'):s=(fixed_pair() if mode=='best_fixed_two' else (first,(first+1)%6))[k]
                elif mode=='full_table_six':s=k
                elif mode=='first_informative':s=next((i for i,x in enumerate(agreed) if x is None),None)
                else:
                    value,s=choose(h,1 if mode=='myopic_two' else limit-k)
                    require(d is not None and abs(d['value']-float(value))<1e-12 and d['state_index']==s and
                            d['history_sha256']==digest(h) and d['problem_sha256']==pid and 1<=d['nodes']<=20000 and ns(d['cpu_ns'])<=100_000_000,'exact selected experiment')
                require(decision['state_index']==s and decision['history_sha256']==digest(h) and ns(decision['cpu_ns'])<=100_000_000,'decision history/budget')
                if s is None:break
                require(k<len(r['records']),'missing source call');rec=r['records'][k]
                request=dict(problem_sha256=pid,binding=binding,state=list(STATES[s]),sequence=k,history_sha256=digest(h),protocol='controlled_reset_v1')
                require(rec['request']==request and rec['receipt']==dict(request_sha256=digest(request),effect=list(source_effect(rule,STATES[s]))),'selected-only source effect')
                ns(rec['cpu_ns']);h=h+((s,STATES.index(source_effect(rule,STATES[s]))),);k+=1;calls+=1
            require(k==len(r['records']) and r['history']==[list(x) for x in h] and r['support']==list(support(h)) and r['failure'] is None,'full observation history')
            agreed=agreement(support(h));identified=all(x is not None for x in agreed)
            predicted=tbl[support(h)[0]] if mode=='map_without_evidence' else agreed
            require(r['agreed']==list(agreed) and r['predictions']==list(predicted) and r['identified']==identified,'unanimity not guessed identity')
            require(r['family_coverage_authenticated'] is False and r['semantic_certificate'] is False and r['production_promotion_permitted'] is False,'not a semantic or production certificate')
            require(len(row['transfer'])==(36 if identified else 0),'no unresolved table export')
            expected_table=dict(frame=frame,context=digest(dict(binding=binding,**ctx)),effects=list(agreed),evidence=digest([pid,h])) if identified else None
            require(row['table_snapshot']==expected_table,'exported rule does not match all evidence')
            require(len(plan['targets'])==36,'declared transfer domain')
            for j,pred in enumerate(row['transfer']):
                roles=STATES[j//6];state=STATES[j%6];target=plan['targets'][j]
                names=['Ari','Bea','Cora']
                text=', '.join(names[i] for i in roles[:2])+' and '+names[roles[2]]+' execute the registered operation.'
                require(target==dict(event=text,names=names,state=list(state),roles=list(roles)),'whole transfer state/role domain')
                norm=tuple(state[i] for i in roles);effect=source_effect(rule,norm)
                expected=tuple(state[roles[effect[roles.index(i)]]] for i in range(3))
                require(tuple(pred['state'])==expected,'incorrect transferred rule')
                t['apply_cpu_ns']+=ns(pred['cpu_ns']);t['transfer_predictions']+=1;t['transfer_correct']+=1
                t['unqueried_transfer_predictions']+=STATES.index(norm) not in {i for i,_ in h}
            t['cases']+=1;t['identified']+=identified;t['checks']+=k
            for s,p in enumerate(predicted):
                t['effects_answered']+=p is not None;t['effects_correct']+=p is not None and STATES[p]==source_effect(rule,STATES[s])
            t['controller_cpu_ns']+=ns(r['cpu_ns']);t['build_cpu_ns']+=ns(row['build_cpu_ns']);t['compile_cpu_ns']+=ns(row['compile_cpu_ns'])
            require(row['total_cpu_ns']>=r['cpu_ns']+row['build_cpu_ns']+row['compile_cpu_ns']+sum(v['cpu_ns'] for v in row['transfer']),'complete controller envelope')
    require(totals==result['summary'],'reported scores/costs differ')
    require(result['family_coverage_authenticated'] is False and result['new_neural_learning'] is False and result['production_promotion_permitted'] is False,'unsupported report certification')
    require(read('identification-ceiling')==identification_ceiling(),'false identification ceiling')
    return dict(outputs_recomputed=len(rows),source_calls_recomputed=calls,transfer_predictions_recomputed=sum(v['transfer_predictions'] for v in totals.values()),
        source_independence_authenticated=False,family_coverage_authenticated=False,production_promotion_permitted=False)
