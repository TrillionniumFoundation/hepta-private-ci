"""Finite-domain transfer experiment. Controlled resets are explicitly NEW source actions."""
from pathlib import Path
from itertools import permutations
import hashlib
import random
import time
from four_gate_common import digest,require,write_once
from fbsde_tracking_records import RecordBuffer
from fbsde_transfer import TransferProblem,TransferTable,execute,MODES,OPS,PROFILE,COST
from fbsde_transfer_reference import RULES,source_effect


def inventory():
    cases=[]
    for rule in range(len(RULES)):
        for first in range(6):
            sid=digest(['transfer-case-v1',rule,first,2026101327])
            public=dict(source_id=sid,names=['Mira','Nolan','Orla'],
                        event='Mira, Nolan and Orla execute the registered operation.')
            cases.append(dict(public=public,first=first,private_rule=rule))
    return cases


def target_requests():
    rows=[];names=['Ari','Bea','Cora']
    for order in permutations(range(3)):
        event=', '.join(names[i] for i in order[:2])+' and '+names[order[2]]+' execute the registered operation.'
        for state in OPS:rows.append(dict(event=event,names=names[:],state=state,roles=order))
    return rows


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);started=time.process_time_ns()
    cases=inventory();targets=target_requests();files=('fbsde_transfer.py','fbsde_transfer_study.py','fbsde_conditional_program.py')
    write_once(output/'plan.json',dict(profile=PROFILE,seed=2026101327,modes=MODES,cases=len(cases),
        source_actions='controlled_reset_v1',ordinary_checks=2,full_table_checks=6,prior='uniform_33_rules',
        terminal_value='fraction_of_6_states_with_unanimous_effect',check_cost=COST,
        old_episode_checks_reused=False,targets=targets,new_semantic_benchmark=False,
        source_sha256={f:hashlib.sha256(Path(__file__).with_name(f).read_bytes()).hexdigest() for f in files},
        production_promotion_permitted=False))
    write_once(output/'inputs.json',[{k:v for k,v in r.items() if k!='private_rule'} for r in cases])
    budget=dict(used=0,limit=256*1024*1024);buffer=RecordBuffer(budget);active={}
    try:
        for n,case in enumerate(cases):
            public=case['public'];context=dict(scope='counterfactual-transfer-research',generation=1,environment=public['source_id'])
            order=list(MODES);random.Random(2026101327+n).shuffle(order)
            for mode in order:
                active=dict(source_id=public['source_id'],mode=mode);start=time.process_time_ns()
                problem=TransferProblem.build(public,context);build=time.process_time_ns()-start
                require(build<=100_000_000,'transfer model construction budget')
                def reveal(request):
                    require(request['binding']==problem.binding and request['protocol']=='controlled_reset_v1','source intervention context')
                    return dict(request_sha256=digest(request),effect=source_effect(case['private_rule'],tuple(request['state'])))
                result=execute(problem,mode,reveal,first_state=case['first'])
                ctx=dict(binding=problem.binding,**context);transfer=[];compile_cpu=0;table_snapshot=None
                if result['identified']:
                    before=time.process_time_ns();table=TransferTable.from_support(problem,tuple(result['history']),ctx)
                    table_snapshot=table.snapshot()
                    table=TransferTable.restore(table_snapshot,problem,tuple(result['history']),ctx)
                    compile_cpu=time.process_time_ns()-before
                    for target in targets:
                        before=time.process_time_ns();state=table.apply(target['event'],target['names'],tuple(target['state']),ctx)
                        transfer.append(dict(state=state,cpu_ns=time.process_time_ns()-before))
                buffer.append(dict(source_id=public['source_id'],first=case['first'],context=context,
                    result=result,build_cpu_ns=build,compile_cpu_ns=compile_cpu,table_snapshot=table_snapshot,transfer=transfer,
                    total_cpu_ns=time.process_time_ns()-start))
    except Exception as error:
        write_once(output/'failure.json',dict(active=active,error=str(error),complete=False));raise
    finally:
        stream=buffer.write_once(output/'outputs.json');write_once(output/'retention.json',dict(stream=stream,bytes=budget['used']))
    # Freeze ALL predictions before exposing private source rule IDs to the scorer.
    write_once(output/'targets.json',{r['public']['source_id']:r['private_rule'] for r in cases})
    results=summarize(list(buffer),targets,{r['public']['source_id']:r['private_rule'] for r in cases})
    write_once(output/'results.json',dict(summary=results,cpu_before_audit_ns=time.process_time_ns()-started,
        family_coverage_authenticated=False,new_neural_learning=False,production_promotion_permitted=False))
    from fbsde_transfer_reference import identification_ceiling
    write_once(output/'identification-ceiling.json',identification_ceiling())
    from fbsde_transfer_audit import audit
    write_once(output/'audit.json',audit(output))
    write_once(output/'completion.json',dict(cpu_through_audit_ns=time.process_time_ns()-started))
    return results


def summarize(rows,targets,private):
    totals={m:dict(cases=0,identified=0,checks=0,effects_answered=0,effects_correct=0,
        transfer_predictions=0,transfer_correct=0,unqueried_transfer_predictions=0,controller_cpu_ns=0,build_cpu_ns=0,
        compile_cpu_ns=0,apply_cpu_ns=0) for m in MODES}
    for row in rows:
        r=row['result'];t=totals[r['mode']];rule=private[row['source_id']]
        t['cases']+=1;t['identified']+=r['identified'];t['checks']+=len(r['records'])
        for i,p in enumerate(r['predictions']):
            t['effects_answered']+=p is not None
            t['effects_correct']+=p is not None and OPS[p]==source_effect(rule,OPS[i])
        for pred,target in zip(row['transfer'],targets):
            roles=target['roles'];state=target['state'];normalized=tuple(state[j] for j in roles)
            op=source_effect(rule,normalized)
            actual=tuple(state[roles[op[roles.index(j)]]] for j in range(3))
            t['transfer_predictions']+=1;t['transfer_correct']+=tuple(pred['state'])==actual
            t['unqueried_transfer_predictions']+=OPS.index(normalized) not in {i for i,_ in r['history']}
            t['apply_cpu_ns']+=pred['cpu_ns']
        t['controller_cpu_ns']+=r['cpu_ns'];t['build_cpu_ns']+=row['build_cpu_ns'];t['compile_cpu_ns']+=row['compile_cpu_ns']
    return totals
