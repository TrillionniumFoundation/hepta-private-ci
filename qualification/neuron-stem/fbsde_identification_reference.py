"""Independent rational experiment design over parent's independently compiled tables.

No runtime learner, policy, transition or transfer object is imported. Bit-mask
partitions and exact fractions check the integer Bellman compiler and its bound.
"""
from fractions import Fraction as F
from itertools import permutations
from four_gate_common import require
from fbsde_transfer_reference import tables, STATES, source_effect, agreement, support, choose


class Reference:
    def __init__(self):
        self.table = tables(); self.memo = {}; self.fixed = {}
        self.masks = [[sum(1 << i for i,r in enumerate(self.table) if r[s] == o) for o in range(6)] for s in range(6)]

    def optimal(self, mask, budget):
        key = mask,budget
        if key in self.memo: return self.memo[key]
        ids = [i for i in range(len(self.table)) if mask >> i & 1]; n = len(ids)
        require(n > 0, 'empty reference support')
        if len({self.table[i] for i in ids}) == 1: result = F(1),F(0),None
        else:
            result = F(0),F(0),None
            if budget:
                for state in range(6):
                    bins = [mask & m for m in self.masks[state] if mask & m]
                    if len(bins) < 2: continue
                    children = [(F(m.bit_count(),n),self.optimal(m,budget-1)) for m in bins]
                    value = sum((p*v[0] for p,v in children),F(0))
                    cost = 1+sum((p*v[1] for p,v in children),F(0))
                    if value > result[0] or value == result[0] and cost < result[1]: result = value,cost,state
        self.memo[key] = result; return result

    def fixed_order(self, budget):
        if budget in self.fixed: return self.fixed[budget]
        best = None
        for order in permutations(range(6),budget):
            bins = {((1 << len(self.table))-1):len(self.table)}; calls = 0
            for state in order:
                nxt = {}
                for mask,n in bins.items():
                    if mask.bit_count() == 1: nxt[mask] = n; continue
                    calls += n
                    for m in self.masks[state]:
                        child = mask & m
                        if child: nxt[child] = child.bit_count()
                bins = nxt
            good = sum(n for m,n in bins.items() if m.bit_count() == 1)
            item = good,-calls,tuple(-s for s in order)
            if best is None or item > best[0]: best = item,order,good,calls
        self.fixed[budget] = best[1:]; return self.fixed[budget]

    def action(self, mode, history, budget):
        ids = support(history)
        if all(x is not None for x in agreement(ids)): return None
        if mode == 'optimal': return self.optimal(sum(1 << i for i in ids),budget-len(history))[2]
        if mode == 'prior_fixed': return self.fixed_order(budget)[0][len(history)]
        if mode == 'first_informative': return next(i for i,x in enumerate(agreement(ids)) if x is None)
        return choose(history,1)[1]
