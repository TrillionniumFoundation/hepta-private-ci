"""Fixed-weight execution experiment; no new training, threshold tuning or labels.

Compare the existing path with one-time immutable gate preparation. Each arm
executes its own pilot and continuation. All old exact/cheap controls remain.
"""
import hashlib
from pathlib import Path
import random
import statistics
import time
from four_gate_common import digest, require, strict_loads, write_once
from fbsde_depth_data import construct
from fbsde_outcome_data import operation
from fbsde_outcome_policy import ARMS, execute
from fbsde_outcome_audit import audit as audit_source
from fbsde_prepared_gate import PreparedOutcomeGate
from fbsde_prepared_gate_audit import semantic, audit
from fbsde_tracking_records import RecordBuffer

PROFILE='prepared_gate_execution_v1'
ENGINES=('validated_each_call_v1','prepared_gate_v2')
REPEATS=5
SEED=20261013


def run(output,evidence_dir):
    root=Path(output);source=Path(evidence_dir);root.mkdir(parents=True,exist_ok=False)
    start=time.process_time_ns()
    def read(name):
        path=source/(name+'.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<64*1024*1024,'bounded frozen source')
        return strict_loads(path.read_bytes())
    write_once(root/'source-audit.json',audit_source(source))
    base=read('plan');policy=read('policy');parent=read('parent-router');policy_pin=digest(policy)
    originals={arm:read(arm) for arm in ARMS}
    expected={(arm,r['source_id']):digest(semantic(r)) for arm,rows in originals.items() for r in rows}
    inputs={r['source_id']:r for r in read('inputs')}
    priors=[p for p in read('priors') if inputs[p['source_id']]['split'] in ('test','retention')]
    context=dict(model=base['model_sha256'],calibration=base['calibration_sha256'],scope='outcome-depth-research',generation=3)
    write_once(root/'plan.json',{'profile':PROFILE,'engines':ENGINES,'arms':ARMS,'repeats':REPEATS,'seed':SEED,
        'original_outputs_sha256':digest(originals),'unique_cases':len(priors),'context':context,
        'source_code':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('fbsde_prepared_gate*.py')},
        'interleaved_per_case':True,'no_fit_or_selection':True,'original_allocation_cpu_ns':100_000_000,
        'component_cost_not_end_to_end':True,'production_promotion_permitted':False})
    specs={};prepared={};preparation=[]
    for arm in ('numeric_router','model_model','model_outcome','outcome_model','outcome_outcome','confidence_outcome'):
        state=parent['fit']['state'] if arm=='numeric_router' else None if arm=='confidence_outcome' else policy['routers'][arm.split('_')[0]]['state']
        threshold=parent['complete']['selected'] if arm=='numeric_router' else policy['selectors'][arm]['selected']
        specs[arm]=dict(state=state,threshold=threshold)
        before=time.process_time_ns()
        gate=PreparedOutcomeGate(state,threshold,context,kind='confidence' if arm=='confidence_outcome' else 'learned')
        preparation.append({'arm':arm,'identity':gate.identity,'cpu_ns':time.process_time_ns()-before})
        prepared[arm]=gate
    write_once(root/'preparation.json',preparation)
    budget={'used':0,'limit':256*1024*1024};calls=RecordBuffer(budget);full=RecordBuffer(budget)
    totals={arm:{engine:[0]*REPEATS for engine in ENGINES} for arm in ARMS};active={};build_cpu=0
    try:
        for repeat in range(REPEATS):
            order=list(priors);random.Random(SEED+repeat).shuffle(order)
            for index,p in enumerate(order):
                src=inputs[p['source_id']];prior={k:p[k] for k in ('source_id','query','components','weights','keys')}
                before=time.process_time_ns();problem=construct(prior,context['model'],context['calibration'],scope=context['scope'])
                request_context=dict(source=digest(prior),**context);build_cpu+=time.process_time_ns()-before
                def reveal(event):return ((0,1),(0,2),(1,2)).index(operation(src['events'][event],src['names']))
                arms=[(a,e) for a in ARMS for e in ENGINES]
                random.Random(SEED+repeat*10000+index).shuffle(arms)
                for arm,engine in arms:
                    active=dict(repeat=repeat,engine=engine,arm=arm,source_id=src['source_id'])
                    before=time.process_time_ns();wall=time.perf_counter_ns()
                    if arm=='exact_reverse':
                        holder=src['query']
                        for text in reversed(src['events']):
                            a,b=operation(text,src['names']);holder=b if holder==a else a if holder==b else holder
                        result={'arm':arm,'holder':holder,'text':('amber','blue','coral')[holder],
                            'checks':[],'decisions':[],'route':None,'probabilities':[float(j==holder) for j in range(3)],
                            'depth2_requested':False,'cpu_ns':time.process_time_ns()-before,'problem_sha256':problem.identity}
                    else:
                        effective=('two_step' if policy['selectors']['best_fixed']==2 else 'one_step') if arm=='best_fixed' else arm
                        if arm in prepared and engine=='prepared_gate_v2':
                            result=execute(problem,effective,reveal,prepared=prepared[arm],context=request_context)
                        else:
                            bundle=dict(binding=problem.binding,**specs[arm]) if arm in specs else None
                            result=execute(problem,effective,reveal,bundle)
                        result['effective_arm']=effective;result['arm']=arm
                    elapsed=time.process_time_ns()-before;elapsed_wall=time.perf_counter_ns()-wall
                    result.update(source_id=src['source_id'],policy_sha256=policy_pin)
                    fingerprint=digest(semantic(result))
                    require(fingerprint==expected[(arm,src['source_id'])],'prepared execution changed frozen decisions')
                    calls.append({**active,'cpu_ns':elapsed,'wall_ns':elapsed_wall,'reported_cpu_ns':result['cpu_ns'],
                                  'semantic_sha256':fingerprint,'returned':True})
                    totals[arm][engine][repeat]+=elapsed
                    if repeat==0:full.append({**active,'output':result})
    except Exception as error:
        write_once(root/'failure.json',{'active':active,'type':type(error).__name__,'error':str(error),
            'evidence':getattr(error,'evidence',None),'complete':False});raise
    finally:
        write_once(root/'streams.json',{'calls':calls.write_once(root/'calls.json'),
            'first-outputs':full.write_once(root/'first-outputs.json'),'retained_bytes':budget['used']})
    require(digest(policy)==policy_pin,'frozen comparison policy mutated')
    prep_by={r['arm']:r['cpu_ns'] for r in preparation};summary={}
    for arm,costs in totals.items():
        a,b=ENGINES;original=sum(costs[a]);optimized=sum(costs[b])+prep_by.get(arm,0)
        summary[arm]={'raw_repeat_cpu_ns':costs,'median_repeat_cpu_ns':{k:statistics.median(v) for k,v in costs.items()},
            'preparation_cpu_ns':prep_by.get(arm,0),'all_actual_calls_cpu_ns':{a:original,b:optimized},
            'prepared_cpu_reduction_fraction':1-optimized/original,'paired_outputs_per_engine':len(priors)*REPEATS}
    result={'profile':PROFILE,'calls':len(calls),'unique_cases':len(priors),'summary':summary,
        'belief_build_cpu_ns':build_cpu,'cpu_envelope_before_audit_ns':time.process_time_ns()-start,
        'new_semantic_efficacy':False,'new_pretrained_forward':False,'historical_training_costs_not_reexecuted':True,
        'unallocated_common_recording_audit_costs':True,'production_promotion_permitted':False}
    write_once(root/'results.json',result);write_once(root/'audit.json',audit(root,source))
    write_once(root/'completion.json',{'cpu_through_audit_ns':time.process_time_ns()-start,
                                     'excludes_import_startup_final_write':True})
    return result
