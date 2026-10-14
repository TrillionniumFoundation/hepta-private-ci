"""Bounded propose/check/refine/select workspace for a finite numerical control task.

A candidate is an initial state and deterministic cost, all fixed BEFORE noise.
Score = original coupled-system Y0 minus cost. This is not language reasoning,
continuous control, an independent verifier of model truth or production authority.
"""
import math
from four_gate_common import digest, require
from fbsde_coupled import residual_report
from fbsde_riccati import solve_newton
from fbsde_continuation import validate_context


def choose_candidate(p, candidates, bank, *, scope, generation, objective,
                     gap_tolerance=1e-8, max_refinements=32, mode='verified_search'):
    p.validate(); validate_context(scope,generation,objective)
    require(mode in ('verified_search','warm_all','cold_all'), 'registered workspace mode')
    require(type(gap_tolerance) in (int,float) and math.isfinite(gap_tolerance) and
            1e-9 <= gap_tolerance <= 1e-5, 'decision gap tolerance')
    require(type(max_refinements) is int and 0 <= max_refinements <= 32, 'bounded refinement budget')
    require(type(candidates) is list and 2 <= len(candidates) <= 32, 'bounded candidate set')
    ids = []
    for c in candidates:
        require(set(c) == {'id','x0','cost'} and type(c['id']) is str and 0 < len(c['id']) <= 128,
                'public candidate contract')
        require(type(c['x0']) in (int,float) and math.isfinite(c['x0']) and abs(c['x0']) <= p.radius,
                'candidate state domain')
        require(type(c['cost']) in (int,float) and math.isfinite(c['cost']) and 0 <= c['cost'] <= 3,
                'candidate cost units')
        ids.append(c['id'])
    require(len(ids) == len(set(ids)), 'duplicate candidate identity')
    rows = []; refinements = 0
    for c in candidates:
        if mode == 'cold_all':
            initial = [0.]*(2**p.steps-1); anchor = None
        else:
            prediction = bank.predict(p,c['x0'],scope=scope,generation=generation,objective=objective)
            initial, anchor = prediction['y'], prediction['anchor_x0']
        error = residual_report(p,c['x0'],initial)['y_error_bound_exact_arithmetic']
        estimate = initial[0]-c['cost']
        rows.append({'candidate': dict(c), 'anchor_x0': anchor, 'proposal': initial,
                     'initial_error_bound': error, 'initial_score': estimate, 'y': initial,
                     'score': estimate, 'error_bound': error, 'refined': False, 'updates': 0})
    events = []
    while True:
        lower = [r['score']-r['error_bound'] for r in rows]
        upper = [r['score']+r['error_bound'] for r in rows]
        winner = max(range(len(rows)), key=lambda i: (lower[i], -i))
        gap = max(upper)-lower[winner]
        if mode == 'verified_search' and gap <= gap_tolerance:
            break
        eligible = [i for i,r in enumerate(rows) if not r['refined'] and
                    (mode != 'verified_search' or upper[i] > lower[winner]+gap_tolerance)]
        if not eligible:
            require(gap <= gap_tolerance, 'numerical interval unresolved after exact refinements')
            break
        if refinements == max_refinements:
            return {'status':'unresolved', 'selected':None, 'text':None, 'gap_bound':gap,
                    'rows':rows, 'events':events, 'refinements':refinements,
                    'production_promotion_permitted':False}
        i = max(eligible,key=lambda j:(upper[j],-j)); row = rows[i]
        result = solve_newton(p,row['candidate']['x0'],initial=row['y'],tolerance=1e-10)
        row.update(y=result['y'],score=result['y'][0]-row['candidate']['cost'],refined=True,
                   updates=result['newton_updates'],error_bound=result['report']['y_error_bound_exact_arithmetic'])
        refinements += 1
        events.append({'candidate_id':ids[i], 'reason':'upper_bound_can_change_decision' if mode == 'verified_search'
                       else 'complete_precise_control', 'original_error_bound':row['error_bound'],
                       'newton_updates':result['newton_updates']})
    selected = ids[winner]
    return {'status':'resolved', 'selected':selected, 'text':f'Select {selected}.',
            'gap_bound':gap, 'rows':rows, 'events':events, 'refinements':refinements,
            'mode':mode,'candidate_inventory_sha256':digest(candidates),
            'binding':{'scope':scope,'generation':generation,'objective':objective},
            'bank_sha256':None if mode == 'cold_all' else bank.identity,
            'float_roundoff_enclosed':False, 'semantic_correctness_claimed':False,
            'production_promotion_permitted':False}
