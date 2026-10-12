"""Source/finite-world audit without Torch, runtime belief, planner or executor."""
from functools import lru_cache
from itertools import permutations, product
import hashlib
import math
from pathlib import Path
import re
from four_gate_common import digest, require, strict_loads
from fbsde_depth_audit import semantic_logits
from fbsde_gain_audit import FRAMES as OLD_FRAMES
from fbsde_outcome_audit import source_pair
from fbsde_tracking_tied_audit import reference as old_reference
from fbsde_role_data import FRAMES, generate

PAIRS=((0,1),(0,2),(1,2))
ARMS=('old_none','old_one','old_two','independent_role_two','program_head_none','program_head_one',
      'program_head_two','program_uniform_one','program_uniform_two','uniform_probe','verify_all_inputs','exact_reverse')


def reference(query, desc, priors, independent=False):
    keys=[d['key'] for d in desc]; unique=list(dict.fromkeys(keys)); groups=[unique.index(k) for k in keys]
    emissions=[d['emissions'] for d in desc];reps=[keys.index(k) for k in unique]
    require(len(desc)<=16 and 3**len(unique)<=8192,'bounded independent reference')
    laws=[[priors[g][emissions[i].index(j)] for j in range(3)] for i,g in enumerate(groups)]
    @lru_cache(None)
    def state(h):
        known=dict(h); outcomes={}; probability=[0.]*3; holders=set()
        if independent:
            available=[i for i in range(len(keys)) if i not in known]
            matrix=[[float(a==b) for b in range(3)] for a in range(3)]
            for i,law in enumerate(laws):
                row=[float(j==known[i]) for j in range(3)] if i in known else law
                nxt=[[0.]*3 for _ in range(3)]
                for p,(a,b) in zip(row,PAIRS):
                    for u in range(3):
                        for v in range(3): nxt[u][v]+=p*matrix[b if u==a else a if u==b else u][v]
                matrix=nxt
            return matrix[query],available,{i:laws[i] for i in available},None
        observed={}
        for i,j in h:
            g=groups[i];r=emissions[i].index(j)
            require(g not in observed or observed[g]==r,'inconsistent observed rule')
            observed[g]=r
        available=[i for g,i in enumerate(reps) if g not in observed];outcomes={i:[0.]*3 for i in available}
        candidates=[]
        for assignment in product(range(3),repeat=len(unique)):
            if not any(assignment[g]!=r for g,r in observed.items()):
                candidates.append((assignment,math.fsum(math.log(p[r]) for p,r in zip(priors,assignment))))
        peak=max(logmass for _,logmass in candidates)
        weights=[math.exp(logmass-peak) for _,logmass in candidates];denom=math.fsum(weights)
        for (assignment,_),rawmass in zip(candidates,weights):
            mass=rawmass/denom
            held=list(range(3))
            for i,g in enumerate(groups):a,b=PAIRS[emissions[i][assignment[g]]];held[a],held[b]=held[b],held[a]
            holders.add(held[query]);probability[held[query]]+=mass
            for i in available:outcomes[i][emissions[i][assignment[groups[i]]]]+=mass
        return probability,available,outcomes,holders
    @lru_cache(None)
    def choose(h,depth):
        p,available,laws,_=state(h);label=max(range(3),key=lambda j:(p[j],-j));value=max(0.,2*p[label]-1)
        action='abstain' if value==0 else f'answer:{label}'
        if depth and available and value < 1-.02-1e-12:
            for i in available:
                v=math.fsum(w*choose(tuple(sorted(h+((i,j),))),depth-1)[0] for j,w in enumerate(laws[i]) if w>0)-.02
                if v>value+1e-12:value,action=v,f'verify:{i}'
        return value,action
    return state,choose


