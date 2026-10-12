"""Selected-effect observations and bounded revisions; not source authority."""
import time
from four_gate_common import digest, require
from fbsde_effect_family import EffectFamily, FamilyConflict, EFFECTS, ALL
from fbsde_planning_workspace import PlanningWorkspace
from fbsde_tracking_control import PlanningBudgetError

ARMS = ('swap_two','swap_probe','expand_two','expand_audit','permutation_one',
        'permutation_two','permutation_probe','event_probe','exact')


def execute(public, arm, reveal):
    require(arm in ARMS and arm != 'exact', 'registered policy')
    start = time.process_time_ns(); n = len(public['events']); build = time.process_time_ns()
    grouping = 'event' if arm == 'event_probe' else 'frame'
    initial = EffectFamily(public, grouping=grouping)
    if arm.startswith('permutation') or arm == 'event_probe':
        initial = EffectFamily(public, grouping=grouping, supports=(ALL,)*len(initial.supports))
    problem = initial; build_cpu = time.process_time_ns()-build
    known=(); checks=[]; decisions=[]; revisions=[]; reason=None; holder=None; distribution=None
    for turn in range(3):
        begin=time.process_time_ns()
        with PlanningWorkspace(problem,known) as workspace:
            p=workspace.marginal(known); available=workspace.available_events(known)
            unqueried=[i for i in range(n) if i not in dict(known)]
            forced=turn == 0 and arm in ('swap_probe','expand_two','expand_audit')
            repeat=arm == 'expand_audit' and turn == 1 and any(problem.groups[i] == problem.groups[checks[0]['event']] for i in unqueried)
            result=None
            if forced: action='verify:0'
            elif repeat:
                e=next(i for i in reversed(unqueried) if problem.groups[i] == problem.groups[checks[0]['event']]);action=f'verify:{e}'
            elif arm.endswith('probe'):
                possible=[j for j,v in enumerate(p) if v > 0]
                action=f'answer:{possible[0]}' if len(possible)==1 else f'verify:{available[0]}' if available and len(checks)<2 else 'abstain'
            else:
                result=workspace.solve(known,horizon=min(2-len(checks),1 if arm=='permutation_one' else 2));action=result['action']
        cpu=time.process_time_ns()-begin
        if cpu>100_000_000: raise PlanningBudgetError('family decision CPU budget exhausted',problem,workspace.nodes,begin)
        decisions.append(dict(known=known,action=action,plan=result,probabilities=p,problem_sha256=problem.identity,
                              nodes=workspace.nodes,cpu_ns=cpu,forced=forced,repeat_audit=repeat))
        if not action.startswith('verify:'):
            holder=None if action=='abstain' else int(action.split(':')[1]); distribution=p; reason='family_conditional_answer' if holder is not None else 'insufficient_support';break
        e=int(action.split(':')[1]); require(e in unqueried and len(checks)<2, 'no reset of verification budget')
        before=time.process_time_ns(); raw=reveal(e,known)
        require(type(raw) is dict and set(raw)=={'effect','source_sha256','event_sha256','known_sha256'} and
                raw['source_sha256']==digest(public) and raw['event_sha256']==digest(public['events'][e]) and
                raw['known_sha256']==digest(known), 'bound selected observation')
        checks.append(dict(event=e,receipt=raw,known_before=known,cpu_ns=time.process_time_ns()-before))
        effect=raw['effect']
        require(type(effect) in (tuple,list) and len(effect)==3 and all(type(v) is int and v in range(3) for v in effect), 'typed effect')
        if tuple(effect) not in EFFECTS: reason='unsupported_nonbijective_effect';break
        next_known=tuple(sorted(known+((e,EFFECTS.index(tuple(effect))),)))
        before=time.process_time_ns()
        try: problem.history(next_known)
        except FamilyConflict as conflict:
            if arm not in ('expand_two','expand_audit'):
                reason=conflict.kind;break
            if conflict.kind=='frame_conflict' and arm!='expand_audit':reason=conflict.kind;break
            old=problem
            candidate=problem.revise(next_known,allow_event_split=arm=='expand_audit')
            elapsed=time.process_time_ns()-before; build_cpu+=elapsed
            if elapsed>100_000_000: raise PlanningBudgetError('family revision CPU budget exhausted',old,0,before)
            revisions.append(dict(reason=conflict.kind,from_sha256=old.identity,to_sha256=candidate.identity,
                history_sha256=digest(next_known),supports=candidate.supports,grouping=candidate.grouping,
                revision=candidate.revision,remaining_checks=2-len(checks),cpu_ns=elapsed))
            problem=candidate
        known=next_known
    else: raise ValueError('unfinished bounded family policy')
    return dict(arm=arm,source_id=public['source_id'],holder=holder,
        text='Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder],
        probabilities=distribution,checks=checks,decisions=decisions,revisions=revisions,reason=reason,
        initial_sha256=initial.identity,final_sha256=problem.identity,final_known=known,
        build_cpu_ns=build_cpu,cpu_ns=time.process_time_ns()-start,semantic_certificate=False,
        production_promotion_permitted=False)
