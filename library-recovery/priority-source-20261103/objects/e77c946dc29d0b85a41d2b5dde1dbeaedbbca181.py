"""Small finite-state regenerative Bellman/QVI double oracle.

This is a deliberately separate MODEL CHECK, not the He-Xiong endogenous
continuous-time rollover QVI. Infinite horizon discounted stop-and-reset:
V(i)=max(c_i + beta P_i V, reset_reward_i + beta V(reset_state)).
"""
import itertools
import numpy as np


def value_iteration(P, rewards, reset_rewards, beta, reset=0, tolerance=2e-13):
    P=np.asarray(P,dtype=float)
    c=np.asarray(rewards,dtype=float)
    g=np.asarray(reset_rewards,dtype=float)
    n=len(c)
    if not (P.shape==(n,n) and g.shape==(n,) and np.all(P>=0)
            and np.max(np.abs(P.sum(axis=1)-1))<1e-13
            and 0 < beta < 1 and 0<=reset<n):
        raise ValueError("invalid discounted MDP")
    V=np.zeros(n)
    for iteration in range(300000):
        cont=c+beta*P@V
        reinit=g+beta*V[reset]
        nxt=np.maximum(cont,reinit)
        if np.max(abs(nxt-V)) < tolerance*(1-beta)/2:
            return nxt,iteration+1
        V=nxt
    raise ArithmeticError("no QVI convergence")


def exhaustive_policy_reference(P, rewards, reset_rewards, beta, reset=0):
    P=np.asarray(P,dtype=float)
    c=np.asarray(rewards,dtype=float)
    g=np.asarray(reset_rewards,dtype=float)
    n=len(c)
    value_vectors=[]
    for decision in itertools.product((False,True),repeat=n):
        A=P.copy()
        r=c.copy()
        for i, reset_now in enumerate(decision):
            if reset_now:
                A[i,:]=0
                A[i,reset]=1
                r[i]=g[i]
        value_vectors.append(np.linalg.solve(np.eye(n)-beta*A,r))
    return np.stack(value_vectors).max(axis=0)


def audit():
    P=np.array([[.8,.2,0,0],[.15,.7,.15,0],
                [0,.2,.6,.2],[0,0,.25,.75]])
    c=np.array([0.,.08,.4,.5])
    r=np.array([0.,.1,1.,4.])
    beta=.94
    V,k=value_iteration(P,c,r,beta)
    ref=exhaustive_policy_reference(P,c,r,beta)
    bellman=np.maximum(c+beta*P@V,r+beta*V[0])
    return {'max_policy_gap':float(max(abs(V-ref))),
            'max_bellman_residual':float(max(abs(bellman-V))),
            'iterations':k,'values':V.tolist(),
            'intervention':[bool(a) for a in r+beta*V[0]>c+beta*P@V]}
