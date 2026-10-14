"""Saved-output arithmetic using an independent full-world reference, not admission.

No Torch, runtime belief object, runtime planner or fitted policy module import.
A matching model value is not correct language, calibrated risk or execution proof.
"""
import math
import re
import hashlib
import struct
from pathlib import Path
from four_gate_common import digest, require, strict_loads
from fbsde_tracking_tied_audit import reference
from fbsde_tracking_feedback_data import task
from fbsde_depth_data import numeric_inputs

MODES = ('no_checks','myopic','full','confidence','frozen','learned','learned_complete','confidence_complete','verify_all_unique','exact_reverse')


def score(weights, x):
    require(len(x)==15 and all(type(v) in (float,int) and math.isfinite(v) for v in x),'finite route features')
    def affine(name, values):
        a,b=weights[name+'.weight'],weights[name+'.bias']
        require(len(a)==len(b) and all(len(r)==len(values) for r in a),'policy tensor dimensions')
        return [sum(u*v for u,v in zip(row,values))+offset for row,offset in zip(a,b)]
    def sigmoid(v): return 1/(1+math.exp(-v)) if v>=0 else math.exp(v)/(1+math.exp(v))
    v,g=affine('value',x),affine('gate',x)
    return sigmoid(affine('out',[math.tanh(a)*sigmoid(b) for a,b in zip(v,g)])[0])


def vector(row, state, choose, h):
    p,posterior,observed=state(h); keys=row['keys']; reps=[keys.index(k) for k in dict.fromkeys(keys)]
    available=[i for g,i in enumerate(reps) if g not in observed]
    laws=[[math.fsum(w*c[i][j] for w,c in zip(posterior,row['components'])) for j in range(3)] for i in available]
    entropy=lambda q:-math.fsum(x*math.log(x) for x in q if x>0)/math.log(3)
    ent=[entropy(q) for q in laws] or [0.]; peaks=[max(q) for q in laws] or [1.]
    stop=max(0.,2*max(p)-1); one=choose(h,1)[0]
    return sorted(p,reverse=True)+[one,stop,one-stop,entropy(p),len(available)/16,
        len(keys)/16,max(ent),math.fsum(ent)/len(ent),max(peaks),min(peaks),len(reps)/len(keys),max(posterior)]


def semantic_logits(snapshot, text, names):
    """Separate scalar reconstruction of the frozen lexical residual pipeline."""
    def sig(v): return 1/(1+math.exp(-v)) if v>=0 else math.exp(v)/(1+math.exp(v))
    def affine(state, key, x):
        return [math.fsum(a*b for a,b in zip(w,x))+v for w,v in zip(state[key+'.weight'],state[key+'.bias'])]
    def f32(x): return struct.unpack('<f',struct.pack('<f',x))[0]
    vectors=[]
    for selected in names:
        normalized=re.sub(r'\b('+'|'.join(map(re.escape,names))+r')\b',
            lambda m:'SELF' if m[0]==selected else 'OTHER',text)
        tokens=re.findall('[a-z]+',normalized.lower()); grams=tokens+[' '.join(t) for t in zip(tokens,tokens[1:])]
        v=[0.]*128
        for token in grams:
            h=hashlib.sha256(token.encode()).digest();v[int.from_bytes(h[:4],'little')%128]+=1 if h[4]&1 else -1
        norm=math.sqrt(sum(x*x for x in v)) or 1;vectors.append([f32(x/norm) for x in v])
    result=[]
    for member in snapshot['base']:
        row=[]
        for x in vectors:
            v,g=affine(member,'value',x),affine(member,'gate',x)
            value=affine(member,'output',[math.tanh(a)*sig(b) for a,b in zip(v,g)])[0]
            residual=math.fsum(a*b for a,b in zip(snapshot['residual']['weight'][0],x))+snapshot['residual']['bias'][0]
            row.append(value+residual)
        result.append(row)
    return result


