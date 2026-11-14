"""Exact rational policy enumeration certificate for a finite regenerative MDP.

Certifies only the explicitly supplied *finite-state discounted* Bellman/QVI:
V[i] = max(c[i] + beta sum_j P[i,j] V[j], g[i]+beta V[reset]).
All calculations use exact rational arithmetic, with every deterministic
stationary continuation/reset policy enumerated. This is NOT the original
continuous He-Xiong equity/bond free-boundary QVI or a neural HCSN kernel.
"""
from __future__ import annotations
from fractions import Fraction
import itertools
import json


def f(s):
    if not isinstance(s,str):
        raise ValueError('rational certificate accepts decimal string inputs only')
    return Fraction(s)


def solve_exact(A,b):
    n=len(b)
    if len(A)!=n or any(len(row)!=n for row in A):
        raise ValueError('non-square linear system')
    M=[list(A[i])+[b[i]] for i in range(n)]
    for col in range(n):
        pivot=next((row for row in range(col,n) if M[row][col]),None)
        if pivot is None:raise ArithmeticError('singular linear system')
        M[col],M[pivot]=M[pivot],M[col]
        v=M[col][col]
        M[col]=[z/v for z in M[col]]
        for row in range(n):
            if row==col:continue
            fac=M[row][col]
            if fac:
                M[row]=[a-fac*b for a,b in zip(M[row],M[col])]
    return [row[-1] for row in M]


def certify(P:list[list[str]],rewards:list[str],reset_rewards:list[str],
            beta:str,reset:int=0):
    n=len(P)
    if n<1 or n>8 or len(rewards)!=n or len(reset_rewards)!=n:
        raise ValueError('finite-state enumeration requires 1..8 states')
    if not 0<=reset<n:raise ValueError('bad reset index')
    T=[[f(a) for a in row] for row in P]
    c=[f(x) for x in rewards]
    g=[f(x) for x in reset_rewards]
    B=f(beta)
    if not (0<B<1):raise ValueError('discount must be strictly 0..1')
    if any(len(row)!=n or any(v<0 for v in row) or sum(row)!=1 for row in T):
        raise ValueError('not a stochastic transition matrix')
    value_vectors=[]
    all_policies=list(itertools.product((False,True),repeat=n))
    for policy in all_policies:
        policy_transition=[([Fraction(int(j==reset)) for j in range(n)] if policy[i]
                           else T[i]) for i in range(n)]
        rewards_=[g[i] if policy[i] else c[i] for i in range(n)]
        A=[[(Fraction(int(i==j))-B*policy_transition[i][j])
            for j in range(n)] for i in range(n)]
        value_vectors.append(solve_exact(A,rewards_))
    V=[max(values[i] for values in value_vectors) for i in range(n)]
    q_cont=[c[i]+B*sum(T[i][j]*V[j] for j in range(n)) for i in range(n)]
    q_reset=[g[i]+B*V[reset] for i in range(n)]
    if any(V[i]!=max(q_cont[i],q_reset[i]) for i in range(n)):
        raise ArithmeticError('Bellman equation failed exact policy enumeration')
    best_policy=tuple(q_reset[i]>q_cont[i] for i in range(n))
    if list(V)!=value_vectors[all_policies.index(best_policy)]:
        raise ArithmeticError('no global stationary optimal policy matches value')
    return {'model':'finite discounted regenerative MDP, not full He-Xiong QVI',
            'state_count':n,'enumerated_policies':len(all_policies),
            'discount':str(B),'exact_values':[str(z) for z in V],
            'continue_q':[str(z) for z in q_cont],
            'reset_q':[str(z) for z in q_reset],
            'optimal_reset_actions':list(best_policy),
            'bellman_residual_exact':'0',
            'comparison_to_all_stationary_policies':'exact_componentwise_dominance',
            'full_HX_qvi_certified':False}


def known_case():
    return certify([
        ['.8','.2','0','0'],['.15','.7','.15','0'],
        ['0','.2','.6','.2'],['0','0','.25','.75']],
        ['0','.08','.4','.5'],['0','.1','1','4'],'.94',0)


if __name__=='__main__':print(json.dumps(known_case(),indent=2))
