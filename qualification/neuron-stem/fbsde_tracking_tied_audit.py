"""Independent original-file arithmetic, not execution/risk certification.

No Torch, runtime belief model, planner, state executor or challenge parser import.
Forward matrices handle singleton variables; tied variables are jointly summed.
"""
from functools import lru_cache
from itertools import combinations, product
import hashlib
import math
from pathlib import Path
import re
from four_gate_common import digest, require, strict_loads

PAIRS=tuple(combinations(range(3),2))
PATTERNS=(
 (r'([A-Z][a-z]+) watches while ([A-Z][a-z]+) swaps parcels with ([A-Z][a-z]+)\.',(2,3)),
 (r'Only ([A-Z][a-z]+) and ([A-Z][a-z]+) exchange parcels; ([A-Z][a-z]+) keeps theirs\.',(1,2)),
 (r'The parcels of ([A-Z][a-z]+) and ([A-Z][a-z]+) are exchanged; ([A-Z][a-z]+) waits\.',(1,2)),
 (r'([A-Z][a-z]+) is not in the exchange: ([A-Z][a-z]+) trades parcels with ([A-Z][a-z]+)\.',(2,3)),
 (r'([A-Z][a-z]+) gives their parcel to ([A-Z][a-z]+), who gives theirs to \1; ([A-Z][a-z]+) stays put\.',(1,2)),
 (r'With ([A-Z][a-z]+) watching, ([A-Z][a-z]+) and ([A-Z][a-z]+) trade their parcels\.',(2,3)))


def source_pair(text,names):
    matches=[]
    for pattern,indices in PATTERNS:
        m=re.fullmatch(pattern,text)
        if m and set(m.groups())==set(names):matches.append(tuple(sorted(names.index(m[i]) for i in indices)))
    require(len(matches)==1,'independent source grammar')
    return PAIRS.index(matches[0])


def reference(components,weights,keys,query):
    unique=tuple(dict.fromkeys(keys));groups=tuple(unique.index(k) for k in keys)
    reps=tuple(keys.index(k) for k in unique)
    @lru_cache(maxsize=20000)
    def state(history):
        observed={}
        for i,j in history:
            g=groups[i];require(g not in observed or observed[g]==j,'contradictory source key')
            observed[g]=j
        logs=[]
        for w,c in zip(weights,components):
            ps=[c[reps[g]][j] for g,j in observed.items()]
            logs.append(math.log(w)+math.fsum(math.log(p) for p in ps) if w and all(ps) else -math.inf)
        peak=max(logs);require(math.isfinite(peak),'joint support')
        mass=[math.exp(v-peak) for v in logs];posterior=[w/math.fsum(mass) for w in mass]
        answer=[0.]*3
        for w,c in zip(posterior,components):
            if len(unique)==len(keys):
                matrix=[[float(i==j) for j in range(3)] for i in range(3)]
                for i,law in enumerate(c):
                    law=[float(j==observed[i]) for j in range(3)] if i in observed else law
                    matrix=[[math.fsum(p*matrix[b if r==a else a if r==b else r][j]
                               for p,(a,b) in zip(law,PAIRS)) for j in range(3)] for r in range(3)]
                for j,v in enumerate(matrix[query]):answer[j]+=w*v
            else:
                choices=[(observed[g],) if g in observed else range(3) for g in range(len(unique))]
                for assignment in product(*choices):
                    p=w*math.prod(c[reps[g]][j] for g,j in enumerate(assignment) if g not in observed)
                    holders=list(range(3))
                    for g in groups:
                        a,b=PAIRS[assignment[g]];holders[a],holders[b]=holders[b],holders[a]
                    answer[holders[query]]+=p
        return answer,posterior,observed
    @lru_cache(maxsize=20000)
    def choose(history,depth):
        probs,posterior,observed=state(history);label=max(range(3),key=lambda j:(probs[j],-j))
        best=max(0.,2*probs[label]-1);action='abstain' if best==0 else f'answer:{label}'
        if depth and best<.98-1e-12:
            for g,event in enumerate(reps):
                if g in observed:continue
                law=[math.fsum(w*c[event][j] for w,c in zip(posterior,components)) for j in range(3)]
                value=math.fsum(p*choose(tuple(sorted(history+((event,j),))),depth-1)[0]
                                for j,p in enumerate(law) if p>0)-.02
                if value>best+1e-12:best,action=value,f'verify:{event}'
        return best,action
    return state,choose


