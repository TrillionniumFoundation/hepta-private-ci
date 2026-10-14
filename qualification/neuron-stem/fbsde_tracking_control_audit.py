"""Independent forward-marginal/whole-lookahead audit; imports no planner or model."""
from functools import lru_cache
from itertools import combinations
import math
from pathlib import Path

from four_gate_common import digest, require, strict_loads
from fbsde_tracking import parse, slot_text
from fbsde_tracking_audit import reference


def audit(directory):
    root = Path(directory)
    def read(name):
        path = root/('controller-'+name+'.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 128*1024*1024,
                'bounded original record')
        return strict_loads(path.read_bytes())
    design, fit, sources = read('plan'), read('calibration'), read('inputs')
    targets, result = read('targets'), read('results')
    inputs = {r['source_id']:r['input'] for r in sources}
    require(len(inputs) == len(sources) and set(inputs) == set(targets), 'input/target inventory')
    temperature = fit['fit']['selected']
    values = []
    for t in design['temperature_grid']:
        loss = 0.
        for row in fit['rows']:
            pairs = list(combinations(range(len(row['scores'])),2))
            logits = [(row['scores'][a]+row['scores'][b])/t for a,b in pairs]
            m = max(logits); weights = [math.exp(x-m) for x in logits]
            peak = logits.index(m)
            loss += m-logits[pairs.index(tuple(sorted(row['pair'])))]+math.log1p(
                math.fsum(w for i,w in enumerate(weights) if i!=peak))
        values.append((loss/len(fit['rows']),t))
    require(min(values)[1] == temperature and fit['fit']['input_sha256'] == digest(fit['rows']),
            'calibration selection mismatch')
    raw_proposals = read('proposals'); all_priors = read('priors')
    ev = [r for r in raw_proposals if r['split']=='evaluation']
    proposals = {(r['source_id'],r['event_index']):r for r in ev}
    require(len(ev)==len(proposals), 'duplicate proposal records')
    priors = {r['source_id']:r for r in all_priors}
    require(len(priors) == len(all_priors) and set(priors) == set(inputs), 'prior inventory')
    tasks = {sid:parse(text) for sid,text in inputs.items()}
    expected_proposals = {(sid,i) for sid,t in tasks.items() for i in range(len(t['events']))}
    require(set(proposals) == expected_proposals, 'complete event proposal inventory')
    for sid,task in tasks.items():
        prior = priors[sid]; n = len(task['names']); pairs = list(combinations(range(n),2))
        require(prior['binding'] == {'source':digest(inputs[sid]), 'model':design['gate_sha256'],
            'calibration':digest(fit['fit']), 'scope':'tracking-control-research','generation':1}, 'source/model binding')
        require(prior['problem_sha256'] == digest([n,task['query'],prior['laws'],prior['binding']]), 'belief binding')
        for i,event in enumerate(task['events']):
            r = proposals[(sid,i)]
            require(r['source_slot_texts'] == [slot_text(event['text'],task['names'],j) for j in range(n)]
                    and r['returned'] and 0 <= r['cpu_ns'] <= 100_000_000, 'source proposal/budget')
            logits = [(r['scores'][a]+r['scores'][b])/temperature for a,b in pairs]
            m = max(logits); w = [math.exp(v-m) for v in logits]; q=[v/math.fsum(w) for v in w]
            require(len(q)==len(prior['laws'][i]) and max(abs(a-b) for a,b in zip(q,prior['laws'][i]))<1e-12,
                    'probabilities not actual calibrated logits')
        require(reference(inputs[sid]) == targets[sid], 'original target/source mismatch')
    cost = design['cost_per_check']; audited=0
    for arm in design['arms']:
        rows=read(arm); require(len(rows)==len(inputs) and {r['source_id'] for r in rows}==set(inputs), 'paired arms')
        correct=answered=checks=0; cpu=0
        for row in rows:
            sid=row['source_id']; task=tasks[sid]; n=len(task['names']); pairs=list(combinations(range(n),2))
            laws=priors[sid]['laws']; count=0
            @lru_cache(maxsize=40000)
            def forward_marginal(h):
                nonlocal count
                count+=1; require(count<=40000,'audit bounded state work')
                known=dict(h); state=[[float(i==j) for j in range(n)] for i in range(n)]
                for i,law in enumerate(laws):
                    if i in known:
                        a,b=pairs[known[i]];state[a],state[b]=state[b],state[a]
                    else:
                        nxt=[[0.]*n for _ in range(n)]
                        for probability,(a,b) in zip(law,pairs):
                            if probability:
                                for j in range(n):
                                    k=b if j==a else a if j==b else j
                                    for c in range(n):nxt[j][c]+=probability*state[k][c]
                        state=nxt
                return state[task['query']]
            @lru_cache(maxsize=40000)
            def choose(h,d):
                p=forward_marginal(h);label=max(range(n),key=lambda j:(p[j],-j))
                best=max(0.,2*p[label]-1); action='abstain' if best==0 else f'answer:{label}'
                if d and best < 1-cost-1e-12:
                    for i,law in enumerate(laws):
                        if i in dict(h):continue
                        value=math.fsum(prob*choose(tuple(sorted(h+((i,j),))),d-1)[0]
                                        for j,prob in enumerate(law) if prob>0)-cost
                        if value>best+1e-12:best,action=value,f'verify:{i}'
                return best,action
            h=();remaining=2;di=0
            if arm=='greedy_no_checks':
                h=tuple((i,max(range(len(pairs)),key=lambda j:(law[j],-j))) for i,law in enumerate(laws))
            elif arm=='exact_reverse':
                h=tuple((i,pairs.index(tuple(sorted(e['pair'])))) for i,e in enumerate(task['events']))
            else:
                for event in row['verifications']:
                    if arm in ('ndu_two_step','myopic_verify'):
                        value,act=choose(h,min(remaining,1 if arm=='myopic_verify' else 2))
                        decision=row['decisions'][di];di+=1
                        require(act==decision['action'] and abs(value-decision['value'])<1e-10,'planner value/action mismatch')
                        i=int(act.split(':')[1]) if act.startswith('verify:') else -1
                    elif arm=='verify_all':i=next(j for j in range(len(laws)) if j not in dict(h))
                    elif arm=='confidence_verify':
                        require(remaining>0 and max(forward_marginal(h))<.95,'unnecessary confidence verification')
                        i=min((j for j in range(len(laws)) if j not in dict(h)),key=lambda j:(max(laws[j]),j))
                    else:raise ValueError('unexpected verification')
                    pair=pairs.index(tuple(sorted(task['events'][i]['pair']))) if i>=0 else -1
                    require(i==event['event'] and pair==event['pair_index'] and event['known_before']==[list(x) for x in h]
                        and event['source_event_sha256']==digest(task['events'][i]['text']),'future or wrong revealed event')
                    h=tuple(sorted(h+((i,pair),)));remaining-=1
            p=forward_marginal(h)
            if arm in ('greedy_no_checks','exact_reverse'):
                action=f'answer:{p.index(max(p))}'
            else:
                _,action=choose(h,min(remaining,1 if arm=='myopic_verify' else 2) if arm in ('ndu_two_step','myopic_verify') else 0)
                require(not action.startswith('verify:'),'premature stopping')
            holder=None if action=='abstain' else int(action.split(':')[1])
            text='Insufficient evidence; abstain.' if holder is None else task['values'][holder]
            answer=None if holder is None else '('+next(k for k,v in task['options'] if v==text)+')'
            require((holder,text,answer)==(row['holder'],row['text'],row['answer']) and
                    max(abs(a-b) for a,b in zip(p,row['probabilities']))<1e-10,'posterior/decoded answer mismatch')
            require(row['problem_sha256']==priors[sid]['problem_sha256'] and
                    abs(row['modeled_cost']-cost*len(row['verifications']))<1e-12,'cost/belief drift')
            checks+=len(row['verifications']);answered+=answer is not None;correct+=answer==targets[sid]
            require(type(row['cpu_ns']) is int and row['cpu_ns']>=0,'measured CPU');cpu+=row['cpu_ns'];audited+=1
        r=result['summary'][arm]
        require((r['correct'],r['answered'],r['verification_calls'],r['controller_cpu_ns'])==(correct,answered,checks,cpu),
                'reported totals mismatch')
        require(abs(r['mean_external_score_minus_cost']-(2*correct-answered-cost*checks)/len(rows))<1e-10,'utility total')
    return {'audited_outputs':audited,'original_tasks':len(inputs),'calibration_recomputed':True,
            'independent_forward_marginals':True,'nonanticipative_decisions_recomputed':True,
            'execution_authenticated':False,'risk_qualification_passed':False,'production_promotion_permitted':False}
