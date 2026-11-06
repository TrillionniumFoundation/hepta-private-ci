"""Independent exact reference: one history recursion and one memoized DP."""
from fractions import Fraction as F
from .contract import ORDER


def full_dp(c,root=None):
    values,actions,qs={}, {}, {}
    work=0
    def visit(s):
        nonlocal work
        if s in values:return values[s]
        work+=len(c.world_accuracy)+1
        row=c.terminal(s)
        for a in c.information_actions(s):
            responses=c.responses(s,a)
            work+=(len(c.world_accuracy)+1)*len(responses)
            row[a]=-c.cost(a)+sum((p*visit(child) for p,child in responses),F(0))
        action=max(ORDER,key=lambda a:row.get(a,F(-10**6)))
        values[s],actions[s],qs[s]=row[action],action,row
        return values[s]
    value=visit(root or c.root)
    return {'value':value,'values':values,'actions':actions,'q':qs,'planning_units':work}


def history_reference(c):
    # This intentionally does not use posterior counts, the model's response
    # method, the partial-DAG bounds or the DP's tables. It keeps all four raw
    # likelihood masses and reconstructs conditional rewards/probabilities.
    calls=0
    def rec(remaining,ready,masses):
        nonlocal calls
        calls+=1
        total=sum(masses,F(0))
        terminal={a:sum((m*c.terminal_world(a,h) for h,m in enumerate(masses)),F(0))/total
                  for a in ('stop','follow','flip')}
        values=list(terminal.values())
        if remaining<1:return max(values)
        if not ready:
            values.append(-c.cost('prepare')+rec(remaining-1,True,masses))
        else:
            for n,a in ((1,'fast'),(2,'pair')):
                if n>remaining:continue
                # Enumerate each ordered binary response string. Equal count
                # strings are NOT merged in this independent implementation.
                from itertools import product
                continuation=F(0)
                for bits in product((0,1),repeat=n):
                    likelihood=tuple(m*p**sum(bits)*(1-p)**(n-sum(bits))
                        for m,p in zip(masses,c.world_accuracy))
                    branch_mass=sum(likelihood,F(0))
                    continuation+=branch_mass/total*rec(remaining-n,True,likelihood)
                values.append(-c.cost(a)+continuation)
        return max(values)
    value=rec(c.deadline,False,c.prior)
    return {'value':value,'history_calls':calls}