def audit(root):
    root=Path(root)
    def read(name):
        p=root/(name+'.json');require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded original file')
        return strict_loads(p.read_bytes())
    design,fit,cal=read('design'),read('fit'),read('calibration')
    public,priors,proposals,result,targets=read('inputs'),read('priors'),read('proposals'),read('results'),read('targets')
    require(design['profile']==result['profile']=='input_tied_challenge_v1' and len(public)==144,
            'registered challenge inventory')
    require(design['check_cost']==.02 and design['max_checks']==2 and design['proposal_cpu_limit_ns']==100_000_000,'budget/goal drift')
    require(hashlib.sha256((root/'heads.pt').read_bytes()).hexdigest()==fit['heads_bytes_sha256'],'weights byte identity')
    expected_arms={'single_no_checks':['single','posterior_no_checks'],'product_no_checks':['pooled','posterior_no_checks'],
        'shared_no_checks':['shared','posterior_no_checks'],'shared_myopic':['shared','myopic_verify'],
        'shared_ndu':['shared','ndu_two_step'],'tied_no_checks':['tied','posterior_no_checks'],
        'tied_myopic':['tied','myopic_verify'],'tied_ndu':['tied','ndu_two_step'],
        'verify_all':['shared','verify_all'],'exact_reverse':['pooled','exact_reverse']}
    require(design['arms']==expected_arms and set(result['summary'])==set(expected_arms),'strong controls changed')
    allrows={a:read(a) for a in expected_arms};temps=[t['selected'] for t in cal['temperatures']]
    for member,t in enumerate(temps):
        losses=[]
        for tau in design['temperature_grid']:
            total=0.
            for r in cal['rows']:
                logits=[(r['scores'][member][a]+r['scores'][member][b])/tau for a,b in PAIRS]
                peak=max(range(3),key=logits.__getitem__)
                total+=logits[peak]-logits[PAIRS.index(tuple(sorted(r['pair'])))]+math.log1p(
                    math.fsum(math.exp(v-logits[peak]) for j,v in enumerate(logits) if j!=peak))
            losses.append((total/len(cal['rows']),tau))
        require(min(losses)[1]==t,'temperature changed after calibration')
    eventrows={(r['source_id'],r['event']):r for r in proposals if r['phase']=='evaluation'}
    require(len(eventrows)==sum(len(r['events']) for r in public),'event coverage')
    require(sum(r['cpu_ns'] for r in proposals)==result['shared_proposal_cpu_ns'],'unpaid shared forwards')
    require(all(type(r['cpu_ns']) is int and 0<=r['cpu_ns']<=100_000_000 and r['returned'] for r in proposals),'denied proposal returned')
    split_keys={'calibration':set(),'evaluation':set()}
    for r in proposals:
        names=r['names']
        slots=[re.sub(r'\b('+'|'.join(map(re.escape,names))+r')\b',
            lambda m:'SELF' if m[0]==name else 'OTHER',r['text']) for name in names]
        require(digest(slots)==r['slots_sha256'],'participant input binding')
        split_keys[r['phase']].update(slots)
    require(not split_keys['calibration'].intersection(split_keys['evaluation']),
            'calibration/test wording overlap')
    pr={r['source_id']:r for r in priors};disagreements=consensus_wrong=0;strata={}
    for i,src in enumerate(public):
        sid=src['source_id'];p=pr[sid];truth=[source_pair(s,src['names']) for s in src['events']]
        holders=list(range(3))
        for j in truth:
            a,b=PAIRS[j];holders[a],holders[b]=holders[b],holders[a]
        require(targets[sid]==holders[src['query']],'independent source answer mismatch')
        b={'source':digest(src),'model':digest(fit['members']),'calibration':digest(cal['temperatures']),
           'scope':'unseen-input-tied-research','generation':1}
        require(p['binding']==b and p['keys']==[digest([s,src['names'],b]) for s in src['events']],'false repeated-input identity')
        require(p['weights']==[1/3]*3,'member prior drift')
        for event,text in enumerate(src['events']):
            r=eventrows[sid,event];require(r['text']==text and r['names']==src['names'],'source event mismatch')
            top=[]
            for m,scores in enumerate(r['scores']):
                logits=[(scores[a]+scores[b])/temps[m] for a,b in PAIRS];peak=max(logits)
                mass=[math.exp(v-peak) for v in logits];law=[v/math.fsum(mass) for v in mass]
                require(max(abs(a-b) for a,b in zip(law,p['components'][m][event]))<1e-12,'logits/law mismatch')
                top.append(max(range(3),key=lambda j:(law[j],-j)))
            disagreements+=len(set(top))>1;consensus_wrong+=len(set(top))==1 and top[0]!=truth[event]
        pooled=[[math.fsum(p['components'][m][e][j]/3 for m in range(3)) for j in range(3)] for e in range(len(truth))]
        refs={'single':reference([p['components'][0]],[1.],list(range(len(truth))),src['query']),
              'pooled':reference([pooled],[1.],list(range(len(truth))),src['query']),
              'shared':reference(p['components'],p['weights'],list(range(len(truth))),src['query']),
              'tied':reference(p['components'],p['weights'],p['keys'],src['query'])}
        for arm,(kind,policy) in expected_arms.items():
            row=allrows[arm][i];require(row['source_id']==sid,'unpaired result row')
            state,choose=refs[kind];h=();remaining=2;decision_index=0
            for v in row['verifications']:
                if policy=='verify_all':event=next(e for e in range(len(truth)) if e not in dict(h))
                else:
                    val,act=choose(h,min(remaining,1 if policy=='myopic_verify' else 2))
                    d=row['decisions'][decision_index];decision_index+=1
                    require(d['action']==act and abs(d['value']-val)<1e-10,'conditional policy mismatch')
                    event=int(act.split(':')[1]) if act.startswith('verify:') else -1
                require(v['event']==event and v['pair_index']==truth[event] and v['known_before']==[list(x) for x in h]
                    and v['source_event_sha256']==digest(src['events'][event]) and v['modeled_cost']==.02,'unselected or false evidence')
                h=tuple(sorted(h+((event,truth[event]),)));remaining-=1
            if policy=='exact_reverse':
                probs=[float(j==targets[sid]) for j in range(3)];act=f'answer:{targets[sid]}'
            else:
                depth=min(remaining,1 if policy=='myopic_verify' else 2) if policy in ('myopic_verify','ndu_two_step') else 0
                val,act=choose(h,depth);probs=state(h)[0];d=row['decisions'][decision_index]
                require(len(row['decisions'])==decision_index+1 and d['action']==act and abs(d['value']-val)<1e-10,'terminal policy mismatch')
            holder=None if act=='abstain' else int(act.split(':')[1]);text='Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]
            require(row['holder']==holder and row['text']==text and row['answer']==(None if holder is None else '('+'ABC'[holder]+')'),'decoded output mismatch')
            require(max(abs(a-b) for a,b in zip(probs,row['probabilities']))<1e-10,'holder probabilities mismatch')
            require(row['modeled_cost']==.02*len(row['verifications']) and row['problem_sha256']==p['problem_ids'][kind],'cost or model identity')
            require(all(d['cpu_ns']<=100_000_000 for d in row['decisions']),'planner budget failure')
            g=strata.setdefault(str(src['family']),{}).setdefault(arm,{'cases':0,'correct':0,'checks':0})
            g['cases']+=1;g['correct']+=holder==targets[sid];g['checks']+=len(row['verifications'])
    for arm,rows in allrows.items():
        require(len(rows)==144 and len({r['source_id'] for r in rows})==144,'full unfiltered case set')
        correct=sum(r['holder']==targets[r['source_id']] for r in rows);answered=sum(r['holder'] is not None for r in rows)
        checks=sum(len(r['verifications']) for r in rows);brier=sum(sum((v-float(j==targets[r['source_id']]))**2 for j,v in enumerate(r['probabilities']))/2 for r in rows)/144
        expected={'cases':144,'correct':correct,'answered':answered,'checks':checks,'brier':brier,
                  'mean_utility':(2*correct-answered-.02*checks)/144,'cpu_ns':sum(r['cpu_ns'] for r in rows)}
        require(expected==result['summary'][arm],'result arithmetic')
    return {'audited_outputs':144*len(allrows),'evaluation_events':len(eventrows),
        'member_top_pair_disagreements':disagreements,'all_members_agree_but_wrong':consensus_wrong,
        'unique_original_event_texts':len({s for r in public for s in r['events']}),'by_family':strata,
        'risk_certificate':False,'independent_sources_authenticated':False,'pretrained_execution':False,
        'calibration_evaluation_normalized_overlap':0,
        'runtime_planner_imported':False,'production_promotion_permitted':False}
