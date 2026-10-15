"""R18 independent Python-only leaf/certainty-equivalent evaluator.

No SciPy, no calls to the trained problem.py evaluator or certificate.
"""
import math

def entropic(x,y,r):
    a,b=r*x,r*y
    m=max(a,b)
    return (m+math.log((math.exp(a-m)+math.exp(b-m))/2))/r

def leaf(theta,x,p0,e1,e2,shift=1):
    a,b=theta
    p1=p0^(e1==1);p2=p1^(e2==1)
    h1=a*x;h2=b*h1+(a-b)**2/4+e2/10
    return h1,h2,p1,p2,p1/20,(h2-x-shift)**2+p2/50

def direct(theta,shift=1):
    c=0.
    for x in (-1,1):
        for p0 in (0,1):
            branches=[]
            for e1 in (-1,1):
                q=[leaf(theta,x,p0,e1,e2,shift) for e2 in (-1,1)]
                r=(.5,1.)[q[0][2]]
                branches.append(q[0][4]+.9*entropic(q[0][5],q[1][5],r))
            c+=.9/4*entropic(branches[0],branches[1],(.5,1.)[p0])
    return c+sum(v*v for v in theta)/4
