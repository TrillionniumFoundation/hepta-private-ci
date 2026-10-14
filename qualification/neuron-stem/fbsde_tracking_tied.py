"""One latent interpretation per declared input identity, across its repetitions.

Exact finite Bayesian model, not a calibrated posterior or semantic certificate.
An input identity must include source meaning, actor coordinates and model/scope;
equal embeddings alone never authorize tying. Distinct keys remain conditionally
independent within a member. World expansion is bounded BEFORE materialization.
"""
from itertools import product
import math
from four_gate_common import digest, require
from fbsde_tracking_control import BeliefProblem
from fbsde_tracking_mixture import SharedHeadBelief

PROFILE = 'input_tied_epistemic_v1'


class InputTiedBelief(SharedHeadBelief):
    def __init__(self, actors, query, components, weights, keys, binding, *, max_worlds=8192):
        super().__init__(actors, query, components, weights, binding)
        require(type(max_worlds) is int and 1 <= max_worlds <= 8192, 'bounded world limit')
        require(type(keys) in (list, tuple) and len(keys) == len(self.laws) and
                all(type(k) is str and len(k) == 64 and all(c in '0123456789abcdef' for c in k)
                    for k in keys), 'full input identities required')
        self.keys = tuple(keys)
        unique = tuple(dict.fromkeys(keys))
        self.groups = tuple(unique.index(k) for k in keys)
        self.representatives = tuple(keys.index(k) for k in unique)
        # A declared shared latent input must have identical per-member distributions.
        for member in self.members:
            for i, g in enumerate(self.groups):
                require(member.laws[i] == member.laws[self.representatives[g]],
                        'same input identity has inconsistent law')
        supports = []
        size = 0
        for w, member in zip(self.weights, self.members):
            rows = [tuple(j for j,p in enumerate(member.laws[i]) if p > 0)
                    for i in self.representatives]
            size += math.prod(map(len, rows)) if w else 0
            supports.append(rows)
        require(size <= max_worlds, 'input-tied world budget exceeded')
        worlds = []
        for m, (w, member, choices) in enumerate(zip(self.weights, self.members, supports)):
            if not w:
                continue
            for assigned in product(*choices):
                logmass = math.log(w) + math.fsum(math.log(member.laws[i][j])
                                                 for i,j in zip(self.representatives, assigned))
                holder = query
                for g in reversed(self.groups):
                    a,b = self.pairs[assigned[g]]
                    holder = b if holder == a else a if holder == b else holder
                worlds.append((m, assigned, holder, logmass))
        self.worlds = tuple(worlds)
        self.identity = digest([PROFILE, actors, query, components, weights, keys, binding])

    def _conditional(self, known):
        history = BeliefProblem.history(self, known)
        observed = {}
        for event, outcome in history:
            g = self.groups[event]
            require(g not in observed or observed[g] == outcome,
                    'contradictory repeated-input observations')
            observed[g] = outcome
        compatible = [w for w in self.worlds if all(w[1][g] == j for g,j in observed.items())]
        require(compatible, 'observation outside joint model support')
        peak = max(w[3] for w in compatible)
        masses = [math.exp(w[3]-peak) for w in compatible]
        total = math.fsum(masses)
        return history, observed, tuple((w, p/total) for w,p in zip(compatible,masses))

    def history(self, known):
        return self._conditional(known)[0]

    def available_events(self, known=()):
        observed = self._conditional(known)[1]
        return [i for g,i in enumerate(self.representatives) if g not in observed]

    def member_posterior(self, known=()):
        result = [0.]*len(self.members)
        for w,p in self._conditional(known)[2]:
            result[w[0]] += p
        return tuple(result)

    def outcome_law(self, event, known=()):
        require(type(event) is int and 0 <= event < len(self.laws), 'observation event index')
        result = [0.]*len(self.pairs)
        for w,p in self._conditional(known)[2]:
            result[w[1][self.groups[event]]] += p
        return tuple(result)

    def marginal(self, known=()):
        result = [0.]*self.actors
        for w,p in self._conditional(known)[2]:
            result[w[2]] += p
        require(abs(math.fsum(result)-1) < 1e-10, 'tied holder conservation')
        return result

    def information_state(self, known=()):
        """One conditional-world reduction for a decision-local planner snapshot.

        No extra observation or inference is introduced. Each sum visits the
        SAME normalized worlds in the SAME order as the individual ports.
        Arrays are fresh and contain no source labels or model objects.
        """
        history, observed, worlds = self._conditional(known)
        available = tuple(i for g,i in enumerate(self.representatives) if g not in observed)
        probabilities = [0.]*self.actors
        posterior = [0.]*len(self.members)
        outcomes = {i:[0.]*len(self.pairs) for i in available}
        for world, p in worlds:
            probabilities[world[2]] += p
            posterior[world[0]] += p
            for event, values in outcomes.items():
                values[world[1][self.groups[event]]] += p
        require(abs(math.fsum(probabilities)-1) < 1e-10, 'tied holder conservation')
        return {'history': history, 'probabilities': tuple(probabilities),
                'available': available, 'posterior': tuple(posterior),
                'outcomes': {i:tuple(values) for i,values in outcomes.items()}}