def audit(root,source):
    root=Path(root);source=Path(source)
    def read(where,n):
        p=where/(n+'.json');require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded saved record')
        return strict_loads(p.read_bytes())
    def ns(v):require(type(v) is int and v>=0,'nonnegative measured CPU');return v
    def close(a,b):require(len(a)==len(b) and all(math.isfinite(x) and math.isfinite(y) and abs(x-y)<1e-9 for x,y in zip(a,b)),'probability mismatch')
    require(not (root/'failure.json').exists(),'failed study is not complete')
    plan=read(root,'plan');rows=read(root,'inputs');result=read(root,'results');priors=read(root,'priors')
    require(plan['uniform_one_added_after_initial_run'] is True and plan['profile']==result['profile']=='verified_role_program_v1' and plan['arms']==list(ARMS)
        and rows==generate(read(source,'inputs')) and len(rows)==len(priors)==444,'frozen inputs and controls')
    require((plan['max_checks'],plan['cpu_limit_ns'],plan['max_nodes'],plan['check_price'],plan['depth_price'])==(2,100_000_000,20000,.02,.002),'unaltered budgets')
    for name,h in plan['source_files'].items():require(hashlib.sha256((source/(name+'.json')).read_bytes()).hexdigest()==h,'parent bytes')
    snapshot=read(source,'frozen-model');cal=read(source,'frozen-calibration')
    require((plan['model'],plan['calibration'])==(digest(snapshot),digest(cal)),'frozen semantic model')
    outputs={a:read(root,a) for a in ARMS};require(all([r['source_id'] for r in records]==[r['source_id'] for r in rows] for records in outputs.values()),'complete ordered outputs')
    proposals=read(root,'proposals');pm={(r['source_id'],r['event']):r for r in proposals}
    require(len(pm)==len(proposals) and set(pm)=={(r['source_id'],i) for r in rows for i in range(len(r['events']))},'complete proposals')
    totals={s:{a:dict(cases=0,correct=0,answered=0,checks=0,deep=0,cpu_ns=0) for a in ARMS} for s in ('test','diagnostic_replay','retention')};truths={};count=0
    for index,(src,prior) in enumerate(zip(rows,priors)):
        sid=src['source_id'];names=src['names'];desc=[];ops=[];laws=[];components=[[],[],[]]
        for i,text in enumerate(src['events']):
            tokens=re.split(r'([A-Z][a-z]+)',text);order=list(dict.fromkeys(t for t in tokens if t in names))
            order.extend(n for n in names if n not in order)
            canonical=''.join('{R'+str(order.index(t))+'}' if t in names else t for t in tokens)
            emit=[PAIRS.index(tuple(sorted(names.index(n) for n in order if n!=omitted))) for omitted in order]
            desc.append(dict(frame=canonical,key=digest(['verified_role_program_v1',canonical]),roles=[names.index(n) for n in order],emissions=emit))
            matches={tuple(sorted((a,b))) for a,b,c in permutations(range(3)) for f in FRAMES+OLD_FRAMES
                     if f.format(a=names[a],b=names[b],c=names[c])==text}
            require(len(matches)<=1,'unambiguous independent source');ops.append(PAIRS.index(matches.pop()) if matches else source_pair(text,names))
            p=pm[(sid,i)];expect=semantic_logits(snapshot,text,names)
            require(p['returned'] is True and ns(p['cpu_ns'])<=100_000_000 and len(p['scores'])==3 and
                all(len(a)==len(b) and max(abs(x-y) for x,y in zip(a,b))<2e-5 for a,b in zip(expect,p['scores'])),'actual frozen proposal')
            for m,s in enumerate(p['scores']):
                logits=[(s[a]+s[b])/cal['selected'] for a,b in PAIRS];w=[math.exp(x-max(logits)) for x in logits]
                components[m].append([x/math.fsum(w) for x in w])
            laws.append([math.fsum(c[i][j] for c in components)/3 for j in range(3)])
        require(desc==prior['descriptions'] and prior['source_id']==sid,'public role mapping')
        keys=[d['key'] for d in desc];unique=list(dict.fromkeys(keys));learned=[]
        for key in unique:
            ids=[i for i,k in enumerate(keys) if k==key]
            learned.append([math.fsum(laws[i][desc[i]['emissions'][r]] for i in ids)/len(ids) for r in range(3)])
        require(learned==prior['head_priors'] and prior['uniform_priors']==[[1/3]*3 for _ in unique],'role prior not source truth')
        expected_old=dict(source_id=sid,query=src['query'],components=components,weights=[1/3]*3,
            keys=[digest([t,names,digest(snapshot),digest(cal)]) for t in src['events']])
        require(prior['old']==expected_old,'old comparator information')
        binding=dict(source=digest([src,desc]),model=digest(snapshot),calibration=digest(cal),scope='role-program-research',generation=3)
        require(prior['binding']==binding,'source and generation binding')
        head_laws=[[learned[unique.index(k)][desc[i]['emissions'].index(j)] for j in range(3)] for i,k in enumerate(keys)]
        oldbind=dict(binding,source=digest(expected_old))
        identities=dict(old=digest(['input_tied_epistemic_v1',3,src['query'],components,[1/3]*3,expected_old['keys'],oldbind]),
            head=digest(['verified_role_program_v1',src['query'],keys,[d['emissions'] for d in desc],learned,binding]),
            uniform=digest(['verified_role_program_v1',src['query'],keys,[d['emissions'] for d in desc],[[1/3]*3 for _ in unique],binding]),
            independent=digest([3,src['query'],head_laws,binding]))
        require(prior['identities']==identities,'problem byte identity')
        held=list(range(3))
        for op in ops:a,b=PAIRS[op];held[a],held[b]=held[b],held[a]
        truths[sid]=held[src['query']]
        oldstate,oldchoose=old_reference(components,[1/3]*3,expected_old['keys'],src['query'])
        refs={kind:reference(src['query'],desc,[[1/3]*3 for _ in unique] if kind=='uniform' else learned,kind=='independent') for kind in ('head','uniform','independent')}
        try:
            for arm in ARMS:
                r=outputs[arm][index];kind='independent' if arm=='independent_role_two' else 'uniform' if arm in ('uniform_probe','program_uniform_one','program_uniform_two') else 'head' if arm.startswith('program_') else 'old'
                require(r['arm']==arm and r['problem_sha256']==identities[kind] and r['semantic_certificate'] is False,'output identity')
                h=();remaining=2;used=0
                def state(h):
                    if kind!='old':return refs[kind][0](h)
                    p,_,observed=oldstate(h);ks=expected_old['keys'];reps=[ks.index(k) for k in dict.fromkeys(ks)]
                    return p,[i for g,i in enumerate(reps) if g not in observed],None,None
                choose=oldchoose if kind=='old' else refs[kind][1]
                if arm=='exact_reverse':
                    holder=truths[sid];dist=[float(j==holder) for j in range(3)];require(not r['checks'] and not r['decisions'],'exact own execution')
                else:
                    for step,d in enumerate(r['decisions']):
                        require(d['known']==[list(v) for v in h] and ns(d['cpu_ns'])<=100_000_000 and type(d['nodes']) is int and 0<=d['nodes']<=20000,'history and runtime budget')
                        p,available,_,support=state(h)
                        if arm=='uniform_probe':
                            holder=next(iter(support)) if len(support)==1 else None
                            action=f'answer:{holder}' if holder is not None else f'verify:{available[0]}' if used<2 and available else 'abstain'
                        elif arm=='verify_all_inputs' and available:action=f'verify:{available[0]}'
                        else:
                            horizon=0 if arm in ('old_none','program_head_none','verify_all_inputs') else min(remaining,1 if arm.endswith('one') else 2)
                            value,action=choose(h,horizon);require(d['plan']['remaining_checks']==horizon and abs(d['plan']['value']-value)<1e-9,'same control objective')
                        require(d['action']==action,'nonanticipative candidate choice')
                        if not action.startswith('verify:'):
                            holder=None if action=='abstain' else int(action.split(':')[1]);require(step==len(r['decisions'])-1,'work after terminal');break
                        e=int(action.split(':')[1]);require(e in available and (remaining>0 or arm=='verify_all_inputs'),'verification budget')
                        require(r['checks'][used]==dict(event=e,outcome=ops[e],known_before=[list(v) for v in h]),'source revelation')
                        used+=1;remaining-=1;h=tuple(sorted(h+((e,ops[e]),)))
                    else:raise ValueError('unfinished policy')
                    require(len(r['checks'])==used,'extra source revelation');dist=state(h)[0]
                require(r['holder']==holder and r['text']==('Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]),'final answer')
                close(r['probabilities'],dist);require(ns(r['cpu_ns'])>=sum(d['cpu_ns'] for d in r['decisions']),'execution CPU envelope')
                deep=arm in ('old_two','independent_role_two','program_head_two','program_uniform_two');require(r['depth2_requested']==deep,'deep-request cost')
                s=totals[src['split']][arm];s['cases']+=1;s['correct']+=holder==truths[sid];s['answered']+=holder is not None;s['checks']+=used;s['deep']+=deep;s['cpu_ns']+=r['cpu_ns'];count+=1
        finally:
            oldstate.cache_clear();oldchoose.cache_clear()
            for st,ch in refs.values():st.cache_clear();ch.cache_clear()
    for group in totals.values():
        for s in group.values():s['utility']=(2*s['correct']-s['answered']-.02*s['checks']-.002*s['deep'])/s['cases']
    require(read(root,'targets')==truths and result['summary']==totals,'scored labels and totals')
    require(result['proposal_cpu_ns']==sum(ns(p['cpu_ns']) for p in proposals),'shared proposal bill')
    return dict(outputs_recomputed=count,source_independence_authenticated=False,role_family_is_assumed=True,
                new_pretrained_forward=False,production_promotion_permitted=False)