def audit(root):
    root=Path(root)
    def read(name):
        p=root/(name+'.json')
        require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded original evidence')
        return strict_loads(p.read_bytes())
    def close(a,b,msg):
        require(len(a)==len(b) and all(math.isfinite(x) and math.isfinite(y) and abs(x-y)<1e-9 for x,y in zip(a,b)),msg)
    def ns(x):
        require(type(x) is int and x>=0,'nonnegative CPU');return x
    design=read('plan');router=read('router');result=read('results')
    require(design['profile']==result['profile']=='learned_depth_allocation_v1' and
            design['modes']==list(MODES) and design['teacher_counts']==[256,64,64] and
            design['gain_price']==.002 and design['max_checks']==2 and design['check_cost']==.02 and
            design['cpu_limit_ns']==100_000_000,'frozen design/strong controls')
    engine=design.get('planning_engine','fresh_solve_v1')
    require(engine in ('fresh_solve_v1','shared_continuation_v2') and
            result.get('planning_engine','fresh_solve_v1')==engine,'planning engine identity')
    teachers={s:read('teacher-'+s) for s in ('train','selection','model_test')}
    seen=set();references=0
    for (split,rows),n,seed in zip(teachers.items(),design['teacher_counts'],design['teacher_seeds']):
        require([r['input'] for r in rows]==numeric_inputs(seed,n,split),'preregistered numerical contexts')
        require(len(rows)==n,'teacher denominator')
        for r in rows:
            inp=r['input']; key=digest(inp)
            require(key not in seen,'overlapping teacher input');seen.add(key)
            state,choose=reference(inp['components'],inp['weights'],inp['keys'],inp['query'])
            one,two=choose((),1),choose((),2)
            require(abs(max(0.,two[0]-one[0])-r['gain'])<1e-10,'teacher gain not same model')
            require(r['one']['action']==one[1] and r['two']['action']==two[1],'teacher policy')
            close(r['features'],vector(inp,state,choose,()),'teacher feature leakage/drift');references+=1
    require(router['fit']['training_sha256']==digest(teachers['train']),'router fit source')
    for kind,selection in (('learned',router['selected']),('confidence',router['heuristic']),
                           ('learned',router['complete']),('confidence',router['complete_heuristic'])):
        rows=teachers['selection']; grid=[]
        thresholds=design['thresholds']
        if selection['selection_profile']=='validation_breakpoints_v2':
            points=[score(router['fit']['state'],r['features']) if kind=='learned' else math.nextafter(r['features'][0],math.inf) for r in rows]
            thresholds=sorted(set([0.,1.01,*points]))
        else:require(selection['selection_profile']=='registered_coarse_v1','declared threshold profile')
        for threshold in thresholds:
            ds=[score(router['fit']['state'],r['features'])>=threshold if kind=='learned' else r['features'][0]<threshold for r in rows]
            loss=math.fsum((0. if d else r['gain'])+.002*d for r,d in zip(rows,ds))/len(rows)
            grid.append({'threshold':threshold,'model_regret_plus_price':loss,'deep_calls':sum(ds)})
        require(len(selection['grid'])==len(grid) and all(a['deep_calls']==b['deep_calls'] and abs(a['threshold']-b['threshold'])<1e-12 and abs(a['model_regret_plus_price']-b['model_regret_plus_price'])<1e-12 for a,b in zip(selection['grid'],grid)) and selection['source_sha256']==digest(rows),'selection grid/source')
        require(abs(selection['selected']-min(grid,key=lambda r:(r['model_regret_plus_price'],r['deep_calls'],r['threshold']))['threshold'])<1e-12,
                'post-test policy selection')
    tests=read('model-test');require(len(tests)==len(teachers['model_test']),'model-test count')
    for r,original in zip(tests,teachers['model_test']):
        q=score(router['fit']['state'],original['features']);deep=q>=router['selected']['selected']
        require(r['source_id']==original['input']['source_id'] and abs(q-r['score'])<1e-10 and r['deeper']==deep
                and r['missed_model_value']==(0. if deep else original['gain']),'independent router test')
        require(r['complete_deeper']==(q>=router['complete']['selected']) and r['complete_missed_model_value']==(0. if q>=router['complete']['selected'] else original['gain']), 'complete-grid test')
    sources=read('inputs');targets=read('targets');priors=read('priors')
    require(len(priors)==len(sources)==204 and len({s['source_id'] for s in sources})==204,'complete semantic inventory')
    outputs={m:read(m) for m in MODES}
    require(all(len(v)==204 for v in outputs.values()),'paired mode denominator')
    weights=read('candidate-weights');snapshot=digest(weights);cal=read('calibration');calibration=digest(cal)
    proposals=read('proposals'); event_map={}
    for row in proposals:
        expected=semantic_logits(weights,row['text'],row['names'])
        require(len(row['scores'])==3 and all(len(a)==len(b) and all(abs(x-y)<2e-5 for x,y in zip(a,b)) for a,b in zip(row['scores'],expected)),
                'saved logits differ from serialized residual model')
        if row['phase']=='evaluation':
            key=(row['source_id'],row['event']);require(key not in event_map,'duplicate proposal');event_map[key]=row
    require(set(event_map)=={(r['source_id'],i) for r in sources for i in range(len(r['events']))},'proposal/source coverage')
    def law(scores,t):
        pairs=((0,1),(0,2),(1,2));v=[(scores[a]+scores[b])/t for a,b in pairs];top=max(v);mass=[math.exp(x-top) for x in v]
        return [x/math.fsum(mass) for x in mass]
    cal_grid=[]
    pairs=((0,1),(0,2),(1,2))
    for t in (.25,.5,1.,2.,4.):
        ps=[math.fsum(law(s,t)[pairs.index(tuple(r['pair']))] for s in r['scores'])/3 for r in cal['rows']]
        cal_grid.append({'temperature':t,'nll':-math.fsum(math.log(max(x,1e-300)) for x in ps)/len(ps)})
    require(cal_grid==cal['grid'] and min(cal_grid,key=lambda r:(r['nll'],r['temperature']))['temperature']==cal['selected'],'calibration selection')
    totals={s:{m:dict(cases=0,correct=0,answered=0,checks=0,utility=0.,cpu_ns=0,depth2_calls=0,planner_nodes=0) for m in MODES}
            for s in ('known_replay','heldout')}; routes_checked=0
    for index,(source,p) in enumerate(zip(sources,priors)):
        sid=source['source_id']; require(p['source_id']==sid and p['model']==snapshot and p['calibration']==calibration,'current model identity')
        require(p['weights']==[1/3]*3 and p['keys']==[digest([text,source['names'],snapshot,calibration]) for text in source['events']], 'input tying identity')
        for i,text in enumerate(source['events']):
            row=event_map[(sid,i)];require(row['text']==text and row['names']==source['names'],'source feature drift')
            for m,scores in enumerate(row['scores']):close(law(scores,cal['selected']),p['components'][m][i],'belief/Head mismatch')
        t=task(source); truth=[]; actual=list(range(3));pairs=[(0,1),(0,2),(1,2)]
        for event in t['events']:
            a,b=event['pair'];truth.append(pairs.index((a,b)));actual[a],actual[b]=actual[b],actual[a]
        require(actual[source['query']]==targets[sid],'original source label')
        bundle=p['bundle']
        base={k:p[k] for k in ('source_id','query','components','weights','keys')}
        require(bundle['context']=={'source':digest(base),'model':snapshot,'calibration':calibration,'scope':'depth-research','generation':3}
            and digest(bundle['context'])==bundle['problem_binding'],'router context binding')
        require(bundle['state']==router['fit']['state'] and bundle['initial']==router['fit']['initial']
            and bundle['threshold']==router['selected']['selected'] and
            bundle['confidence_threshold']==router['heuristic']['selected'] and bundle['complete_threshold']==router['complete']['selected'] and bundle['complete_confidence_threshold']==router['complete_heuristic']['selected'],'unchanged selected policy')
        state,choose=reference(p['components'],p['weights'],p['keys'],source['query'])
        for mode,allrows in outputs.items():
            r=allrows[index];require(r['source_id']==sid and r['mode']==mode and r['problem_sha256']==p['problem_sha256'],'paired source mode')
            h=();remaining=2;ri=di=vi=0
            if mode=='exact_reverse':
                holder=actual[source['query']];dist=[float(j==holder) for j in range(3)]
                require(not r['routes'] and not r['decisions'] and not r['verifications'],'free exact control')
            else:
                for _ in range(len(truth)+1):
                    observed=state(h)[2];reps=[p['keys'].index(k) for k in dict.fromkeys(p['keys'])]
                    available=[i for g,i in enumerate(reps) if g not in observed]
                    if mode=='verify_all_unique' and available:action=f'verify:{available[0]}'
                    else:
                        depth=0 if mode in ('no_checks','verify_all_unique') else min(remaining,1 if mode=='myopic' else 2)
                        if mode not in ('no_checks','verify_all_unique'):
                            route=r['routes'][ri];ri+=1;routes_checked+=1
                            require(route['remaining']==remaining and route['known']==[list(x) for x in h]
                                and route['mode']==mode and route['returned'] is True and ns(route['cpu_ns'])<=100_000_000
                                and route['bundle_sha256']==digest(bundle),'paid current routing')
                            require(ns(route['planner_cpu_ns'])<=route['cpu_ns'],'unpaid planner work')
                            require(route.get('planning_engine','fresh_solve_v1')==engine,'route engine drift')
                            if engine=='shared_continuation_v2':
                                scratch=route['workspace']
                                require(set(scratch)=={'new_value_nodes','value_cache_hits','conditional_state_hits',
                                    'conditional_outcome_hits','retained_value_rows','retained_state_rows',
                                    'retained_outcome_rows','closed'} and scratch['closed'] is True,
                                    'complete closed decision workspace')
                                for key in set(scratch)-{'closed'}: ns(scratch[key])
                                require(scratch['new_value_nodes']==route['planner_nodes'] and
                                    all(scratch[k]==0 for k in ('retained_value_rows','retained_state_rows','retained_outcome_rows')),
                                    'retained scratch or unpaid new nodes')
                            else: require(route.get('workspace') is None,'fresh solve cannot claim reused work')
                            require(type(route['planner_nodes']) is int and 1<=route['planner_nodes']<=20000
                                and type(route['one_step_nodes']) is int and 0<=route['one_step_nodes']<=route['planner_nodes'],'combined node budget')
                            if remaining==2 and mode!='full':
                                x=vector(p,state,choose,h);close(x,route['features'],'runtime route features')
                                q=score(bundle['initial' if mode=='frozen' else 'state'],x) if mode in ('learned','frozen','learned_complete') else None
                                deep=(q>=(bundle['complete_threshold'] if mode=='learned_complete' else bundle['threshold'] if mode=='learned' else .5) if q is not None else
                                      x[0]<(bundle['complete_confidence_threshold'] if mode=='confidence_complete' else bundle['confidence_threshold']) if mode in ('confidence','confidence_complete') else False)
                                depth=2 if deep else 1
                                require(route['probability'] is None if q is None else abs(q-route['probability'])<1e-10,'route probability')
                                require(ns(route['one_step_cpu_ns'])>0,'pilot planner cannot be free')
                            else:require(route['features'] is None and route['probability'] is None,'unused features')
                            require(route['selected_depth']==depth,'depth differs from frozen routing')
                        value,action=choose(h,depth);d=r['decisions'][di];di+=1
                        require(d['action']==action and abs(d['value']-value)<1e-9,'chosen-horizon policy mismatch')
                    if not action.startswith('verify:'):
                        holder=None if action=='abstain' else int(action.split(':')[1]);break
                    event=int(action.split(':')[1]);v=r['verifications'][vi];vi+=1
                    require(event in available and (mode=='verify_all_unique' or remaining>0) and v['event']==event
                        and v['outcome']==truth[event] and v['source_event_sha256']==digest(source['events'][event])
                        and v['known_before']==[list(x) for x in h] and v['modeled_cost']==.02,'selected source revelation')
                    h=tuple(sorted(h+((event,truth[event]),)));remaining-=1
                else:raise ValueError('unfinished policy')
                dist=state(h)[0]
                require((ri,di,vi)==(len(r['routes']),len(r['decisions']),len(r['verifications'])),'ghost or missing work')
            text='Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]
            require((r['holder'],r['text'])==(holder,text),'decoded answer mismatch');close(dist,r['probabilities'],'terminal belief')
            require(ns(r['cpu_ns'])>=sum(q['cpu_ns'] for q in r['routes']),'controller envelope hides router cost')
            total=totals[source['split']][mode];total['cases']+=1;total['correct']+=holder==targets[sid]
            total['answered']+=holder is not None;total['checks']+=len(r['verifications']);total['cpu_ns']+=r['cpu_ns']
            total['depth2_calls']+=sum(q['selected_depth']==2 for q in r['routes'])
            total['planner_nodes']+=sum(q['planner_nodes'] for q in r['routes']) if r['routes'] else sum(d['nodes'] for d in r['decisions'])
    for group in totals.values():
        for x in group.values():x['utility']=(2*x['correct']-x['answered']-.02*x['checks'])/x['cases']
    require(totals==result['summary'],'fabricated score/cost totals')
    proposals=read('proposals')
    require(all(r['returned'] is True and ns(r['cpu_ns'])<=100_000_000 for r in proposals),'denied input used')
    require(sum(r['cpu_ns'] for r in proposals)==result['shared_proposal_cpu_ns'],'unpaid shared proposals')
    return {'teacher_contexts_recomputed':references,'semantic_outputs_recomputed':204*len(MODES),
        'routing_records_recomputed':routes_checked,'risk_certified':False,'physical_execution_authenticated':False,
        'semantic_probability_model_assumed':True,'production_promotion_permitted':False}
