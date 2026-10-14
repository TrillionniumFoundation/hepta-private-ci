"""Use the existing finite planner; learn programs only from selected effects."""
import time
from four_gate_common import digest, require
from fbsde_conditional_program import ConditionalProgramBelief, OPS
from fbsde_planning_workspace import PlanningWorkspace
from fbsde_tracking_control import PlanningBudgetError

ARMS = ('constant_two','conditional_one','conditional_two','conditional_probe',
        'conditional_no_checks','event_probe','legacy_expand_audit','exact')


def execute(public, arm, reveal):
    require(arm in ARMS[:5], 'conditional executor arm')
    started=time.process_time_ns(); build=started
    problem=ConditionalProgramBelief(public,family='constant' if arm=='constant_two' else 'conditional')
    build_cpu=time.process_time_ns()-build
    if build_cpu>100_000_000: raise PlanningBudgetError('conditional construction CPU budget',problem,0,build)
    h=(); checks=[]; decisions=[]; holder=None; reason=None; distribution=None
    for _ in range(3):
        begin=time.process_time_ns()
        with PlanningWorkspace(problem,h) as w:
            p=w.marginal(h); available=w.available_events(h); d=None
            if arm=='conditional_probe':
                support=[j for j,q in enumerate(p) if q>0]
                action=f'answer:{support[0]}' if len(support)==1 else f'verify:{available[0]}' if available and len(checks)<2 else 'abstain'
            else:
                depth=0 if arm=='conditional_no_checks' else min(2-len(checks),1 if arm=='conditional_one' else 2)
                d=w.solve(h,horizon=depth); action=d['action']
            posterior=problem.posterior_summary(h)
        cpu=time.process_time_ns()-begin
        if cpu>100_000_000: raise PlanningBudgetError('conditional decision CPU budget',problem,w.nodes,begin)
        decisions.append(dict(action=action,known=h,probabilities=p,plan=d,posterior=posterior,
            cpu_ns=cpu,nodes=w.nodes,problem_sha256=problem.identity))
        if not action.startswith('verify:'):
            holder=None if action=='abstain' else int(action.split(':')[1]); distribution=p
            reason='conditional_family_answer' if holder is not None else 'insufficient_support';break
        event=int(action.split(':')[1]);require(event in available and len(checks)<2, 'paid available event')
        begin=time.process_time_ns(); receipt=reveal(event,h)
        require(type(receipt) is dict and set(receipt)=={'effect','source_sha256','event_sha256','known_sha256'} and
                receipt['source_sha256']==digest(public) and receipt['event_sha256']==digest(public['events'][event]) and
                receipt['known_sha256']==digest(h), 'bound selected observation')
        effect=receipt['effect']
        require(type(effect) in (tuple,list) and len(effect)==3 and all(type(j) is int and 0<=j<3 for j in effect),'typed effect')
        checks.append(dict(event=event,receipt=receipt,known_before=h,cpu_ns=time.process_time_ns()-begin))
        if tuple(effect) not in OPS: reason='unsupported_nonbijective_effect';break
        nxt=tuple(sorted(h+((event,OPS.index(tuple(effect))),)))
        try: problem.history(nxt)
        except ValueError as error:
            if str(error)!='observations outside conditional family':raise
            reason='outside_conditional_family';break
        h=nxt
    else: raise ValueError('unfinished conditional decision')
    return dict(arm=arm,source_id=public['source_id'],holder=holder,
        text='Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder],
        probabilities=distribution,checks=checks,decisions=decisions,final_known=h,reason=reason,
        problem_sha256=problem.identity,build_cpu_ns=build_cpu,cpu_ns=time.process_time_ns()-started,
        semantic_certificate=False,production_promotion_permitted=False)
