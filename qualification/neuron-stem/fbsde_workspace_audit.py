"""Saved-trajectory numerical decision audit; imports neither bank nor solver.

Checks the ORIGINAL fixed-point residual and a decision gap, not semantic truth,
authorization, execution authenticity or outward-rounded floating arithmetic.
"""
from pathlib import Path
import random
import math
from four_gate_common import digest, require, strict_loads
from fbsde_riccati_audit import original_metrics


def check_result(cfg, candidates, result, tolerance):
    require(result['status'] == 'resolved' and result['candidate_inventory_sha256'] == digest(candidates),
            'unresolved or changed candidate inventory')
    rows = result['rows']
    require(len(rows) == len(candidates) and [r['candidate'] for r in rows] == candidates,
            'candidate coverage or order drift')
    lo, hi = [], []
    for c,r in zip(candidates, rows):
        first = original_metrics(cfg,c['x0'],r['proposal'])['error_bound']
        last = original_metrics(cfg,c['x0'],r['y'])['error_bound']
        require(abs(first-r['initial_error_bound']) <= 3e-12 and
                abs(last-r['error_bound']) <= 3e-12, 'original residual bound mismatch')
        require(r['initial_score'] == r['proposal'][0]-c['cost'] and r['score'] == r['y'][0]-c['cost'],
                'changed scoring rule')
        require(type(r['refined']) is bool and type(r['updates']) is int and r['updates'] >= 0,
                'invalid refinement record')
        require(last <= 1.01e-10 if r['refined'] else r['y'] == r['proposal'], 'unverified candidate mutation')
        lo.append(r['score']-last); hi.append(r['score']+last)
    winner = max(range(len(rows)),key=lambda i:(lo[i],-i))
    gap = max(hi)-lo[winner]
    require(gap <= tolerance+6e-12 and abs(gap-result['gap_bound']) <= 6e-12,
            'unresolved decision gap')
    require(result['selected'] == candidates[winner]['id'] and result['text'] == f"Select {result['selected']}.",
            'unsupported selected action or unfaithful decoded answer')
    # Replay the recorded choice of which hypothesis to revise, without running a solver.
    scores = [r['initial_score'] for r in rows]; errors = [r['initial_error_bound'] for r in rows]
    done = set()
    for event in result['events']:
        low = [a-b for a,b in zip(scores,errors)]; high = [a+b for a,b in zip(scores,errors)]
        best_lower = max(low)
        eligible = [i for i in range(len(rows)) if i not in done and
                    (result['mode'] != 'verified_search' or high[i] > best_lower+tolerance)]
        require(eligible, 'unnecessary or duplicate refinement')
        chosen = max(eligible,key=lambda i:(high[i],-i)); row = rows[chosen]
        require(event['candidate_id'] == row['candidate']['id'] and
                event['newton_updates'] == row['updates'] and
                event['original_error_bound'] == row['error_bound'], 'noncausal refinement trace')
        scores[chosen],errors[chosen] = row['score'],row['error_bound']; done.add(chosen)
    events = result['events']; refined = {r['candidate']['id'] for r in rows if r['refined']}
    require(len(events) == len(refined) == result['refinements'] and
            {e['candidate_id'] for e in events} == refined, 'refinement trace mismatch')
    require(not result['production_promotion_permitted'] and not result['semantic_correctness_claimed'],
            'unsupported promotion/semantics')
    return {'gap_bound':gap, 'refinements':len(events)}


def check_bank(bank, profile, binding):
    body = {k:v for k,v in bank.items() if k != 'sha256'}
    require(bank['sha256'] == digest(body) and bank['profile'] == profile and
            bank['target'] == 'coupled_binary_tanh.root_y_minus_cost.v1' and
            all(bank[k] == v for k,v in binding.items()), 'saved bank identity')
    for row in bank['anchors']:
        metric = original_metrics(profile,row['x0'],row['y'])
        require(metric['error_bound'] <= 3e-12, 'saved anchor equation')
        x = metric['x']; d = row['dy_dx0']; n = len(row['y'])
        require(type(d) is list and len(d) == n and all(type(t) in (int,float) and math.isfinite(t) for t in d),
                'saved tangent inventory')
        h = profile['horizon']/profile['steps']; dx = []
        for node in range(2*n+1):
            ancestors = []; cursor = node
            while cursor:
                cursor = (cursor-1)//2; ancestors.append(cursor)
            dx.append(1+profile['a']*h*sum(d[i] for i in ancestors))
        full_d = d+[(1-math.tanh(v)**2)*dx[n+i] for i,v in enumerate(x[n:])]
        error = max(abs((1+profile['lam']*h)*d[i]-.5*(full_d[2*i+1]+full_d[2*i+2])-
                        profile['beta']*h*(1-math.tanh(x[i])**2)*dx[i]) for i in range(n))
        require(error <= 2e-10, 'saved tangent equation')
    return bank


