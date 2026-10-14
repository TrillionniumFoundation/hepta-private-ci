"""Independent integer tables and exact experimental-design reference, no planner import."""
from itertools import permutations, product
from fractions import Fraction as F
from four_gate_common import require

STATES=tuple(permutations(range(3)))
TRANS=tuple(i for i,p in enumerate(STATES) if sum(a!=b for a,b in enumerate(p))==2)
RULES=tuple((-1,-1,i) for i in range(6))+tuple(product(range(3),range(3),TRANS))


def source_effect(rule_index,state):
    """Private simulator primitive; never provided to the experimental policy."""
    role,colour,op=RULES[rule_index]
    return STATES[op] if role<0 or state[role]==colour else (0,1,2)


def tables():
    return tuple(tuple(STATES.index(source_effect(i,state)) for state in STATES) for i in range(len(RULES)))


def support(history):
    result=tuple(i for i,row in enumerate(tables()) if all(row[s]==o for s,o in history))
    require(result,'outside reference family');return result


def agreement(ids):
    t=tables(); result=[]
    for s in range(6):
        values=set(t[i][s] for i in ids);result.append(min(values) if len(values)==1 else None)
    return tuple(result)


def choose(history,horizon):
    """Full conditional outcome enumeration with exact rational costs and ties."""
    t=tables()
    def recurse(fn,ids,depth):
        known=agreement(ids);best=F(sum(v is not None for v in known),6);action=None
        if depth:
            for s in range(6):
                if known[s] is not None:continue
                bins=[tuple(i for i in ids if t[i][s]==o) for o in range(6)]
                value=sum((F(len(b),len(ids))*fn(fn,b,depth-1)[0] for b in bins if b),F(0))-F(1,50)
                if value>best:best,action=value,s
        return best,action
    return recurse(recurse,support(history),horizon)


def fixed_pair():
    t=tables();choices=[]
    for a in range(6):
        for b in range(a+1,6):
            groups={}
            for i,row in enumerate(t):groups.setdefault((row[a],row[b]),[]).append(i)
            value=sum((F(len(g),len(t))*F(sum(x is not None for x in agreement(g)),6) for g in groups.values()),F(0))
            choices.append((value,(a,b)))
    return max(choices,key=lambda r:(r[0],tuple(-i for i in r[1])))[1]


def identification_ceiling():
    """Post-score existential bound over EVERY two-probe path, not a policy oracle.

    An adaptive two-query policy follows one pair on each true world. Enumerating
    every pair (including repeats) per world bounds ANY such policy's identification.
    """
    t=tables(); witnesses={}
    for r,row in enumerate(t):
        hits=[]
        for a in range(6):
            for b in range(6):
                ids=tuple(i for i,other in enumerate(t) if (other[a],other[b])==(row[a],row[b]))
                if len({t[i] for i in ids})==1:hits.append([a,b])
        witnesses[str(r)]=hits
    return dict(two_probe_identifiable_rules=[int(k) for k,v in witnesses.items() if v],
        total_rules=len(t),pairs_per_rule=36,witnesses=witnesses,posthoc_diagnostic_only=True,
        scope='two_selected_single_step_reset_effects_over_six_states_in_this_exact_family')
