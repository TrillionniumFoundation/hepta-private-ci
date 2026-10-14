"""Episode-local version space of exchange-role programs, not new model weights.

One latent omitted mention-role per exact name-normalized frame. This explicit
hypothesis family assumes one unconditional two-person exchange among 3 actors.
It does not establish that arbitrary language belongs to this family. No verifier
result or answer is available during construction. No cross-request learning.
"""
from itertools import product
import math
import re
from four_gate_common import digest, require
from fbsde_tracking_control import BeliefProblem

PROFILE = 'verified_role_program_v1'
PAIRS = ((0, 1), (0, 2), (1, 2))


def describe(text, names):
    """Only alpha-rename actor tokens, retaining all other words and punctuation."""
    require(type(text) is str and 1 <= len(text) <= 2048 and
            type(names) in (list, tuple) and len(names) == len(set(names)) == 3 and
            all(type(n) is str and re.fullmatch('[A-Z][a-z]{1,31}', n) for n in names),
            'bounded public exchange coordinates')
    pattern = r'\b(?:'+'|'.join(map(re.escape, names))+r')\b'
    mentions = re.findall(pattern, text)
    order = tuple(dict.fromkeys(mentions))
    require(len(order) >= 2, 'at least two named roles required')
    order += tuple(n for n in names if n not in order)
    canonical = re.sub(pattern, lambda m: '{R'+str(order.index(m[0]))+'}', text)
    emissions = tuple(PAIRS.index(tuple(sorted(names.index(n) for n in order if n != omitted)))
                      for omitted in order)
    return {'frame': canonical, 'key': digest([PROFILE, canonical]),
            'roles': tuple(names.index(n) for n in order), 'emissions': emissions}


class RoleProgramBelief(BeliefProblem):
    """Finite exact hypothesis expansion; verification eliminates inconsistent rules.

    Hypotheses are omitted-role programs, NOT ensemble members. Frame priors are
    independent across DISTINCT canonical frames. Across repetitions and role
    permutations of one frame the chosen rule is shared. The complete event
    order remains part of the problem; no state update is merged or reordered.
    """
    def __init__(self, query, descriptions, event_laws, binding, *, prior='head', max_worlds=8192):
        require(prior in ('head', 'uniform') and type(max_worlds) is int and 1 <= max_worlds <= 8192,
                'declared role prior and world budget')
        require(type(descriptions) in (list, tuple) and 1 <= len(descriptions) <= 16,
                'bounded description inventory')
        require(len(event_laws) == len(descriptions), 'aligned role inputs')
        require(all(type(d) is dict and set(d) == {'frame','key','roles','emissions'} and
            type(d['frame']) is str and len(d['frame']) <= 2048 and
            digest([PROFILE, d['frame']]) == d['key'] and
            all(type(v) is int for v in d['roles']) and sorted(d['roles']) == [0,1,2] and
            tuple(d['emissions']) == tuple(PAIRS.index(tuple(sorted(v for v in d['roles'] if v != omit)))
                                           for omit in d['roles']) for d in descriptions),
                'declared alpha-renaming and emission identity')
        keys = tuple(d['key'] for d in descriptions)
        emissions = tuple(tuple(d['emissions']) for d in descriptions)
        require(all(type(k) is str and len(k) == 64 and all(c in '0123456789abcdef' for c in k)
                    for k in keys) and all(sorted(row) == [0, 1, 2] for row in emissions),
                'complete role program emissions')
        unique = tuple(dict.fromkeys(keys)); groups = tuple(unique.index(k) for k in keys)
        require(3**len(unique) <= max_worlds, 'role world budget exceeded')
        # Reuse original strict categorical validation, without claiming old independence.
        super().__init__(3, query, event_laws, binding)
        prior_rows = []
        for g in range(len(unique)):
            ids = [i for i, j in enumerate(groups) if j == g]
            # Arithmetic opinion pool, NOT repeated independent likelihood evidence.
            row = tuple(math.fsum(self.laws[i][emissions[i][r]] for i in ids)/len(ids)
                        for r in range(3)) if prior == 'head' else (1/3,)*3
            require(all(x > 0 for x in row), 'role family needs full prior support')
            prior_rows.append(row)
        marginal_laws = [tuple(prior_rows[g][emissions[i].index(j)] for j in range(3))
                         for i, g in enumerate(groups)]
        super().__init__(3, query, marginal_laws, binding)
        self.keys, self.groups, self.emissions = keys, groups, emissions
        self.representatives = tuple(keys.index(k) for k in unique)
        self.priors = tuple(prior_rows)
        worlds = []
        for assigned in product(range(3), repeat=len(unique)):
            logmass = math.fsum(math.log(p[r]) for p, r in zip(self.priors, assigned))
            holder = query
            for i in reversed(range(len(keys))):
                a, b = PAIRS[emissions[i][assigned[groups[i]]]]
                holder = b if holder == a else a if holder == b else holder
            worlds.append((assigned, holder, logmass))
        self.worlds = tuple(worlds)
        self.identity = digest([PROFILE, query, keys, emissions, self.priors, binding])

    def _conditional(self, known):
        history = BeliefProblem.history(self, known); observed = {}
        for event, outcome in history:
            g = self.groups[event]; rule = self.emissions[event].index(outcome)
            require(g not in observed or observed[g] == rule, 'verified frame rule contradiction')
            observed[g] = rule
        compatible = [w for w in self.worlds if all(w[0][g] == r for g, r in observed.items())]
        require(compatible, 'observation outside role program family')
        peak = max(w[2] for w in compatible)
        masses = [math.exp(w[2]-peak) for w in compatible]; total = math.fsum(masses)
        return history, observed, tuple((w, p/total) for w, p in zip(compatible, masses))

    def history(self, known):
        return self._conditional(known)[0]

    def information_state(self, known=()):
        history, observed, worlds = self._conditional(known)
        available = tuple(i for g, i in enumerate(self.representatives) if g not in observed)
        probabilities = [0.]*3; outcomes = {i: [0.]*3 for i in available}
        for (assignment, holder, _), p in worlds:
            probabilities[holder] += p
            for i, row in outcomes.items(): row[self.emissions[i][assignment[self.groups[i]]]] += p
        return {'history': history, 'probabilities': tuple(probabilities), 'available': available,
                'posterior': tuple(p for _, p in worlds),
                'outcomes': {i: tuple(row) for i, row in outcomes.items()}}

    def available_events(self, known=()):
        return list(self.information_state(known)['available'])

    def outcome_law(self, event, known=()):
        require(type(event) is int and 0 <= event < len(self.laws), 'observation event index')
        _, _, worlds = self._conditional(known); result = [0.]*3
        for (assignment, _, _), p in worlds: result[self.emissions[event][assignment[self.groups[event]]]] += p
        return tuple(result)

    def marginal(self, known=()):
        return list(self.information_state(known)['probabilities'])

    def identified_holder(self, known=()):
        """Support unanimity under the declared family, NOT semantic certification."""
        holders = {w[1] for w, _ in self._conditional(known)[2]}
        return next(iter(holders)) if len(holders) == 1 else None
