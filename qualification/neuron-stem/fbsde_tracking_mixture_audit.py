"""Read-only original-file recomputation; no planner or neural-model import.

Uses forward holder matrices and a fixed common model posterior. A numerical
check is not a source-independence, calibration, execution or language certificate.
"""
from functools import lru_cache
from itertools import combinations
import hashlib
import math
from pathlib import Path
from four_gate_common import digest, require, strict_loads
from fbsde_tracking import parse, slot_text, generated_cases
from fbsde_tracking_audit import reference
from fbsde_tracking_features import audit_features


def conditional_reference(components, weights, actors, query):
    """Returns an independent forward evaluator with a per-case bounded cache."""
    pairs=list(combinations(range(actors),2));seen=0
    @lru_cache(maxsize=40000)
    def state(h):
        nonlocal seen
        seen+=1;require(seen<=40000,'audit state budget')
        logs=[]
        for w,rows in zip(weights,components):
            values=[rows[i][j] for i,j in h]
            logs.append(math.log(w)+sum(math.log(v) for v in values)
                        if w>0 and all(v>0 for v in values) else -math.inf)
        maximum=max(logs);require(math.isfinite(maximum),'zero joint support')
        likelihood=[math.exp(v-maximum) for v in logs];z=math.fsum(likelihood)
        posterior=[v/z for v in likelihood];answer=[0.]*actors;known=dict(h)
        for mw,rows in zip(posterior,components):
            if mw==0:continue
            matrix=[[float(i==j) for j in range(actors)] for i in range(actors)]
            for event,law in enumerate(rows):
                if event in known:
                    a,b=pairs[known[event]];matrix[a],matrix[b]=matrix[b],matrix[a]
                else:
                    after=[[0.]*actors for _ in range(actors)]
                    for q,(a,b) in zip(law,pairs):
                        if q:
                            for i in range(actors):
                                source=b if i==a else a if i==b else i
                                for j in range(actors):after[i][j]+=q*matrix[source][j]
                    matrix=after
            for j,v in enumerate(matrix[query]):answer[j]+=mw*v
        return answer,posterior
    def outcomes(h,event):
        posterior=state(h)[1]
        return [math.fsum(w*rows[event][j] for w,rows in zip(posterior,components)) for j in range(len(pairs))]
    @lru_cache(maxsize=40000)
    def choose(h,depth,cost):
        probabilities=state(h)[0];label=max(range(actors),key=lambda j:(probabilities[j],-j))
        best=max(0.,2*probabilities[label]-1);action='abstain' if best==0 else f'answer:{label}'
        if depth and best < 1-cost-1e-12:
            for i in range(len(components[0])):
                if i in dict(h):continue
                value=math.fsum(p*choose(tuple(sorted(h+((i,j),))),depth-1,cost)[0]
                               for j,p in enumerate(outcomes(h,i)) if p>0)-cost
                if value>best+1e-12:best,action=value,f'verify:{i}'
        return best,action
    return state,choose


