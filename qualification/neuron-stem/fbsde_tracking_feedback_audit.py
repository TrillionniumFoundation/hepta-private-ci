"""Independent saved-file recomputation. Imports no Torch, candidate or planner.

Floating recomputation checks are consistency, not proof of physical execution,
source independence, unrestricted-language semantics or calibration under shift.
"""
from itertools import combinations
import hashlib
import math
from pathlib import Path
import re
import struct
from four_gate_common import digest, require, strict_loads
from fbsde_tracking_tied_audit import reference

PAIRS = tuple(combinations(range(3), 2))


def pair_from_source(text, names, frames):
    answers = set()
    for template in frames:
        pattern = re.escape(template); seen = set()
        for key in re.findall(r'\{([abc])\}', template):
            token = re.escape('{'+key+'}')
            replacement = '(?P='+key+')' if key in seen else '(?P<'+key+'>[A-Z][a-z]+)'
            pattern = pattern.replace(token,replacement,1); seen.add(key)
        m = re.fullmatch(pattern,text)
        if m and set(m.groupdict().values()) <= set(names):
            pair = tuple(sorted((names.index(m['a']), names.index(m['b']))))
            if pair in PAIRS: answers.add(PAIRS.index(pair))
    require(len(answers) == 1, 'independent source grammar')
    return next(iter(answers))


def vector(text, names, slot):
    text = re.sub(r'\b('+'|'.join(map(re.escape,names))+r')\b',
                  lambda m:'SELF' if m[0] == names[slot] else 'OTHER', text)
    tokens = re.findall('[a-z]+',text.lower()); v = [0.]*128
    for gram in tokens+[' '.join(p) for p in zip(tokens,tokens[1:])]:
        h = hashlib.sha256(gram.encode()).digest(); v[int.from_bytes(h[:4],'little') % 128] += 1 if h[4]&1 else -1
    n = math.sqrt(sum(x*x for x in v)) or 1
    return list(struct.unpack('<128f',struct.pack('<128f',*(x/n for x in v))))


def neural_logits(state, x):
    def linear(prefix, inp):
        return [sum(a*b for a,b in zip(row,inp))+bias for row,bias in
                zip(state[prefix+'weight'],state[prefix+'bias'])]
    a = linear('value.',x); b = linear('gate.',x)
    return linear('output.',[math.tanh(v)/(1+math.exp(-g)) for v,g in zip(a,b)])[0]


