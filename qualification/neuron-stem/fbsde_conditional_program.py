"""Episode-local induction of state-dependent role programs, not neural fitting.

Every candidate rolls its OWN predecessor states forward. A selected effect
filters the complete trajectory, including latent predecessors; no true state is
injected. The prior is uniform over an explicitly bounded program family.
"""
from itertools import permutations, product
import math
from four_gate_common import digest, require
from fbsde_role_program import describe

PROFILE = 'conditional_program_induction_v1'
OPS = tuple(permutations(range(3)))
SWAPS = tuple(i for i,p in enumerate(OPS) if sum(j != p[j] for j in range(3)) == 2)
# (guard role, required colour, true effect); -1 is an unconditional effect.
PROGRAMS = tuple((-1,-1,i) for i in range(6)) + tuple(product(range(3),range(3),SWAPS))


def transition(rule, roles, state):
    r, colour, op = rule
    active = r == -1 or state[roles[r]] == colour
    effect = tuple(roles[OPS[op][roles.index(j)]] for j in range(3)) if active else (0,1,2)
    return effect, tuple(state[j] for j in effect)


class ConditionalProgramBelief:
    """A latent program per exact alpha-renamed frame, not a constant effect.

    Static and conditional effects share the original six-effect observation
    alphabet. An informative event is NOT removed just because its frame was
    checked once. Conditional unanimity still requires true-family coverage.
    """
    def __init__(self, public, *, family='conditional', initial=(0,1,2), max_worlds=8192):
        require(type(public) is dict and set(public)=={'source_id','names','query','events'}, 'public fields only')
        require(type(public['source_id']) is str and 0<len(public['source_id'])<=256 and
                type(public['query']) is int and 0<=public['query']<3 and
                type(public['events']) in (list,tuple) and 1<=len(public['events'])<=16, 'bounded public task')
        require(type(initial) is tuple and all(type(x) is int for x in initial) and initial in OPS,
                'public permutation initial state')
        require(family in ('constant','conditional') and type(max_worlds) is int and
                1<=max_worlds<=8192, 'bounded program family')
        self.descriptions = tuple(describe(t,public['names']) for t in public['events'])
        keys = tuple(d['key'] for d in self.descriptions); unique = tuple(dict.fromkeys(keys))
        self.groups = tuple(unique.index(k) for k in keys)
        self.programs = PROGRAMS[:6] if family=='constant' else PROGRAMS
        require(len(self.programs)**len(unique)<=max_worlds, 'conditional world budget exceeded')
        self.initial, self.family, self.max_worlds = initial, family, max_worlds
        self.actors, self.query, self.pairs = 3, public['query'], OPS
        self.binding = digest(dict(source=digest(public),initial=initial,model=PROFILE,
            calibration='uniform-program-assumption',scope='conditional-program-research',generation=1))
        self.identity = digest([self.binding,family,self.programs,keys,self.groups])
        worlds = []
        for assigned in product(range(len(self.programs)),repeat=len(unique)):
            state = initial; effects = []; states = [state]
            for d,g in zip(self.descriptions,self.groups):
                effect,state = transition(self.programs[assigned[g]],d['roles'],state)
                effects.append(OPS.index(effect)); states.append(state)
            worlds.append((assigned,tuple(effects),tuple(states)))
        self.worlds = tuple(worlds)
        self.laws = tuple(tuple(sum(w[1][i]==j for w in worlds)/len(worlds) for j in range(6))
                          for i in range(len(keys)))

    def _consistent(self, known):
        require(type(known) is tuple and len(known)<=len(self.laws) and all(type(r) is tuple and
                len(r)==2 and type(r[0]) is int and 0<=r[0]<len(self.laws) and
                type(r[1]) is int and 0<=r[1]<6 for r in known) and
                len({r[0] for r in known})==len(known), 'typed unique effect history')
        history = tuple(sorted(known))
        worlds = tuple(w for w in self.worlds if all(w[1][i]==j for i,j in history))
        require(worlds, 'observations outside conditional family')
        return history,worlds

    def history(self, known): return self._consistent(known)[0]

    def information_state(self, known=()):
        history,worlds = self._consistent(known); count = len(worlds)
        values = [0]*3; outcomes = {i:[0]*6 for i in range(len(self.laws)) if i not in dict(history)}
        for _,effects,states in worlds:
            values[states[-1][self.query]] += 1
            for i,counts in outcomes.items(): counts[effects[i]] += 1
        # Skip only already-determined effects, not all instances of one frame.
        available = tuple(i for i,c in outcomes.items() if sum(v>0 for v in c)>1)
        return dict(history=history,probabilities=tuple(v/count for v in values),
            available=available,posterior=(1/count,)*count,
            outcomes={i:tuple(v/count for v in outcomes[i]) for i in available})

    def marginal(self, known=()): return list(self.information_state(known)['probabilities'])
    def available_events(self, known=()): return list(self.information_state(known)['available'])

    def outcome_law(self, event, known=()):
        require(type(event) is int and 0<=event<len(self.laws), 'event domain')
        _,worlds = self._consistent(known)
        return tuple(sum(w[1][event]==j for w in worlds)/len(worlds) for j in range(6))

    def posterior_summary(self, known=()):
        history,worlds = self._consistent(known)
        support = tuple(tuple(sorted({w[0][g] for w in worlds})) for g in range(max(self.groups)+1))
        return dict(history_sha256=digest(history),compatible_worlds=len(worlds),program_support=support,
                    program_set_identified=all(len(s)==1 for s in support),semantic_certificate=False)