def audit(root):
    def read(name):
        p = Path(root)/name
        require(p.is_file() and not p.is_symlink() and p.stat().st_size <= 64*1024*1024, 'bounded regular evidence')
        return strict_loads(p.read_bytes())
    plan, outputs, times, prep, summary = [read(n+'.json') for n in ('design','outputs','timings','preparation','summary')]
    require(plan['methods'] == ['cold_all','warm_all','verified_search'] and plan['repeats'] == 3 and
            plan['gap_tolerance'] == 1e-8, 'comparison plan drift')
    require(summary['outputs_sha256'] == digest(outputs) and summary['timings_sha256'] == digest(times)
            and summary['preparation_sha256'] == digest(prep), 'original-file identity')
    cases = {c['id']:c for c in plan['cases']}; identities = {}; refined = {m:0 for m in plan['methods']}
    require(len(outputs) == len(cases) == len(plan['cases']) and {o['id'] for o in outputs} == set(cases), 'case count drift')
    bank_by_profile = {}
    for c in cases.values():
        key = digest(c['profile'])
        if key not in bank_by_profile:
            bank_by_profile[key] = check_bank(read(f'bank-{key}.json'),c['profile'],plan['binding'])
    for item in outputs:
        case = cases[item['id']]
        require(set(item['methods']) == set(plan['methods']), 'missing strong controls')
        cold = item['methods']['cold_all']; gold = {r['candidate']['id']:r['score'] for r in cold['rows']}
        for mode, result in item['methods'].items():
            require(result['mode'] == mode and result['binding'] == plan['binding'], 'workspace mode or context drift')
            bank = bank_by_profile[digest(case['profile'])]
            require(result['bank_sha256'] == (None if mode == 'cold_all' else bank['sha256']), 'workspace bank drift')
            for row,candidate in zip(result['rows'],case['candidates']):
                anchor = min(bank['anchors'],key=lambda r:(abs(candidate['x0']-r['x0']),r['x0']))
                expected = ([0.]*(2**case['profile']['steps']-1) if mode == 'cold_all' else
                            [a+(candidate['x0']-anchor['x0'])*b for a,b in zip(anchor['y'],anchor['dy_dx0'])])
                require(row['proposal'] == expected, 'proposal does not use committed shared field')
            checked = check_result(case['profile'],case['candidates'],result,plan['gap_tolerance'])
            require(max(gold.values())-gold[result['selected']] <= plan['gap_tolerance']+3e-10,
                    'selection disagrees with complete precise control')
            if mode != 'verified_search': require(checked['refinements'] == len(gold), 'incomplete all-candidate control')
            identities[(item['id'],mode)] = digest(result)
            refined[mode] += checked['refinements']
    seen = set(); totals = {m:0 for m in plan['methods']}
    for t in times:
        key = (t['case_id'],t['method'],t['repeat'])
        require(key not in seen and key[:2] in identities and type(key[2]) is int and 0 <= key[2] < plan['repeats'],
                'duplicate/unmatched timing')
        order = list(plan['methods']); random.Random(f"{plan['seed']}:{key[0]}:{key[2]}").shuffle(order)
        require(type(t['position']) is int and 0 <= t['position'] < len(order), 'bounded timing position')
        require(order[t['position']] == key[1] and t['output_sha256'] == identities[key[:2]], 'timed output/order drift')
        require(type(t['cpu_ns']) is int and t['cpu_ns'] >= 0 and type(t['wall_ns']) is int and t['wall_ns'] >= 0,
                'unmeasured work')
        totals[key[1]] += t['cpu_ns']; seen.add(key)
    require(len(seen) == len(cases)*len(plan['methods'])*plan['repeats'], 'missing timed work')
    expected = {digest(c['profile']) for c in cases.values()}
    require(len(prep) == len(expected) and {r['profile_sha256'] for r in prep} == expected, 'missing/duplicate bank preparation')
    require(all(type(r['cpu_ns']) is int and r['cpu_ns'] >= 0 for r in prep), 'bank preparation work')
    preparation = sum(r['cpu_ns'] for r in prep)
    require(totals == summary['query_cpu_ns'] and refined == summary['unique_case_refinements'], 'work summary mismatch')
    require(summary['standalone_component_cpu_ns'] == {m:v+(0 if m=='cold_all' else preparation) for m,v in totals.items()},
            'unpaid shared preparation or imaginary amortization')
    raw_wrong = sum(max(o['methods']['verified_search']['rows'],key=lambda r:r['initial_score'])['candidate']['id']
                    != o['methods']['cold_all']['selected'] for o in outputs)
    disagrees = sum(o['methods']['verified_search']['selected'] != o['methods']['cold_all']['selected'] for o in outputs)
    require(summary['raw_proposal_wrong_selections'] == raw_wrong and
            summary['verified_disagrees_with_complete_exact'] == disagrees, 'decision quality summary drift')
    require(sum(totals.values())+preparation <= summary['cpu_envelope_ns'], 'work outside run envelope')
    return {'cases':len(cases),'timed_queries':len(times),'original_equation_and_decision_gap_checked':True,
            'query_cpu_ns':totals,'unique_case_refinements':refined,'bank_preparation_cpu_ns':preparation,
            'physical_execution_authenticated':False,'semantic_accuracy_claimed':False,'production_promotion_permitted':False}