def audit(root):
    root = Path(root)
    def read(name):
        p = root/(name+'.json')
        require(p.is_file() and not p.is_symlink() and p.stat().st_size < 64*1024*1024,'bounded original file')
        return strict_loads(p.read_bytes())
    plan, fit, weights, cal = read('plan'), read('fit'), read('candidate-weights'), read('calibration')
    public, proposed, priors, targets, result = (read(n) for n in ('inputs','proposals','priors','targets','results'))
    expected_arms = {'frozen_no_checks':['base_raw','posterior_no_checks'],
        'temperature_ndu':['base_temp','ndu_two_step'],'smoothing_ndu':['smooth','ndu_two_step'],
        'residual_no_checks':['residual','posterior_no_checks'],'residual_myopic':['residual','myopic_verify'],
        'residual_ndu':['residual','ndu_two_step'],'finetuned_no_checks':['finetuned','posterior_no_checks'],
        'finetuned_ndu':['finetuned','ndu_two_step'],'linear_no_checks':['linear','posterior_no_checks'],
        'linear_ndu':['linear','ndu_two_step'],'verify_all':['base_raw','verify_all'],
        'exact_reverse':['base_raw','exact_reverse']}
    require(plan['arms'] == expected_arms, 'complete cheaper-control inventory')
    require(plan['profile'] == result['profile'] == 'verified_feedback_learning_v1'
        and plan['public_sha256'] == digest(public) and plan['cost_per_check'] == .02
        and plan['max_checks'] == 2 and plan['proposal_cpu_limit_ns'] == 100_000_000,'registered problem')
    require(fit['snapshot_sha256'] == digest(weights),'candidate snapshot identity')
    parent = read('frozen-fit')
    def tensor_hash(values):
        shape = []; x = values
        while isinstance(x,list): shape.append(len(x)); x = x[0]
        def flatten(v):
            return [n for row in v for n in flatten(row)] if isinstance(v,list) else [v]
        flat = flatten(values)
        return hashlib.sha256(str(('torch.float32',tuple(shape))).encode('ascii')+
                              struct.pack('<'+str(len(flat))+'f',*flat)).hexdigest()
    require([digest({k:tensor_hash(v) for k,v in m.items()}) for m in weights['base']] == parent['members'],
            'frozen parent tensors changed')
    frames = plan['feedback_frames']+plan['calibration_frames']+plan['heldout_frames']
    feedback, before = read('feedback'), read('before-feedback')
    require(fit['feedback_sha256'] == digest(feedback) and len(feedback) == len(before) == 54
        and fit['prediction_file_sha256'] == hashlib.sha256((root/'before-feedback.json').read_bytes()).hexdigest(),
        'sealed feedback coverage')
    held = {t for r in public if r['split'] == 'heldout' for t in r['events']}
    for i,(r,p) in enumerate(zip(feedback,before)):
        src = r['source']
        require(r['prediction_sha256'] == digest(p) and r['sequence'] == 2*i+1 and p['index'] == i
            and p['source'] == src and src['source_id'] == digest(src['text']) and src['text'] not in held,
            'prediction/feedback source order')
        require(r['observer'] == 'simulator_source_verifier' and p['phase'] == 'before_feedback',
                'simulator provenance not production attestation')
        require(PAIRS.index(tuple(r['pair'])) == pair_from_source(src['text'],src['names'],frames),
            'feedback contradicts source')
    require(len({r['source']['source_id'] for r in feedback}) == 54, 'duplicated feedback source')
    require(len(cal['rows']) == 18 and not {r['text'] for r in cal['rows']} & held, 'calibration overlap')
    cached = {}
    def check_logits(row, recorded):
        key = digest([row['text'],row['names']])
        if key not in cached:
            xs = [vector(row['text'],row['names'],j) for j in range(3)]
            base = [[neural_logits(m,x) for x in xs] for m in weights['base']]
            delta = [sum(a*b for a,b in zip(weights['residual']['weight'][0],x))+weights['residual']['bias'][0] for x in xs]
            simple = [sum(a*b for a,b in zip(weights['linear']['weight'][0],x))+weights['linear']['bias'][0] for x in xs]
            cached[key] = {'frozen':base,'residual':[[v+d for v,d in zip(s,delta)] for s in base],
                'finetuned':[[neural_logits(m,x) for x in xs] for m in weights['finetuned']], 'linear':[simple]*3}
        for kind, scores in recorded.items():
            require(len(scores) == 3 and all(len(s) == 3 for s in scores),'score inventory')
            require(all(math.isfinite(a) and abs(a-b) < 3e-5 for s,t in zip(scores,cached[key][kind])
                        for a,b in zip(s,t)),'scores differ from saved candidate weights')
    for p in before: check_logits(p['source'], {'frozen':p['scores']})
    def law(scores, temp):
        logits = [(scores[a]+scores[b])/temp for a,b in PAIRS]; peak = max(logits)
        mass = [math.exp(x-peak) for x in logits]; return [v/math.fsum(mass) for v in mass]
    for row in cal['rows']:
        require(PAIRS.index(tuple(row['pair'])) == pair_from_source(row['text'],row['names'],frames),
                'calibration label changed')
        check_logits(row,row['scores'])
    for kind, temperature in cal['temperatures'].items():
        losses = []
        for t in plan['temperature_grid']:
            probs = [math.fsum(law(s,t)[PAIRS.index(tuple(r['pair']))] for s in r['scores'][kind])/3 for r in cal['rows']]
            losses.append((-math.fsum(math.log(max(p,1e-300)) for p in probs)/len(probs),t))
        require(min(losses)[1] == temperature,'temperature selected on other data')
    constants = []
    for a in plan['constant_grid']:
        probs = [(1-a)*math.fsum(law(s,cal['temperatures']['frozen'])[PAIRS.index(tuple(r['pair']))]
                     for s in r['scores']['frozen'])/3+a/3 for r in cal['rows']]
        constants.append((-math.fsum(math.log(max(p,1e-300)) for p in probs)/len(probs),a))
    require(min(constants)[1] == cal['alpha'],'smoothing selection')
    events = {(r['source_id'],r['event']):r for r in proposed if r['split'] == 'evaluation'}
    require(len(events) == sum(len(r['events']) for r in public) and len(proposed) == len(events)+18,'real proposal inventory')
    require(all(type(r['cpu_ns']) is int and 0 <= r['cpu_ns'] <= 100_000_000 and r['returned'] for r in proposed), 'failed proposal used')
    require(sum(r['cpu_ns'] for r in proposed) == result['shared_proposal_cpu_ns'],'unpaid proposal work')
    pr = {r['source_id']:r for r in priors}; allrows = {a:read(a) for a in plan['arms']}
    require(len(pr) == len(priors) == len(public) == 204 and set(pr) == set(targets),'complete input denominator')
    require(all(len(rs) == 204 and len({r['source_id'] for r in rs}) == 204 for rs in allrows.values()),'complete matched arms')
    consensus = {k:{'events':0,'unanimous_wrong':0,'unique_wrong':set()} for k in cal['temperatures']}
    oldtemps = read('old-temperatures'); strata = {}
    for idx,src in enumerate(public):
        sid = src['source_id']; p = pr[sid]; truth = [pair_from_source(t,src['names'],frames) for t in src['events']]
        holders = list(range(3))
        for j in truth:
            a,b = PAIRS[j]; holders[a],holders[b] = holders[b],holders[a]
        require(targets[sid] == holders[src['query']], 'independent final answer')
        binding = {'source':digest(src),'model':digest(weights),'calibration':digest(cal),'scope':'verified-feedback-research','generation':2}
        require(p['binding'] == binding and p['keys'] == [digest([t,src['names'],binding]) for t in src['events']], 'input/generation binding')
        for i,text in enumerate(src['events']):
            r = events[sid,i]; require(r['text'] == text and r['names'] == src['names'],'source event')
            check_logits(r,r['scores'])
            raw = r['scores']; temp = [law(s,cal['temperatures']['frozen']) for s in raw['frozen']]
            variants = {'base_raw':[law(s,t) for s,t in zip(raw['frozen'],oldtemps)],'base_temp':temp,
                'smooth':[[(1-cal['alpha'])*v+cal['alpha']/3 for v in q] for q in temp],
                **{k:[law(s,cal['temperatures'][k]) for s in raw[k]] for k in ('residual','finetuned','linear')}}
            for kind,qs in variants.items():
                require(all(abs(a-b) < 1e-12 for m,q in enumerate(qs) for a,b in zip(q,p['components'][kind][m][i])), 'declared law drift')
            if src['split'] == 'heldout':
                for kind,scores in raw.items():
                    top = [max(range(3),key=lambda j:(s[PAIRS[j][0]]+s[PAIRS[j][1]],-j)) for s in scores]
                    d = consensus[kind]; d['events'] += 1
                    if len(set(top)) == 1 and top[0] != truth[i]:
                        d['unanimous_wrong'] += 1; d['unique_wrong'].add(digest(text))
        refs = {k:reference(v,[1/3]*3,p['keys'],src['query']) for k,v in p['components'].items()}
        for arm,(kind,policy) in plan['arms'].items():
            row = allrows[arm][idx]; require(row['source_id'] == sid,'paired row order')
            state, choose = refs[kind]; h = (); remaining = 2; di = 0
            for event in row['verifications']:
                if policy == 'verify_all': e = next(i for i in range(len(truth)) if i not in dict(h))
                else:
                    value,action = choose(h,min(remaining,1 if policy == 'myopic_verify' else 2))
                    d = row['decisions'][di]; di += 1
                    require(d['action'] == action and abs(d['value']-value)<1e-10 and remaining>0,'conditional action')
                    require(action.startswith('verify:'),'unrequested verification'); e = int(action.split(':')[1])
                require(event['event'] == e and event['pair_index'] == truth[e] and event['known_before'] == [list(v) for v in h]
                    and event['source_event_sha256'] == digest(src['events'][e]) and event['modeled_cost'] == .02, 'revelation changed')
                h = tuple(sorted(h+((e,truth[e]),))); remaining -= 1
            if policy == 'exact_reverse':
                require(not row['decisions'] and not row['verifications'],'exact comparator')
                probabilities = [float(j==targets[sid]) for j in range(3)]; action = f'answer:{targets[sid]}'
            else:
                depth = min(remaining,1 if policy=='myopic_verify' else 2) if policy in ('myopic_verify','ndu_two_step') else 0
                value,action = choose(h,depth); probabilities = state(h)[0]
                require(len(row['decisions']) == di+1 and row['decisions'][di]['action'] == action and
                    abs(row['decisions'][di]['value']-value)<1e-10,'terminal decision')
            holder = None if action == 'abstain' else int(action.split(':')[1])
            require(row['holder'] == holder and row['answer'] == (None if holder is None else '('+'ABC'[holder]+')')
                and row['text'] == ('Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]), 'decoded answer')
            require(max(abs(a-b) for a,b in zip(probabilities,row['probabilities']))<1e-10,'final probability')
            expected_id = digest(['input_tied_epistemic_v1',3,src['query'],p['components'][kind],[1/3]*3,p['keys'],binding])
            require(row['problem_sha256'] == p['problem_ids'][kind] == expected_id and
                row['modeled_cost'] == .02*len(row['verifications']), 'problem/cost identity')
            require(all(0 <= d['cpu_ns'] <= 100_000_000 for d in row['decisions']),'planner budget')
            g = strata.setdefault(src['split']+':'+str(src['family']),{}).setdefault(arm,{'cases':0,'correct':0,'checks':0})
            g['cases']+=1; g['correct']+=holder==targets[sid]; g['checks']+=len(row['verifications'])
    split_of = {r['source_id']:r['split'] for r in public}
    require(set(result['summary']) == {'heldout','known_replay'} and
            all(set(v) == set(expected_arms) for v in result['summary'].values()), 'reported arm inventory')
    require(result['new_fit_cpu_ns'] == sum(j['cpu_ns'] for j in fit['jobs']) and
            all(j['feedback_sha256'] == digest(feedback) and j['steps'] == 160 and j['lr'] == .01
                and j['cpu_ns'] >= 0 for j in fit['jobs']), 'fit data and costs')
    for split in ('heldout','known_replay'):
        for arm,rs in allrows.items():
            rows = [r for r in rs if split_of[r['source_id']] == split]; n=len(rows)
            c=sum(r['holder']==targets[r['source_id']] for r in rows); a=sum(r['holder'] is not None for r in rows)
            checks=sum(len(r['verifications']) for r in rows)
            require(result['summary'][split][arm] == {'cases':n,'correct':c,'answered':a,'checks':checks,
                'mean_utility':(2*c-a-.02*checks)/n,'cpu_ns':sum(r['cpu_ns'] for r in rows)}, 'aggregate arithmetic')
    for d in consensus.values(): d['unique_wrong'] = len(d['unique_wrong'])
    return {'audited_outputs':204*len(allrows),'feedback_rows':54,'calibration_rows':18,
        'proposal_rows':len(proposed),'heldout_consensus_errors':consensus,'by_family':strata,
        'frozen_parent_unchanged':True,'model_or_planner_imported':False,
        'risk_certified':False,'new_pretrained_execution':False,'production_promotion_permitted':False}
