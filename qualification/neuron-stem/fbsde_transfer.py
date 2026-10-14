"""Choose controlled initial-state probes before exporting a rule on a finite domain.

This is finite experiment design, not a new neural model, acceptance service or
permission to intervene on a real environment. Source effects enter only AFTER
selecting a reset experiment. Domain agreement is conditional on family coverage.
"""
from dataclasses import dataclass
import math
import time
from four_gate_common import digest, require
from fbsde_conditional_program import PROGRAMS, OPS, transition
from fbsde_role_program import describe

PROFILE = 'counterfactual_rule_transfer_v1'
COST = .02  # Per source experiment utility, not CPU/energy currency.
MODES = ('map_without_evidence', 'support_only', 'fixed_two', 'best_fixed_two',
         'first_informative', 'myopic_two', 'active_two', 'full_table_six')


@dataclass(frozen=True)
class TransferProblem:
    frame: str
    binding: str
    identity: str
    table: tuple
    context_id: str

    @classmethod
    def build(cls, public, context):
        require(type(public) is dict and set(public)=={'source_id','names','event'}, 'public probe fields')
        require(type(public['source_id']) is str and 0<len(public['source_id'])<=256, 'source identity')
        require(type(context) is dict and set(context)=={'scope','generation','environment'} and
                all(type(context[k]) is str and context[k] for k in ('scope','environment')) and
                type(context['generation']) is int and context['generation']>0, 'transfer context')
        desc = describe(public['event'], public['names'])
        # Domain coordinates are mention roles, not literal actor names.
        table = tuple(tuple(OPS.index(transition(rule,(0,1,2),state)[0]) for state in OPS)
                      for rule in PROGRAMS)
        binding = digest([public,context])
        return cls(desc['key'],binding,digest([PROFILE,binding,desc['key'],table]),table,digest(context))

    def support(self, history=()):
        require(type(history) is tuple and len(history)<=6 and all(type(r) is tuple and len(r)==2 and
                all(type(x) is int and 0<=x<6 for x in r) for r in history), 'typed probe history')
        result=tuple(i for i,row in enumerate(self.table) if all(row[s]==o for s,o in history))
        require(result, 'observations outside transfer family')
        return result

    def agreement(self, support):
        return tuple(next(iter(v)) if len(v)==1 else None
                     for v in ({self.table[i][s] for i in support} for s in range(6)))

    def choose(self, history, horizon, *, max_nodes=20000):
        require(type(horizon) is int and 0<=horizon<=2 and type(max_nodes) is int and
                1<=max_nodes<=20000, 'bounded probe planning')
        started=time.process_time_ns();nodes=0
        initial=self.support(history)
        # Cache belongs to this call and is cleared in finally, including failures.
        memo={}
        def visit(recurse, support, depth):
            nonlocal nodes
            key=(support,depth)
            if key in memo:return memo[key]
            nodes+=1
            require(nodes<=max_nodes and time.process_time_ns()-started<=100_000_000, 'probe planner budget')
            agreed=self.agreement(support)
            best=sum(x is not None for x in agreed)/6; action=None
            if depth:
                for s in range(6):
                    if agreed[s] is not None:continue
                    children=[tuple(i for i in support if self.table[i][s]==o) for o in range(6)]
                    value=math.fsum(len(child)/len(support)*recurse(recurse,child,depth-1)[0]
                                    for child in children if child)-COST
                    if value>best+1e-12:best,action=value,s
            memo[key]=(best,action)
            return memo[key]
        try:
            value,action=visit(visit,initial,horizon)
        finally:
            memo.clear()
        elapsed=time.process_time_ns()-started
        require(elapsed<=100_000_000,'probe planner budget')
        return dict(state_index=action,value=value,nodes=nodes,cpu_ns=elapsed,
                    history_sha256=digest(history),problem_sha256=self.identity)

    def best_fixed(self):
        """Exact best nonadaptive pair under the SAME prior; no source outcomes."""
        choices=[]
        for a in range(6):
            for b in range(a+1,6):
                buckets={}
                for i,row in enumerate(self.table):buckets.setdefault((row[a],row[b]),[]).append(i)
                quality=math.fsum(len(ids)/len(self.table)*sum(x is not None for x in self.agreement(ids))/6
                                  for ids in buckets.values())
                choices.append((quality,(a,b)))
        return max(choices,key=lambda x:(x[0],tuple(-i for i in x[1])))[1]


