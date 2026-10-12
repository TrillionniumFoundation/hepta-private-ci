"""Saved-file recomputation without a neural model, runtime planner or executor.

Forward permutation-world probabilities, source-renderer regex and sealed answers
are checked separately. This is NOT independent human verification or admission.
"""
import math
import re
from pathlib import Path
from four_gate_common import digest, require, strict_loads
from fbsde_depth_audit import semantic_logits, vector
from fbsde_tracking_tied_audit import reference
from fbsde_outcome_data import PROFILE, FRAMES, generate

ARMS=('no_checks','one_step','two_step','best_fixed','numeric_router','model_model','model_outcome',
      'outcome_model','outcome_outcome','confidence_outcome','verify_all_unique','exact_reverse')
PAIRS=((0,1),(0,2),(1,2))



def score(weights,x):
    # Recompute the exported scalar-network specification with compensated sums.
    # Ordinary sum shifts exact threshold ties, so no epsilon changes decisions.
    def layer(name,values):
        return [math.fsum(a*b for a,b in zip(row,values))+bias
                for row,bias in zip(weights[name+'.weight'],weights[name+'.bias'])]
    def sigmoid(v):return 1/(1+math.exp(-v)) if v>=0 else math.exp(v)/(1+math.exp(v))
    a,b=layer('value',x),layer('gate',x)
    return sigmoid(layer('out',[math.tanh(u)*sigmoid(v) for u,v in zip(a,b)])[0])



def source_pair(text,names):
    found=set()
    for frames in FRAMES.values():
        for frame in frames:
            pattern=''; seen=set()
            for part in re.split(r'(\{[abc]\})',frame):
                if part.startswith('{'):
                    role=part[1]
                    pattern+=f'(?P={role})' if role in seen else f'(?P<{role}>[A-Z][a-z]+)'
                    seen.add(role)
                else:pattern+=re.escape(part)
            match=re.fullmatch(pattern,text)
            if match and len(set(match.groupdict().values()))==len(match.groupdict()) and set(match.groupdict().values())<=set(names):
                found.add(PAIRS.index(tuple(sorted((names.index(match['a']),names.index(match['b']))))))
    require(len(found)==1,'independent source grammar');return found.pop()


