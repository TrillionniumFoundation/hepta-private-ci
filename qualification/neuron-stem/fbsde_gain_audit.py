"""Saved-file gain audit; imports neither Torch nor runtime planner/executor.

Original teachers are audited first. New worlds are propagated by the existing
independent reference. No PASS field grants risk or model promotion authority.
"""
from itertools import permutations
import hashlib
import math
from pathlib import Path
from four_gate_common import digest, require, strict_loads
from fbsde_outcome_audit import audit as audit_source, score, source_pair as old_pair
from fbsde_depth_audit import semantic_logits, vector
from fbsde_tracking_tied_audit import reference
from fbsde_gain_data import FRAMES, PROFILE, generate

PAIRS=((0,1),(0,2),(1,2))
ARMS=('no_checks','one_step','two_step','best_fixed','numeric_router','model_model','model_outcome',
    'outcome_model','outcome_outcome','confidence_outcome','verify_all_unique','exact_reverse',
    'frequency_half','frequency_selected','signed_half','signed_selected')


def audit(root, source):
    root=Path(root);source=Path(source);audit_source(source)
    def load(where,name):
        path=where/(name+'.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<64*1024*1024,'bounded evidence file')
        return strict_loads(path.read_bytes())
    def read(n):return load(root,n)
    def old(n):return load(source,n)
    def ns(x):
        require(type(x) is int and x>=0,'nonnegative CPU');return x
    def close(a,b):
        require(len(a)==len(b) and all(math.isfinite(x) and math.isfinite(y) and abs(x-y)<1e-9 for x,y in zip(a,b)),
                'probability or feature mismatch')
    p=read('plan');rows=read('inputs');policy=read('policy');result=read('results')
    require(not (root/'failure.json').exists(),'failed study cannot pass complete audit')
    require(p['profile']==result['profile']==PROFILE and rows==generate(old('inputs')) and p['arms']==list(ARMS),
            'frozen design and complete input inventory')
    require(p['price']==.002 and p['verification_price']==.02 and p['max_checks']==2 and
            p['cpu_ns_limit']==100_000_000 and p['max_nodes']==20000,'unchanged budgets/prices')
    for name,h in p['parent_files'].items():
        require(hashlib.sha256((source/(name+'.json')).read_bytes()).hexdigest()==h,'parent source bytes changed')
    snapshot=old('frozen-model');cal=old('frozen-calibration');parent=old('policy');numeric=old('parent-router')
    require(p['model_sha256']==digest(snapshot) and p['calibration_sha256']==digest(cal) and
            policy['parent_policy_sha256']==digest(parent),'immutable source models')
    training=old('teacher-train');selection=old('teacher-selection');specs={}
    for objective,f in policy['fits'].items():
        require(objective in ('frequency_v1','signed_gain_v2') and f['objective']==objective and
            f['parameters']==265 and f['steps']==160 and len(f['losses'])==160 and
            f['rows_sha256']==digest(training),'training identity or budget')
        net=[r['outcome_gain']-.002 for r in training]
        weights=[1. if objective=='frequency_v1' else abs(d) for d in net]
        require(abs(f['weight_sum']-math.fsum(weights))<1e-4 and f['positive_labels']==sum(d>0 for d in net),
                'signed gain weight or label drift')
        require(all(math.isfinite(v) for v in f['losses']) and ns(f['cpu_ns'])<=15_000_000_000,'finite paid fit')
        scores=[score(f['state'],r['features']) for r in selection];grid=[]
        for threshold in sorted(set([0.,1.01,*scores])):
            ds=[s>=threshold for s in scores]
            grid.append({'threshold':threshold,'deep':sum(ds),
                'mean_increment':math.fsum((r['outcome_gain']-.002)*d for r,d in zip(selection,ds))/len(selection)})
        s=policy['selectors'][objective]
        require(s['grid']==grid and s['rows_sha256']==digest(selection) and s['objective']=='outcome' and
            s['selected']==max(grid,key=lambda g:(g['mean_increment'],-g['deep'],-g['threshold']))['threshold'],
            'post-test threshold or changed gain objective')
        prefix='frequency' if objective=='frequency_v1' else 'signed'
        for suffix,t in (('half',.5),('selected',s['selected'])):specs[prefix+'_'+suffix]=(f['state'],t)
    require(set(policy['fits'])=={'frequency_v1','signed_gain_v2'} and
        len({v['initial_sha256'] for v in policy['fits'].values()})==1,'matched two-loss initialization')
    for arm in ARMS:
        if arm in specs or arm in ('no_checks','one_step','two_step','best_fixed','verify_all_unique','exact_reverse'):continue
        specs[arm]=(numeric['fit']['state'],numeric['complete']['selected']) if arm=='numeric_router' else (
            None if arm=='confidence_outcome' else parent['routers'][arm.split('_')[0]]['state'],parent['selectors'][arm]['selected'])
    sources={r['source_id']:r for r in rows};priors=read('priors');pmap={r['source_id']:r for r in priors}
    require(len(priors)==len(pmap)==len(rows) and set(pmap)==set(sources),'paired priors')
    proposals=read('proposals');pm={(r['source_id'],r['event']):r for r in proposals}
    require(len(pm)==len(proposals) and set(pm)=={(r['source_id'],i) for r in rows for i in range(len(r['events']))},'proposal coverage')
    truths={};operations={}
    for src in rows:
        sid=src['source_id'];ops=[]
        for i,text in enumerate(src['events']):
            matches={tuple(sorted((a,b))) for a,b,c in permutations(range(3)) for frame in FRAMES
                if frame.format(a=src['names'][a],b=src['names'][b],c=src['names'][c])==text}
            require(len(matches)<=1,'ambiguous source')
            ops.append(PAIRS.index(matches.pop()) if matches else old_pair(text,src['names']))
            r=pm[(sid,i)];require(r['text_sha256']==digest(text) and r['returned'] is True and ns(r['cpu_ns'])<=100_000_000,'denied proposal used')
            expected=semantic_logits(snapshot,text,src['names'])
            require(len(r['scores'])==3 and all(len(a)==len(b) and max(abs(x-y) for x,y in zip(a,b))<2e-5 for a,b in zip(r['scores'],expected)),'source semantic parameters changed')
            for m,s in enumerate(r['scores']):
                q=[(s[a]+s[b])/cal['selected'] for a,b in PAIRS];top=max(q);w=[math.exp(v-top) for v in q]
                close([v/math.fsum(w) for v in w],pmap[sid]['components'][m][i])
        state=list(range(3))
        for op in ops:a,b=PAIRS[op];state[a],state[b]=state[b],state[a]
        truths[sid]=state[src['query']];operations[sid]=ops
        prior=pmap[sid];base={k:prior[k] for k in ('source_id','query','components','weights','keys')}
        ctx=dict(source=digest(base),model=digest(snapshot),calibration=digest(cal),scope='signed-gain-routing',generation=3)
        require(prior['weights']==[1/3]*3 and prior['query']==src['query'] and
            prior['keys']==[digest([t,src['names'],digest(snapshot),digest(cal)]) for t in src['events']],'complete source tying')
        require(prior['binding']==digest(ctx) and prior['problem_sha256']==digest(['input_tied_epistemic_v1',3,src['query'],
            prior['components'],prior['weights'],prior['keys'],ctx]),'problem or scope identity')
    require(read('targets')==truths,'final labels')
    count=0;strata={}
    for arm in ARMS:
        records=read(arm);require(len(records)==len(rows) and [r['source_id'] for r in records]==[r['source_id'] for r in rows],'complete ordered arm')
        sums={s:dict(cases=0,correct=0,answered=0,checks=0,deep=0,utility=0.,cpu_ns=0,nodes=0) for s in ('test','retention')}
        for r in records:
            sid=r['source_id'];src=sources[sid];prior=pmap[sid];ops=operations[sid]
            state,choose=reference(prior['components'],prior['weights'],prior['keys'],src['query'])
            h=();remaining=2;used=0;depth=2 if arm=='two_step' else parent['selectors']['best_fixed'] if arm=='best_fixed' else 1
            try:
                require(r['arm']==arm and r['policy_sha256']==digest(policy) and r['problem_sha256']==prior['problem_sha256'],'output identity')
                if arm in specs:
                    route=r['route'];x=vector(prior,state,choose,());close(x,route['features'])
                    st,t=specs[arm];q=1-route['features'][0] if st is None else score(st,route['features'])
                    require(q==route['score'] and t==route['threshold'] and
                        route['bundle_sha256']==digest(dict(binding=prior['binding'],state=st,threshold=t)), 'current gain route')
                    depth=2 if q>=t else 1;require(route['selected_depth']==depth,'threshold predicate')
                else:require(r['route'] is None,'unexpected learned route')
                if arm=='exact_reverse':
                    holder=truths[sid];dist=[float(i==holder) for i in range(3)]
                    require(not r['checks'] and not r['decisions'],'free exact control')
                else:
                    for k,d in enumerate(r['decisions']):
                        require(d['known']==[list(v) for v in h] and ns(d['cpu_ns'])<=100_000_000 and 0<=d['nodes']<=20000,'decision budget/history')
                        reps=[prior['keys'].index(v) for v in dict.fromkeys(prior['keys'])];observed=state(h)[2]
                        available=[e for g,e in enumerate(reps) if g not in observed]
                        if arm=='verify_all_unique' and available:
                            action=f'verify:{available[0]}';require(d['plan'] is None,'verify-all not a hidden planner')
                        else:
                            horizon=0 if arm in ('no_checks','verify_all_unique') else min(remaining,depth if k==0 else 1)
                            value,action=choose(h,horizon)
                            require(d['plan']['remaining_checks']==horizon and abs(d['plan']['value']-value)<1e-9,'original finite objective')
                        require(d['action']==action,'nonanticipative action')
                        if not action.startswith('verify:'):
                            require(k==len(r['decisions'])-1,'work after answer');holder=None if action=='abstain' else int(action.split(':')[1]);break
                        event=int(action.split(':')[1]);require(event in available and (arm=='verify_all_unique' or remaining>0),'verification allowance')
                        require(r['checks'][used]==dict(event=event,outcome=ops[event],known_before=[list(v) for v in h]),'selected revelation')
                        used+=1;remaining-=1;h=tuple(sorted(h+((event,ops[event]),)))
                    else:raise ValueError('unfinished policy')
                    require(used==len(r['checks']),'extra revelation');dist=state(h)[0]
                require(r['holder']==holder and r['text']==('Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]),'decoded answer')
                close(dist,r['probabilities']);require(ns(r['cpu_ns'])>=sum(d['cpu_ns'] for d in r['decisions']),'unpaid decisions')
                require(r['depth2_requested']==(arm=='two_step' or arm=='best_fixed' and depth==2 or arm in specs and depth==2),'deep charge')
                s=sums[src['split']];s['cases']+=1;s['correct']+=holder==truths[sid];s['answered']+=holder is not None
                s['checks']+=used;s['deep']+=r['depth2_requested'];s['cpu_ns']+=r['cpu_ns'];s['nodes']+=sum(d['nodes'] for d in r['decisions'])
                key=f"{src['split']}:{src['family']}";ss=strata.setdefault(key,{}).setdefault(arm,dict(cases=0,correct=0,checks=0))
                ss['cases']+=1;ss['correct']+=holder==truths[sid];ss['checks']+=used;count+=1
            finally:choose.cache_clear();state.cache_clear()
        for split,s in sums.items():
            s['utility']=(2*s['correct']-s['answered']-.02*s['checks']-.002*s['deep'])/s['cases']
            require(s==result['summary'][split][arm],'fabricated result or cost totals')
    preparation=read('preparation')
    require(len(preparation)==len(specs) and {v['arm'] for v in preparation}==set(specs),'prepared policy inventory')
    for item in preparation:
        st,t=specs[item['arm']]
        ctx=dict(model=digest(snapshot),calibration=digest(cal),scope='signed-gain-routing',generation=3)
        require(item['identity']==digest(dict(profile='prepared_gate_v2',kind='confidence' if st is None else 'learned',
            context=ctx,state=st,threshold=t)),'prepared model identity')
    a=read('one_step');b=read('two_step');test=[(x,y) for x,y in zip(a,b) if sources[x['source_id']]['split']=='test']
    headroom={'one_step_correct':sum(x['holder']==truths[x['source_id']] for x,y in test),
        'best_of_these_two_correct':sum(x['holder']==truths[x['source_id']] or y['holder']==truths[y['source_id']] for x,y in test),
        'two_step_corrects_one_step':sum(x['holder']!=truths[x['source_id']] and y['holder']==truths[y['source_id']] for x,y in test),
        'two_step_harms_one_step':sum(x['holder']==truths[x['source_id']] and y['holder']!=truths[y['source_id']] for x,y in test),
        'same_final_answer':sum(x['holder']==y['holder'] for x,y in test),
        'posthoc_diagnostic_not_a_deployed_oracle':True}
    require(result['proposal_cpu_ns']==sum(ns(r['cpu_ns']) for r in proposals),'shared proposal bill')
    require(result['preparation_cpu_ns']==sum(ns(r['cpu_ns']) for r in read('preparation')),'preparation bill')
    return {'outputs_recomputed':count,'fixed_continuation_headroom':headroom,'strata':strata,'test_unique_texts':len({t for r in rows if r['split']=='test' for t in r['events']}),
        'new_frames_generated_not_human':True,'source_independence_authenticated':False,'production_promotion_permitted':False}
