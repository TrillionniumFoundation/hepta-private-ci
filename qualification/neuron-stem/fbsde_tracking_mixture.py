"""One hidden Head per story, not a newly sampled Head at every event.

A finite mixture of conditionally independent categorical event models. Exact
conditioning retains cross-event epistemic dependence through the member index.
Within-member independence and the ensemble prior are still MODEL assumptions.
No raw text, source truth, test label or new controller/acceptance authority.
"""
import math
from four_gate_common import digest, require
from fbsde_tracking_control import BeliefProblem

PROFILE = 'shared_head_mixture_v2'


class SharedHeadBelief(BeliefProblem):
    """Bounded conditional-law port for the existing finite BSDE planner.

    p(events) = sum_m w_m product_i q_mi(event_i). Members are never resampled
    after an observation. w_m(history) is recomputed from the ORIGINAL prior
    and ALL distinct observations; repeated calls cannot double count evidence.
    """
    def __init__(self, actors, query, components, weights, binding):
        require(type(components) in (list, tuple) and 1 <= len(components) <= 4,
                'bounded common-Head components')
        require(type(weights) in (list, tuple) and len(weights) == len(components)
                and all(type(w) in (int, float) and math.isfinite(w) and 0 <= w <= 1 for w in weights)
                and abs(math.fsum(weights)-1) < 1e-12, 'mixture prior')
        members = tuple(BeliefProblem(actors, query, rows, binding) for rows in components)
        require(len({len(m.laws) for m in members}) == 1, 'aligned event inventories')
        laws = [[math.fsum(w*m.laws[i][j] for w,m in zip(weights,members))
                 for j in range(len(members[0].pairs))] for i in range(len(members[0].laws))]
        super().__init__(actors, query, laws, binding)
        self.members, self.weights = members, tuple(weights)
        self.identity = digest([PROFILE, actors, query, [m.laws for m in members], self.weights, binding])

    def member_posterior(self, known=()):
        # Base validation checks public coordinates, duplication and marginal
        # support. Joint support is checked BELOW, not inferred from marginals.
        history = super().history(known)
        logs = []
        for w, member in zip(self.weights, self.members):
            ps = [member.laws[i][j] for i,j in history]
            logs.append(math.log(w)+math.fsum(math.log(p) for p in ps)
                        if w > 0 and all(p > 0 for p in ps) else -math.inf)
        peak = max(logs)
        require(math.isfinite(peak), 'observation outside joint model support')
        values = [math.exp(v-peak) for v in logs]
        total = math.fsum(values)
        return tuple(v/total for v in values)

    def history(self, known):
        history = super().history(known)
        self.member_posterior(history)
        return history

    def outcome_law(self, event, known=()):
        require(type(event) is int and 0 <= event < len(self.laws), 'observation event index')
        history = self.history(known)
        if event in dict(history):
            return tuple(float(j == dict(history)[event]) for j in range(len(self.pairs)))
        posterior = self.member_posterior(history)
        return tuple(math.fsum(w*m.laws[event][j] for w,m in zip(posterior,self.members))
                     for j in range(len(self.pairs)))

    def marginal(self, known=()):
        history = self.history(known)
        result = [0.]*self.actors
        for weight, member in zip(self.member_posterior(history), self.members):
            if weight:
                for j,p in enumerate(member.marginal(history)):
                    result[j] += weight*p
        require(abs(math.fsum(result)-1) < 1e-10 and min(result) >= 0,
                'mixture holder probability conservation')
        return result
