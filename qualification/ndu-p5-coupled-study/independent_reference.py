"""Independent prefix-keyed reference and dense finite-difference Newton.

Not a general FBSDE theorem, pretraining result or independent signer.
Does NOT call coupled_binary.mapping/transport. Designed to detect indexing,
forward/backward coupling, drift, and wrong-root local convergence errors.
"""
from __future__ import annotations
import math
from time import process_time_ns, perf_counter_ns


def prefixes(steps):
    return [tuple(int(b) for b in format(i, 'b')[1:]) for i in range(1,2**steps)]


def direct_map(p, y):
    keys=prefixes(p.steps)
    if len(keys)!=len(y) or any(not math.isfinite(v) for v in y):
        raise ValueError('whole public-information tree required')
    mapping=dict(zip(keys,y))
    h=p.h
    x={():float(p.x0)}
    for k in keys:
        for b in (0,1):
            x[k+(b,)]=x[k]+p.a*h*mapping[k]+(2*b-1)*p.sigma*math.sqrt(h)
    u={k:math.tanh(v) for k,v in x.items() if len(k)==p.steps}
    for k in reversed(keys):
        u[k]=(sum(u[k+(b,)] for b in (0,1))/2+h*p.beta*math.tanh(x[k]))/(1+p.lam*h)
    return [u[k] for k in keys]


def gaussian_solve(matrix, rhs):
    """Pivoting dense reference. No fitted model and no pseudoinverse fallback."""
    n=len(rhs)
    rows=[list(row)+[rhs[i]] for i,row in enumerate(matrix)]
    for i in range(n):
        k=max(range(i,n), key=lambda j:abs(rows[j][i]))
        if abs(rows[k][i])<1e-12: raise ValueError('singular Newton Jacobian')
        rows[i],rows[k]=rows[k],rows[i]
        t=rows[i][i]
        rows[i]=[z/t for z in rows[i]]
        for j in range(i+1,n):
            t=rows[j][i]
            rows[j]=[a-t*b for a,b in zip(rows[j],rows[i])]
    d=[0.]*n
    for i in range(n-1,-1,-1):
        d[i]=rows[i][-1]-sum(rows[i][j]*d[j] for j in range(i+1,n))
    return d


def newton(p,*,tol=1e-9,max_iter=16):
    p.validate()
    n=2**p.steps-1
    if n>31: raise ValueError('bounded dense reference at <=5 steps')
    y=[0.]*n
    calls=0
    cpu=process_time_ns();wall=perf_counter_ns()
    for k in range(max_iter):
        m=direct_map(p,y);calls+=1
        residual=[v-w for v,w in zip(y,m)]
        rr=max(map(abs,residual))
        if rr/(1-p.q)<=tol:
            return dict(y=y,iterations=k,operator_calls=calls,
                        residual=rr,nominal_error_bound=rr/(1-p.q),
                        cpu_ns=process_time_ns()-cpu,wall_ns=perf_counter_ns()-wall,
                        independent_implementation=True,
                        roundoff_enclosed=False,production_accepted=False,authority='DENY_ALL')
        cols=[]
        for j in range(n):
            delta=1e-6*max(1,abs(y[j]))
            yp=y.copy();yp[j]+=delta
            next_map=direct_map(p,yp);calls+=1
            cols.append([float(i==j)-(v-w)/delta for i,(v,w) in enumerate(zip(next_map,m))])
        jac=[[cols[j][i] for j in range(n)] for i in range(n)]
        correction=gaussian_solve(jac,[-v for v in residual])
        # Measured backtracking, never pretend a failed Newton step is accepted.
        improved=False
        scale=1.
        for _ in range(20):
            candidate=[v+scale*d for v,d in zip(y,correction)]
            rc=direct_map(p,candidate);calls+=1
            if max(abs(v-w) for v,w in zip(candidate,rc))<rr:
                y=candidate;improved=True;break
            scale/=2
        if not improved: raise ValueError('newton line search failed')
    raise ValueError('newton iteration exhausted')
