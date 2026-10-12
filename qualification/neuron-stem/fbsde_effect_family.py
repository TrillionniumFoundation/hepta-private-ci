"""Bounded effect hypotheses with explicit, replayed family revisions.

Effects are pullback permutations: new_state[j] = old_state[effect[j]].
Frame invariance is an assumption. An accepted observation is evidence about
ONE execution, not certification that a language frame is state-independent.
"""
from itertools import permutations, product
import math
from four_gate_common import digest, require
from fbsde_role_program import describe

PROFILE = 'effect_family_revision_v1'
EFFECTS = tuple(permutations(range(3)))
SWAPS = tuple(i for i, p in enumerate(EFFECTS) if sum(j != p[j] for j in range(3)) == 2)
ALL = tuple(range(6))


class FamilyConflict(ValueError):
    def __init__(self, kind, group):
        super().__init__(kind)
        self.kind, self.group = kind, group


class EffectFamily:
    """One uniform latent role-effect per frame (or, explicitly, per event).

    Every constructor preflights the expanded product. Revision changes the
    problem identity, never a cached object; all revealed evidence is replayed.
    """
    def __init__(self, public, *, grouping='frame', supports=None, revision=0, max_worlds=8192):
        require(type(public) is dict and set(public) == {'source_id','names','query','events'}, 'public fields only')
        require(type(public['query']) is int and 0 <= public['query'] < 3 and
                type(public['source_id']) is str and 0 < len(public['source_id']) <= 256 and
                type(public['events']) in (list,tuple) and 1 <= len(public['events']) <= 16, 'bounded public task')
        require(grouping in ('frame','event') and type(revision) is int and revision >= 0 and
                type(max_worlds) is int and 1 <= max_worlds <= 8192, 'bounded declared family')
        self.descriptions = tuple(describe(t, public['names']) for t in public['events'])
        keys = tuple(d['key'] if grouping == 'frame' else digest([d['key'],i]) for i,d in enumerate(self.descriptions))
        unique = tuple(dict.fromkeys(keys)); self.groups = tuple(unique.index(k) for k in keys)
        self.representatives = tuple(keys.index(k) for k in unique)
        supports = (SWAPS,)*len(unique) if supports is None else tuple(tuple(s) for s in supports)
        require(len(supports) == len(unique) and all(s and tuple(sorted(set(s))) == s and
                all(type(v) is int and v in ALL for v in s) for s in supports), 'complete finite program supports')
        require(math.prod(map(len,supports)) <= max_worlds, 'family world budget exceeded')
        # Each row maps a ROLE permutation index to its ACTOR permutation index.
        emissions = []
        for d in self.descriptions:
            roles = d['roles']; row = []
            for p in EFFECTS:
                actual = [0]*3
                for j in range(3): actual[roles[j]] = roles[p[j]]
                row.append(EFFECTS.index(tuple(actual)))
            emissions.append(tuple(row))
        self.emissions, self.supports = tuple(emissions), supports
        self.max_worlds = max_worlds
        self.public = {**public, 'names':tuple(public['names']), 'events':tuple(public['events'])}
        self.actors, self.query, self.grouping, self.revision = 3, public['query'], grouping, revision
        self.pairs = EFFECTS  # Existing planner uses its length as the observation alphabet.
        self.laws = tuple(tuple(sum(self.emissions[i][r] == o for r in supports[g])/len(supports[g])
                                for o in ALL) for i,g in enumerate(self.groups))
        self.binding = digest(dict(source=digest(public), model=PROFILE, calibration='uniform-assumed',
                                   scope='effect-family-research', generation=1))
        self.identity = digest([self.binding, grouping, supports, revision, self.emissions])
        worlds = []
        for assignment in product(*supports):
            holder = self.query
            for i in reversed(range(len(keys))): holder = EFFECTS[self.emissions[i][assignment[self.groups[i]]]][holder]
            worlds.append((assignment,holder))
        self.worlds = tuple(worlds)

    def _observed(self, known):
        require(type(known) is tuple and len(known) <= len(self.laws) and all(type(r) is tuple and
            len(r) == 2 and type(r[0]) is int and 0 <= r[0] < len(self.laws) and
            type(r[1]) is int and r[1] in ALL for r in known) and
            len({r[0] for r in known}) == len(known), 'unique typed observation history')
        observed = {}
        for i,o in sorted(known):
            g = self.groups[i]; rule = self.emissions[i].index(o)
            if g in observed and observed[g] != rule: raise FamilyConflict('frame_conflict',g)
            observed[g] = rule
        return observed

    def history(self, known):
        observed = self._observed(known)
        for g,r in observed.items():
            if r not in self.supports[g]: raise FamilyConflict('outside_effect_family',g)
        return tuple(sorted(known))

    def information_state(self, known=()):
        history = self.history(known); observed = self._observed(history)
        worlds = [w for w in self.worlds if all(w[0][g] == r for g,r in observed.items())]
        available = tuple(i for g,i in enumerate(self.representatives) if g not in observed)
        n = len(worlds)
        probabilities = tuple(sum(holder == j for _,holder in worlds)/n for j in range(3))
        outcomes = {i:tuple(sum(self.emissions[i][a[self.groups[i]]] == o for a,_ in worlds)/n
                           for o in ALL) for i in available}
        return dict(history=history, probabilities=probabilities, available=available,
                    posterior=(1/n,)*n, outcomes=outcomes)

    def marginal(self, known=()): return list(self.information_state(known)['probabilities'])
    def available_events(self, known=()): return list(self.information_state(known)['available'])

    def outcome_law(self, event, known=()):
        require(type(event) is int and 0 <= event < len(self.laws), 'event domain')
        self.history(known); observed = self._observed(known)
        worlds = [a for a,_ in self.worlds if all(a[g] == r for g,r in observed.items())]
        return tuple(sum(self.emissions[event][a[self.groups[event]]] == o for a in worlds)/len(worlds) for o in ALL)

    def revise(self, known, *, allow_event_split=False):
        """Only contradictory observations authorize widening; never reset evidence."""
        require(type(allow_event_split) is bool, 'explicit split permission')
        try: observed = self._observed(known)
        except FamilyConflict:
            require(allow_event_split and self.grouping == 'frame', 'frame conflict requires explicit fallback')
            candidate = EffectFamily(self.public, grouping='event', supports=(ALL,)*len(self.laws), revision=self.revision+1, max_worlds=self.max_worlds)
        else:
            supports = tuple(ALL if g in observed and observed[g] not in s else s for g,s in enumerate(self.supports))
            require(supports != self.supports, 'no evidence-authorized expansion')
            candidate = EffectFamily(self.public, grouping=self.grouping, supports=supports, revision=self.revision+1, max_worlds=self.max_worlds)
        candidate.history(known)  # Replay ALL observations before publishing the new identity.
        return candidate
