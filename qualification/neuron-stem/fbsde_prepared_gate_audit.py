"""Read-only frozen-output/cost pairing; imports no prepared or runtime policy.

First independently validates the source study. A matching semantic fingerprint
establishes arithmetic consistency, not physical execution or source independence.
"""
import math
import random
import statistics
from pathlib import Path
from four_gate_common import digest, require, strict_loads
from fbsde_outcome_audit import audit as audit_source, ARMS


def semantic(row):
    if isinstance(row,dict):return {k:semantic(v) for k,v in row.items() if k!='cpu_ns'}
    if isinstance(row,(list,tuple)):return [semantic(v) for v in row]
    return row


def audit(root, source):
    root,source=Path(root),Path(source)
    def read(directory,name):
        p=directory/(name+'.json')
        require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded paired evidence')
        return strict_loads(p.read_bytes())
    def ns(x):
        require(type(x) is int and x>=0,'nonnegative measured cost');return x
    audit_source(source)
    plan=read(root,'plan');result=read(root,'results');records=read(root,'calls')
    require(plan['profile']=='prepared_gate_execution_v1' and plan['arms']==list(ARMS) and
            plan['engines']==['validated_each_call_v1','prepared_gate_v2'] and
            plan['repeats']==5 and plan['seed']==20261013,'frozen comparison design')
    require(not (root/'failure.json').exists(),'failed execution is not a complete comparison')
    originals={(arm,r['source_id']):r for arm in ARMS for r in read(source,arm)}
    expected_keys=[]
    priors=[p for p in read(source,'priors') if ('one_step',p['source_id']) in originals]
    for repeat in range(5):
        ordered=list(priors);random.Random(plan['seed']+repeat).shuffle(ordered)
        for index,p in enumerate(ordered):
            arms=[(a,e) for a in ARMS for e in plan['engines']]
            random.Random(plan['seed']+repeat*10000+index).shuffle(arms)
            expected_keys.extend((repeat,e,a,p['source_id']) for a,e in arms)
    keys=[(r['repeat'],r['engine'],r['arm'],r['source_id']) for r in records]
    require(len(keys)==len(set(keys)) and keys==expected_keys,'paired execution inventory')
    require(plan['original_outputs_sha256']==digest({a:read(source,a) for a in ARMS}),'source output identity')
    full=read(root,'first-outputs');full_map={(r['engine'],r['arm'],r['source_id']):r['output'] for r in full}
    require(len(full)==len(full_map)==2*len(originals),'first complete trace inventory')
    fingerprints={k:digest(semantic(v)) for k,v in originals.items()}
    for r in records:
        original=originals[(r['arm'],r['source_id'])]
        require(r['semantic_sha256']==fingerprints[(r['arm'],r['source_id'])],'changed action, score, or decoded answer')
        require(r['returned'] is True and ns(r['cpu_ns'])>=ns(r['reported_cpu_ns']) and ns(r['wall_ns'])>=0,
                'unpaid execution')
        if r['repeat']==0:
            output=full_map[(r['engine'],r['arm'],r['source_id'])]
            require(semantic(output)==semantic(original) and output['cpu_ns']==r['reported_cpu_ns'],
                    'first trace differs from source')
            for d in output['decisions']:
                require(ns(d['cpu_ns'])<=100_000_000 and type(d['nodes']) is int and 0<=d['nodes']<=20000,
                        'original allocation limits')
    prep=read(root,'preparation');policy=read(source,'policy');parent=read(source,'parent-router');base=read(source,'plan')
    context=dict(model=base['model_sha256'],calibration=base['calibration_sha256'],scope='outcome-depth-research',generation=3)
    adaptive=('numeric_router','model_model','model_outcome','outcome_model','outcome_outcome','confidence_outcome')
    require({r['arm'] for r in prep}==set(adaptive) and len(prep)==6,'preparation inventory')
    prep_by={}
    for r in prep:
        arm=r['arm'];kind='confidence' if arm=='confidence_outcome' else 'learned'
        state=parent['fit']['state'] if arm=='numeric_router' else None if kind=='confidence' else policy['routers'][arm.split('_')[0]]['state']
        threshold=parent['complete']['selected'] if arm=='numeric_router' else policy['selectors'][arm]['selected']
        require(r['identity']==digest(dict(profile='prepared_gate_v2',kind=kind,context=context,state=state,threshold=threshold)),
                'prepared gate provenance')
        prep_by[arm]=ns(r['cpu_ns'])
    summary={}
    for arm in ARMS:
        costs={engine:[sum(r['cpu_ns'] for r in records if r['arm']==arm and r['engine']==engine and r['repeat']==rep)
                       for rep in range(5)] for engine in plan['engines']}
        a,b=plan['engines'];original=sum(costs[a]);prepared=sum(costs[b])+prep_by.get(arm,0)
        summary[arm]={'raw_repeat_cpu_ns':costs,'median_repeat_cpu_ns':{k:statistics.median(v) for k,v in costs.items()},
            'preparation_cpu_ns':prep_by.get(arm,0),'all_actual_calls_cpu_ns':{a:original,b:prepared},
            'prepared_cpu_reduction_fraction':1-prepared/original,'paired_outputs_per_engine':len(originals)//len(ARMS)*5}
    require(summary==result['summary'],'fabricated cost reduction')
    require(result['calls']==len(records) and result['unique_cases']==len(originals)//len(ARMS),'sample accounting')
    return {'audited_calls':len(records),'full_traces':len(full),'semantic_outputs_unchanged':True,
            'preparation_charged_to_actual_calls':True,'new_accuracy_gain':False,'execution_authenticated':False,
            'production_promotion_permitted':False}