def audit(directory):
    root=Path(directory)
    def read(name):
        path=root/('mixture-'+name+'.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<64*1024*1024,'bounded mixture evidence')
        return strict_loads(path.read_bytes())
    def close(a,b,message):
        require(len(a)==len(b) and all(math.isfinite(x) and math.isfinite(y) and abs(x-y)<1e-10 for x,y in zip(a,b)),message)
    design,fit,cal=read('plan'),read('fit'),read('calibration')
    sources,targets,result=read('inputs'),read('targets'),read('results')
    require(design['profile']=='shared_head_mixture_v2' and design['member_weights']==[1/3]*3,'registered mixture profile')
    expected={'single_no_checks':['single','posterior_no_checks'],'single_ndu':['single','ndu_two_step'],
        'pooled_no_checks':['pooled','posterior_no_checks'],'pooled_ndu':['pooled','ndu_two_step'],
        'joint_no_checks':['joint','posterior_no_checks'],'joint_myopic':['joint','myopic_verify'],
        'joint_ndu':['joint','ndu_two_step'],'verify_all':['joint','verify_all'],'exact_reverse':['pooled','exact_reverse']}
    require(design['arms']==expected and design['max_checks']==2 and design['cost_per_check']==.02
            and design['cpu_limit_ns']==100_000_000,'unchanged controls and limits')
    require(len(fit['members'])==3 and fit['members']==cal['members']==result['members']
            and fit['members'][0]==design['parent_gate_sha256'],'member identity')
    path=root/'mixture-gates.pt';require(path.is_file() and not path.is_symlink() and path.stat().st_size<1_000_000,'bounded tiny weights')
    require(hashlib.sha256(path.read_bytes()).hexdigest()==fit['weights_file_sha256'],'weights file identity')
    proposals=read('proposals');cal_proposals=[r for r in proposals if r['split']=='calibration']
    cal_tasks={r['source_id']:parse(r['input']) for r in generated_cases(seed=design['calibration_seed'],count=72)}
    require(len(cal['rows'])==len(cal_proposals)==360,'calibration inventory')
    for original,p in zip(cal['rows'],cal_proposals):
        task=cal_tasks[p['source_id']];event=task['events'][p['event_index']]
        require(original['scores']==p['scores'] and original['pair']==list(event['pair']),'calibration source/label')
    temps=[]
    for member,temperature in enumerate(cal['temperatures']):
        values=[];raw=[{'scores':r['scores'][member],'pair':r['pair']} for r in cal['rows']]
        for t in design['temperature_grid']:
            total=0.
            for row in raw:
                pairs=list(combinations(range(len(row['scores'])),2));s=row['scores']
                logits=[(s[a]+s[b])/t for a,b in pairs];peak=max(range(len(logits)),key=logits.__getitem__)
                total+=logits[peak]-logits[pairs.index(tuple(sorted(row['pair'])))]+math.log1p(
                    math.fsum(math.exp(v-logits[peak]) for j,v in enumerate(logits) if j!=peak))
            values.append((total/len(raw),t))
        require(min(values)[1]==temperature['selected'] and temperature['input_sha256']==digest(raw),'temperature selection')
        temps.append(temperature['selected'])
    tasks={r['source_id']:parse(r['input']) for r in sources};inputs={r['source_id']:r['input'] for r in sources}
    require(len(tasks)==len(sources) and set(tasks)==set(targets),'complete source denominator')
    raw_priors=read('priors');priors={r['source_id']:r for r in raw_priors}
    ev=[r for r in proposals if r['split']=='evaluation'];events={(r['source_id'],r['event_index']):r for r in ev}
    require(len(priors)==len(raw_priors)==len(tasks) and set(priors)==set(tasks),'prior inventory')
    require(len(events)==len(ev) and set(events)=={(sid,i) for sid,t in tasks.items() for i in range(len(t['events']))},'event inventory')
    for row in proposals:
        require(row['returned'] is True and type(row['cpu_ns']) is int and 0<=row['cpu_ns']<=100_000_000,'proposal budget')
    for sid,task in tasks.items():
        prior=priors[sid];n=len(task['names']);pairs=list(combinations(range(n),2))
        require(prior['binding']=={'source':digest(inputs[sid]),'model':digest(fit['members']),
            'calibration':digest(cal['temperatures']),'scope':'tracking-mixture-research','generation':1},'source/member binding')
        require(prior['weights']==design['member_weights'] and len(prior['components'])==3,'common prior reset')
        for i,event in enumerate(task['events']):
            p=events[(sid,i)]
            require(p['source_slot_texts']==[slot_text(event['text'],task['names'],j) for j in range(n)],'original event input')
            require(len(p['scores'])==3,'three actual member proposals')
            for m,s in enumerate(p['scores']):
                require(len(s)==n and all(type(v) is float and math.isfinite(v) for v in s),'finite actual logits')
                logits=[(s[a]+s[b])/temps[m] for a,b in pairs];top=max(logits);w=[math.exp(v-top) for v in logits]
                close([v/math.fsum(w) for v in w],prior['components'][m][i],'member law not calibrated logits')
        pooled=[[math.fsum(w*comp[i][j] for w,comp in zip(prior['weights'],prior['components'])) for j in range(len(pairs))]
                for i in range(len(task['events']))]
        prior['_pooled']=pooled
        expected_ids={'joint':digest([design['profile'],n,task['query'],prior['components'],prior['weights'],prior['binding']]),
                      'single':digest([n,task['query'],prior['components'][0],prior['binding']]),
                      'pooled':digest([n,task['query'],pooled,prior['binding']])}
        require(prior['problem_ids']==expected_ids,'belief identity')
        require(reference(inputs[sid])==targets[sid],'publisher target mismatch')
    total=0;cost=design['cost_per_check']
    for arm,(kind,policy) in expected.items():
        rows=read(arm);require(len(rows)==len(tasks) and {r['source_id'] for r in rows}==set(tasks),'paired complete arms')
        correct=answered=checks=cpu=0
        for row in rows:
            sid=row['source_id'];task=tasks[sid];p=priors[sid];n=len(task['names']);pairs=list(combinations(range(n),2))
            comps=p['components'] if kind=='joint' else [p['_pooled'] if kind=='pooled' else p['components'][0]]
            weights=p['weights'] if kind=='joint' else [1.]
            state,choose=conditional_reference(comps,weights,n,task['query']);h=();remaining=2;di=0
            member_history=[state(h)[1]] if kind=='joint' else None
            for event in row['verifications']:
                if policy=='verify_all':i=next(j for j in range(len(comps[0])) if j not in dict(h))
                else:
                    depth=min(remaining,1 if policy=='myopic_verify' else 2)
                    require(policy in ('myopic_verify','ndu_two_step') and remaining>0,'unpermitted check')
                    value,action=choose(h,depth,cost);d=row['decisions'][di];di+=1
                    require(action==d['action'] and abs(value-d['value'])<1e-10,'conditional plan decision')
                    i=int(action.split(':')[1]) if action.startswith('verify:') else -1
                require(i>=0 and event['event']==i and event['known_before']==[list(r) for r in h]
                    and event['source_event_sha256']==digest(task['events'][i]['text'])
                    and event['pair_index']==pairs.index(tuple(sorted(task['events'][i]['pair'])))
                    and event['modeled_cost']==cost,'selected revelation only')
                h=tuple(sorted(h+((i,event['pair_index']),)));remaining-=1
                if kind=='joint':member_history.append(state(h)[1])
            if policy=='exact_reverse':
                require(not row['verifications'] and not row['decisions'],'exact control has no learned checks')
                holder=task['query']
                for e in reversed(task['events']):
                    a,b=e['pair'];holder=b if holder==a else a if holder==b else holder
                dist=[float(i==holder) for i in range(n)];action=f'answer:{holder}'
            else:
                depth=min(remaining,1 if policy=='myopic_verify' else 2) if policy in ('ndu_two_step','myopic_verify') else 0
                value,action=choose(h,depth,cost);dist=state(h)[0]
                require(not action.startswith('verify:') and len(row['decisions'])==di+1,'premature stopping or ghost decision')
                last=row['decisions'][di]
                require(last['action']==action and abs(last['value']-value)<1e-10,'terminal value')
            if kind=='joint':
                require(len(row['member_weight_history'])==len(member_history),'member history length')
                for a,b in zip(row['member_weight_history'],member_history):close(a,b,'conditional member posterior')
            else:require(row['member_weight_history'] is None,'product control must not claim a joint posterior')
            holder=None if action=='abstain' else int(action.split(':')[1]);text='Insufficient evidence; abstain.' if holder is None else task['values'][holder]
            answer=None if holder is None else '('+next(k for k,v in task['options'] if v==text)+')'
            require((row['holder'],row['text'],row['answer'])==(holder,text,answer),'decoded answer')
            close(row['probabilities'],dist,'final holder posterior')
            require(row['comparison_arm']==arm and row['arm']==policy and row['problem_sha256']==p['problem_ids'][kind]
                and abs(row['modeled_cost']-cost*len(row['verifications']))<1e-12,'problem/cost identity')
            for d in row['decisions']:
                require(type(d['cpu_ns']) is int and 0<=d['cpu_ns']<=100_000_000 and d['problem_sha256']==p['problem_ids'][kind],'planner budget/identity')
            require(type(row['cpu_ns']) is int and row['cpu_ns']>=0,'measured controller CPU')
            correct+=answer==targets[sid];answered+=answer is not None;checks+=len(row['verifications']);cpu+=row['cpu_ns'];total+=1
        expected_summary={'tasks':len(rows),'correct':correct,'answered':answered,'verification_calls':checks,'controller_cpu_ns':cpu,
                          'mean_external_score_minus_cost':(2*correct-answered-cost*checks)/len(rows)}
        require(result['summary'][arm]==expected_summary,'original result totals')
    require(result['shared_proposal_cpu_ns']==sum(r['cpu_ns'] for r in proposals),'shared physical work counted once')
    encoding=read('encoding');feature_plan=strict_loads((root/'feature-plan.json').read_bytes())
    audit_features(feature_plan,encoding['batches'],proposals)
    return {'audited_outputs':total,'original_tasks':len(tasks),'actual_proposal_rows':len(proposals),
        'conditional_common_member_recomputed':True,'forward_matrix_reference':True,
        'within_member_independence_is_assumed':True,'risk_calibrated':False,'execution_authenticated':False,
        'production_promotion_permitted':False}
