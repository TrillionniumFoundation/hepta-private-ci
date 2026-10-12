"""Saved-file arithmetic using the prior independent full-world reference.

No neural model, runtime planner or belief class import. Shares the declared
closed-grammar inventory, NOT an independent human semantic judgement.
"""
from itertools import permutations, combinations
import hashlib
import math
from pathlib import Path
import re
from four_gate_common import digest, require, strict_loads
from fbsde_tracking_tied_audit import reference
from fbsde_tracking_novelty_data import FAMILIAR, CALIBRATION, HELDOUT

PAIRS = tuple(combinations(range(3),2))
SPECS = {'base_no_checks': ('base','posterior_no_checks'), 'base_ndu': ('base','ndu_two_step'),
         'temperature_ndu': ('temperature','ndu_two_step'), 'constant_ndu': ('constant','ndu_two_step'),
         'novelty_no_checks': ('novelty','posterior_no_checks'), 'novelty_myopic': ('novelty','myopic_verify'),
         'novelty_ndu': ('novelty','ndu_two_step'), 'uniform_ndu': ('uniform','ndu_two_step'),
         'verify_all': ('novelty','verify_all'), 'exact_reverse': ('base','exact_reverse')}


def audit(root):
    root = Path(root)
    def read(n):
        p = root/(n+'.json')
        require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded original observation')
        return strict_loads(p.read_bytes())
    def close(a,b):
        require(len(a)==len(b) and all(math.isfinite(x) and math.isfinite(y) and abs(x-y)<1e-10
                                     for x,y in zip(a,b)),'probability/arithmetic mismatch')
    def words(text,names=()):
        for n in names: text = re.sub(r'\b'+re.escape(n)+r'\b','ACTOR',text)
        return tuple('actor' if w in ('self','other','actor') else w for w in re.findall('[a-z]+',text.lower()))
    def pair(text,names):
        found = {tuple(sorted((a,b))) for a,b,c in permutations(range(3)) for f in FAMILIAR+CALIBRATION+HELDOUT
                 if f.format(a=names[a],b=names[b],c=names[c])==text}
        require(len(found)==1,'independent declared-source check')
        return PAIRS.index(next(iter(found)))
    def laws(scores,temps):
        result=[]
        for s,t in zip(scores,temps):
            logits=[(s[a]+s[b])/t for a,b in PAIRS]; top=max(logits)
            w=[math.exp(x-top) for x in logits];result.append([x/math.fsum(w) for x in w])
        return result
    design,cal,support,inputs,priors,result = (read(n) for n in ('plan','calibration','support','inputs','priors','results'))
    require(design['profile']==result['profile']=='novelty_calibration_v1' and
            design['arms']=={a:list(v) for a,v in SPECS.items()} and design['max_checks']==2 and
            design['cost_per_check']==.02 and design['cpu_limit_ns']==100_000_000,'profile/limits drift')
    oldfit,oldcal=read('frozen-fit'),read('frozen-calibration'); temps=[t['selected'] for t in oldcal['temperatures']]
    require(hashlib.sha256((root/'frozen-heads.pt').read_bytes()).hexdigest()==design['frozen_heads_sha256']==
            oldfit['heads_bytes_sha256'],'frozen bytes changed')
    training=read('support-training-texts'); ws=[words(t) for t in training]
    require(support=={'unigrams':sorted({x for r in ws for x in r}),
        'bigrams':sorted({' '.join(p) for r in ws for p in zip(r,r[1:])}),
        'training_texts_sha256':digest(training),'no_labels_used':True},'support not training-only text')
    def feature(text,names,q):
        w=words(text,names);b=[' '.join(p) for p in zip(w,w[1:])];mean=[math.fsum(r[j] for r in q)/3 for j in range(3)]
        return [1.,sum(x not in support['unigrams'] for x in w)/len(w),
            sum(x not in support['bigrams'] for x in b)/max(1,len(b)),
            -math.fsum(p*math.log(p) for p in mean if p)/math.log(3),1-max(mean),
            max(math.fsum((r[j]-mean[j])**2 for j in range(3)) for r in q)]
    rows=cal['source_rows'];fitrows=cal['fit_rows']
    require(len(rows)==len(fitrows)==54 and len({r['text'] for r in rows})==54,'calibration denominator')
    for r,f in zip(rows,fitrows):
        q=laws(r['scores'],temps);j=pair(r['text'],r['names'])
        require(f['source_sha256']==digest(r['text']) and f['pair_index']==j,'local fit label/source')
        close(feature(r['text'],r['names'],q),f['features'])
        for a,b in zip(q,f['laws']):close(a,b)
    require(cal['gate']['calibration_rows_sha256']==digest(fitrows) and len(cal['gate']['weights'])==6,
            'gate fit binding')
    def loss(ps): return -math.fsum(math.log(max(p,1e-300)) for p in ps)/len(ps)
    tvalues=[(loss([math.fsum(x[f['pair_index']] for x in laws(r['scores'],[t]*3))/3
                   for r,f in zip(rows,fitrows)]),t) for t in design['temperature_grid']]
    avalues=[(loss([(1-a)*math.fsum(q[f['pair_index']] for q in f['laws'])/3+a/3
                   for f in fitrows]),a) for a in design['constant_grid']]
    require(cal['temperature']==min(tvalues)[1] and cal['constant']==min(avalues)[1],'calibration-only control selection')
    require(len(inputs)==156 and len(priors)==156,'complete task denominator')
    forms={words(r['text'],r['names']) for r in rows}
    require(all(words(t,r['names']) not in forms for r in inputs if r['split']=='heldout' for t in r['events']),
            'heldout normalized syntax overlap')
    proposals=read('proposals');ev={(r['source_id'],r['event']):r for r in proposals if r['phase']=='evaluation'}
    require(all(r['returned'] and type(r['cpu_ns']) is int and 0<=r['cpu_ns']<=100_000_000 for r in proposals),
            'proposal budget failure')
    targets=read('targets');alloutputs={a:read(a) for a in SPECS};cal_id=digest(cal);alphas=[];total=0
    require(all(len(rs)==156 and len({r['source_id'] for r in rs})==156 for rs in alloutputs.values()),'matched complete arms')
    for index,(src,prior) in enumerate(zip(inputs,priors)):
        sid=src['source_id'];truth=[pair(t,src['names']) for t in src['events']];holder=list(range(3))
        for j in truth:
            a,b=PAIRS[j];holder[a],holder[b]=holder[b],holder[a]
        require(targets[sid]==holder[src['query']],'final original target')
        bind={'source':digest(src),'model':digest(oldfit['members']),'calibration':cal_id,
              'scope':'novelty-calibration-research','generation':1}
        keys=[digest([t,src['names'],bind]) for t in src['events']]
        require(prior['binding']==bind and prior['keys']==keys and prior['source_id']==sid,'input binding')
        expected_ids = {k:digest(['input_tied_epistemic_v1',3,src['query'],c,[1/3]*3,keys,bind])
                        for k,c in prior['components'].items()}
        require(prior['problem_ids']==expected_ids,'conditional model identity')
        for i,text in enumerate(src['events']):
            p=ev[(sid,i)];require(p['text']==text and p['names']==src['names'],'proposal source mismatch')
            q=laws(p['scores'],temps);feat=feature(text,src['names'],q);v=math.fsum(a*b for a,b in zip(feat,cal['gate']['weights']))
            a=1/(1+math.exp(-v)) if v>=0 else math.exp(v)/(1+math.exp(v));alphas.append(a)
            close(feat,prior['annotations'][i]['features']);close([a],[prior['annotations'][i]['alpha']])
            expected={'base':q,'temperature':laws(p['scores'],[cal['temperature']]*3)}
            for kind,mass in [('novelty',a),('constant',cal['constant']),('uniform',1.)]:
                expected[kind]=[[(1-mass)*x+mass/3 for x in r] for r in q]
            for kind,qs in expected.items():
                for m,r in enumerate(qs):close(r,prior['components'][kind][m][i])
        refs={k:reference(c,[1/3]*3,keys,src['query']) for k,c in prior['components'].items()}
        for arm,(kind,policy) in SPECS.items():
            r=alloutputs[arm][index];require(r['source_id']==sid,'result source order');state,choose=refs[kind]
            h=();remaining=2;di=0
            require(r['arm']==policy and r['problem_sha256']==expected_ids[kind] and
                    type(r['cpu_ns']) is int and r['cpu_ns']>=0,'runtime identity and clock')
            require(policy=='verify_all' or len(r['verifications'])<=2,'global verification budget')
            for check in r['verifications']:
                if policy=='verify_all':event=next(i for i in range(len(truth)) if i not in dict(h))
                else:
                    value,action=choose(h,min(remaining,1 if policy=='myopic_verify' else 2))
                    d=r['decisions'][di];di+=1
                    require(action==d['action'] and abs(value-d['value'])<1e-10,'conditional check decision')
                    event=int(action.split(':')[1]) if action.startswith('verify:') else -1
                require(event>=0 and check['event']==event and check['pair_index']==truth[event] and
                    check['known_before']==[list(x) for x in h] and check['source_event_sha256']==digest(src['events'][event]),
                    'unrequested source evidence')
                h=tuple(sorted(h+((event,truth[event]),)));remaining-=1
            if policy=='exact_reverse':probs=[float(i==targets[sid]) for i in range(3)];action=f'answer:{targets[sid]}'
            else:
                depth=min(remaining,1 if policy=='myopic_verify' else 2) if policy in ('myopic_verify','ndu_two_step') else 0
                value,action=choose(h,depth);probs=state(h)[0];d=r['decisions'][di]
                require(len(r['decisions'])==di+1 and d['action']==action and abs(d['value']-value)<1e-10,'terminal decision')
            answer=None if action=='abstain' else int(action.split(':')[1]);close(probs,r['probabilities'])
            require(r['holder']==answer and r['text']==('Insufficient evidence; abstain.' if answer is None else
                ('amber','blue','coral')[answer]) and r['answer']==(None if answer is None else '('+'ABC'[answer]+')'),
                'decoded answer mismatch')
            require(r['modeled_cost']==.02*len(r['verifications']) and
                all(type(d['cpu_ns']) is int and 0<=d['cpu_ns']<=100_000_000 and
                    d['problem_sha256']==expected_ids[kind] for d in r['decisions']),'decision cost/budget')
            total+=1
    splitmap={r['source_id']:r['split'] for r in inputs}
    for split,report in result['summary'].items():
        for a,rs in alloutputs.items():
            rs=[r for r in rs if splitmap[r['source_id']]==split];n=len(rs)
            c=sum(r['holder']==targets[r['source_id']] for r in rs);answered=sum(r['holder'] is not None for r in rs)
            checks=sum(len(r['verifications']) for r in rs)
            require(report[a]=={'cases':n,'correct':c,'answered':answered,'checks':checks,
                'mean_utility':(2*c-answered-.02*checks)/n,'cpu_ns':sum(r['cpu_ns'] for r in rs)},'summary arithmetic')
    require(result['shared_proposal_cpu_ns']==sum(r['cpu_ns'] for r in proposals),'shared work accounting')
    return {'outputs':total,'calibration_events':len(rows),'heldout_templates':4,'heldout_cases':96,
            'alpha_range':[min(alphas),max(alphas)],'no_calibration_heldout_template_overlap':True,
            'source_independence_authenticated':False,'new_pretrained_execution':False,
            'risk_certificate':False,'production_promotion_permitted':False}