def audit(root):
    root=Path(root)
    def read(name):
        p=root/(name+'.json'); require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded original file')
        return strict_loads(p.read_bytes())
    def close(a,b,msg):require(len(a)==len(b) and all(abs(x-y)<1e-9 for x,y in zip(a,b)),msg)
    plan=read('plan');inputs=read('inputs');snapshot=read('frozen-model');cal=read('frozen-calibration')
    require(plan['profile']==PROFILE and inputs==generate() and plan['arms']==list(ARMS),'design/input inventory')
    require(plan['model_sha256']==digest(snapshot) and plan['calibration_sha256']==digest(cal),'frozen model binding')
    sources={r['source_id']:r for r in inputs}; originals={}
    for sid,src in sources.items():
        ops=[source_pair(t,src['names']) for t in src['events']];holders=list(range(3))
        for op in ops:a,b=PAIRS[op];holders[a],holders[b]=holders[b],holders[a]
        originals[sid]=(ops,holders[src['query']])
    priors=read('priors');pmap={r['source_id']:r for r in priors}
    require(len(priors)==len(pmap)==len(sources) and set(pmap)==set(sources),'prior coverage')
    ps=read('proposals');proposals={(r['source_id'],r['event']):r for r in ps}
    require(len(proposals)==len(ps) and set(proposals)=={(sid,i) for sid,src in sources.items() for i in range(len(src['events']))},'proposal coverage')
    for sid,p in pmap.items():
        src=sources[sid];base={k:p[k] for k in ('source_id','query','components','weights','keys')}
        ctx={'source':digest(base),'model':digest(snapshot),'calibration':digest(cal),'scope':'outcome-depth-research','generation':3}
        require(p['binding']==digest(ctx) and p['problem_sha256']==digest(['input_tied_epistemic_v1',3,src['query'],p['components'],p['weights'],p['keys'],ctx]),'problem identity')
        require(p['weights']==[1/3]*3 and p['keys']==[digest([t,src['names'],digest(snapshot),digest(cal)]) for t in src['events']],'source tying')
        for i,text in enumerate(src['events']):
            r=proposals[(sid,i)];require(r['text_sha256']==digest(text) and r['returned'] is True and 0<=r['cpu_ns']<=100_000_000,'denied or wrong input')
            expected=semantic_logits(snapshot,text,src['names'])
            require(len(r['scores'])==3 and all(max(abs(x-y) for x,y in zip(a,b))<2e-5 for a,b in zip(r['scores'],expected)),'semantic logits')
            for m,s in enumerate(r['scores']):
                logs=[(s[a]+s[b])/cal['selected'] for a,b in PAIRS];top=max(logs);w=[math.exp(x-top) for x in logs]
                close([x/math.fsum(w) for x in w],p['components'][m][i],'conditional law')
    def check_record(r,sid,root_depth):
        p=pmap[sid];ops,truth=originals[sid];state,choose=reference(p['components'],p['weights'],p['keys'],p['query'])
        h=();remaining=2;vi=0; holder=None
        try:
            if r['arm']=='exact_reverse':
                require(r['holder']==truth and not r['checks'] and not r['decisions'],'exact control');holder=truth;dist=[float(i==truth) for i in range(3)]
            else:
                for k,d in enumerate(r['decisions']):
                    require(d['known']==[list(v) for v in h] and 0<=d['cpu_ns']<=100_000_000 and 0<=d['nodes']<=20000,'decision budget/history')
                    observed=state(h)[2];reps=[p['keys'].index(key) for key in dict.fromkeys(p['keys'])]
                    available=[e for g,e in enumerate(reps) if g not in observed]
                    if r['arm']=='verify_all_unique' and available:
                        action=f'verify:{available[0]}';require(d['plan'] is None,'verify-all does not hide a solve')
                    else:
                        depth=0 if r['arm'] in ('no_checks','verify_all_unique') else min(remaining,root_depth if k==0 else 1)
                        value,action=choose(h,depth)
                        require(d['plan']['remaining_checks']==depth and d['action']==action and abs(d['plan']['value']-value)<1e-9,'conditional decision')
                    require(d['action']==action,'source action')
                    if not action.startswith('verify:'):
                        require(k==len(r['decisions'])-1,'work after answer');holder=None if action=='abstain' else int(action.split(':')[1]);break
                    event=int(action.split(':')[1]);v=r['checks'][vi];vi+=1
                    require(v=={'event':event,'outcome':ops[event],'known_before':[list(t) for t in h]},'unselected or altered revelation')
                    h=tuple(sorted(h+((event,ops[event]),)));remaining-=1
                else:raise ValueError('unfinished policy')
                require(vi==len(r['checks']),'extra revelation');dist=state(h)[0]
            require(r['holder']==holder and r['text']==('Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]),'decoded answer')
            close(r['probabilities'],dist,'answer distribution')
            require(r['problem_sha256']==p['problem_sha256'] and type(r['cpu_ns']) is int and r['cpu_ns']>=sum(d['cpu_ns'] for d in r['decisions']),'cost/problem binding')
            return (0 if holder is None else 1 if holder==truth else -1)-.02*len(r['checks'])
        finally:choose.cache_clear();state.cache_clear()
    teachers={s:read('teacher-'+s) for s in ('train','selection')};before=read('teacher-predictions')
    require(len(before)==sum(map(len,teachers.values())),'teacher prediction denominator')
    forecast={r['source_id']:r for r in before}; gaps={}
    for split,rows in teachers.items():
        require({r['source_id'] for r in rows}=={sid for sid,s in sources.items() if s['split']==split},'teacher split leakage')
        for r in rows:
            sid=r['source_id'];p=pmap[sid];require(r['label']==originals[sid][1] and r['prediction_sha256']==digest(forecast[sid]) and forecast[sid]=={k:r[k] for k in ('source_id','shallow','deep')},'pre-outcome prediction identity')
            a=check_record(r['shallow'],sid,1);b=check_record(r['deep'],sid,2)
            require(abs(r['outcome_gain']-(b-a))<1e-10 and abs(r['model_gain']-(r['deep']['decisions'][0]['plan']['value']-r['shallow']['decisions'][0]['plan']['value']))<1e-10,'teacher gains')
            state,choose=reference(p['components'],p['weights'],p['keys'],p['query'])
            close(r['features'],vector(p,state,choose,()),'paid pilot features');choose.cache_clear();state.cache_clear()
        gaps[split]={'rows':len(rows),'model_positive':sum(r['model_gain']>.002 for r in rows),
            'outcome_positive':sum(r['outcome_gain']>.002 for r in rows),'model_positive_outcome_negative':sum(r['model_gain']>.002 and r['outcome_gain']<-.002 for r in rows)}
    policy=read('policy');selectors=policy['selectors'];fits=policy['routers'];rs=teachers['selection']
    for teacher in ('model','outcome'):
        require(fits[teacher]['rows_sha256']==digest(teachers['train']) and fits[teacher]['positive_labels']==sum(r[teacher+'_gain']>.002 for r in teachers['train']),'fit sources/labels')
    require(fits['model']['initial_sha256']==fits['outcome']['initial_sha256'],'same initialization')
    for name,s in selectors.items():
        if name=='best_fixed':
            require(s==(2 if math.fsum(r['outcome_gain']-.002 for r in rs)>0 else 1),'selected fixed depth');continue
        kind=name.split('_')[0];sc=[1-r['features'][0] if kind=='confidence' else score(fits[kind]['state'],r['features']) for r in rs]
        require(s['rows_sha256']==digest(rs) and len(s['grid'])==len(set([0.,1.01,*sc])),'selector inventory')
        for g in s['grid']:
            ds=[v>=g['threshold'] for v in sc];gain=math.fsum((r[s['objective']+'_gain']-.002)*d for r,d in zip(rs,ds))/len(rs)
            require(g['deep']==sum(ds) and abs(gain-g['mean_increment'])<1e-10,'threshold objective')
        require(s['selected']==max(s['grid'],key=lambda g:(g['mean_increment'],-g['deep'],-g['threshold']))['threshold'],'frozen selection')
    targets=read('targets');expected_ids={sid for sid,s in sources.items() if s['split'] in ('test','retention')}
    require(set(targets)==expected_ids and all(v==originals[k][1] for k,v in targets.items()),'evaluation targets')
    result=read('results');total=0;strata={};old=read('parent-router')
    for arm in ARMS:
        records=read(arm);require(len(records)==len(expected_ids) and {r['source_id'] for r in records}==expected_ids,'complete paired arms')
        sums={s:dict(cases=0,correct=0,answered=0,checks=0,escalations=0,utility=0.,cpu_ns=0,nodes=0) for s in ('test','retention')}
        for r in records:
            sid=r['source_id'];p=pmap[sid];depth=2 if arm=='two_step' else selectors['best_fixed'] if arm=='best_fixed' else 1
            if r['route'] is not None:
                route=r['route'];state,choose=reference(p['components'],p['weights'],p['keys'],p['query']);x=vector(p,state,choose,())
                close(x,route['features'],'route observable input');choose.cache_clear();state.cache_clear()
                st=old['fit']['state'] if arm=='numeric_router' else None if arm=='confidence_outcome' else fits[arm.split('_')[0]]['state']
                q=1-x[0] if st is None else score(st,x);threshold=old['complete']['selected'] if arm=='numeric_router' else selectors[arm]['selected']
                require(abs(q-route['score'])<1e-9 and threshold==route['threshold'],'frozen route')
                depth=2 if route['score']>=threshold else 1
                require(route['selected_depth']==depth and route['bundle_sha256']==digest({'binding':p['binding'],'state':st,'threshold':threshold}),'route identity')
            value=check_record(r,sid,depth)
            require(r['depth2_requested']==(arm=='two_step' or arm=='best_fixed' and depth==2 or r['route'] is not None and depth==2),'deep work price')
            require(r['policy_sha256']==digest(policy),'policy changed after test')
            s=sums[sources[sid]['split']];s['cases']+=1;s['correct']+=r['holder']==targets[sid];s['answered']+=r['holder'] is not None
            s['checks']+=len(r['checks']);s['escalations']+=r['depth2_requested'];s['cpu_ns']+=r['cpu_ns'];s['nodes']+=sum(d['nodes'] for d in r['decisions']);total+=1
            group=strata.setdefault(sources[sid]['split']+':'+str(sources[sid]['family']),{}).setdefault(arm,{'cases':0,'correct':0,'checks':0})
            group['cases']+=1;group['correct']+=r['holder']==targets[sid];group['checks']+=len(r['checks'])
        for split,s in sums.items():
            s['utility']=(2*s['correct']-s['answered']-.02*s['checks']-.002*s['escalations'])/s['cases']
            require(s==result['summary'][split][arm],'score or cost sum')
    return {'teacher_diagnostics':gaps,'audited_outputs':total,'strata':strata,'new_test_event_texts':len({t for r in inputs if r['split']=='test' for t in r['events']}),
        'runtime_planner_imported':False,'risk_certified':False,'source_independence_authenticated':False,'production_promotion_permitted':False}