@dataclass(frozen=True)
class TransferTable:
    """Only exported for full-domain agreement; carries scope AND evidence identity."""
    frame: str
    context: str
    effects: tuple
    evidence: str

    @classmethod
    def from_support(cls, problem, history, context):
        values=problem.agreement(problem.support(history))
        require(all(x is not None for x in values),'unresolved transferable rule')
        require(type(context) is dict and context['binding']==problem.binding and
                set(context)=={'binding','scope','generation','environment'} and
                digest({k:v for k,v in context.items() if k!='binding'})==problem.context_id,'table export context')
        return cls(problem.frame,digest(context),values,digest([problem.identity,history]))

    def snapshot(self):
        return dict(frame=self.frame,context=self.context,effects=list(self.effects),evidence=self.evidence)

    @classmethod
    def restore(cls, saved, problem, history, context):
        expected=cls.from_support(problem,history,context)
        require(type(saved) is dict and saved==expected.snapshot(), 'table/evidence reconstruction mismatch')
        return expected

    def apply(self, text, names, state, context):
        require(digest(context)==self.context,'stale or foreign transfer context')
        d=describe(text,names);require(d['key']==self.frame,'different rule frame')
        require(type(state) is tuple and all(type(x) is int for x in state) and state in OPS,'transfer state domain')
        roles=d['roles'];normalized=tuple(state[j] for j in roles)
        op=OPS[self.effects[OPS.index(normalized)]]
        effect=tuple(roles[op[roles.index(j)]] for j in range(3))
        return tuple(state[j] for j in effect)


def execute(problem, mode, reveal, *, first_state=0):
    require(mode in MODES and type(first_state) is int and 0<=first_state<6,'probe mode/state')
    started=time.process_time_ns();history=();records=[];decisions=[];failure=None
    limit=6 if mode=='full_table_six' else 0 if mode in MODES[:2] else 2
    fixed=problem.best_fixed() if mode=='best_fixed_two' else (first_state,(first_state+1)%6)
    require(time.process_time_ns()-started<=100_000_000,'probe preparation budget')
    for k in range(limit):
        before=time.process_time_ns();support=problem.support(history);agreed=problem.agreement(support)
        decision=None
        if mode in ('fixed_two','best_fixed_two'):s=fixed[k]
        elif mode=='full_table_six':s=k
        elif mode=='first_informative':s=next((i for i,x in enumerate(agreed) if x is None),None)
        else:
            decision=problem.choose(history,1 if mode=='myopic_two' else limit-k);s=decision['state_index']
        cpu=time.process_time_ns()-before
        require(cpu<=100_000_000,'probe decision budget')
        decisions.append(dict(state_index=s,history_sha256=digest(history),cpu_ns=cpu,plan=decision))
        if s is None:break
        request=dict(problem_sha256=problem.identity,binding=problem.binding,state=OPS[s],
                     sequence=len(records),history_sha256=digest(history),protocol='controlled_reset_v1')
        before=time.process_time_ns();receipt=reveal(request)
        valid=type(receipt) is dict and set(receipt)=={'request_sha256','effect'} and receipt['request_sha256']==digest(request)
        require(valid,'bound controlled experiment receipt')
        effect=receipt['effect']
        require(type(effect) in (tuple,list) and len(effect)==3 and all(type(x) is int and 0<=x<3 for x in effect),'typed effect receipt')
        records.append(dict(request=request,receipt=receipt,cpu_ns=time.process_time_ns()-before))
        if tuple(effect) not in OPS:failure='unsupported_nonbijective_effect';break
        history=history+((s,OPS.index(tuple(effect))),)
        try:problem.support(history)
        except ValueError:
            failure='outside_transfer_family';break
    support=() if failure else problem.support(history)
    agreed=(None,)*6 if failure else problem.agreement(support)
    predictions=problem.table[support[0]] if mode=='map_without_evidence' else agreed
    # Output agreement, not a singleton guess, controls transfer qualification.
    return dict(mode=mode,history=history,records=records,decisions=decisions,support=support,
                agreed=agreed,predictions=predictions,identified=all(x is not None for x in agreed),
                failure=failure,problem_sha256=problem.identity,checks_limit=limit,
                cpu_ns=time.process_time_ns()-started,family_coverage_authenticated=False,
                semantic_certificate=False,production_promotion_permitted=False)
