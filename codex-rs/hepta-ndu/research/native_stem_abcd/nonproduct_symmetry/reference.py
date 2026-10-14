"""Independent pure Python 16-leaf score and preference bookkeeping for audit."""
from math import exp,log

def cert_equiv_eval(weights,kappa=.25,variant='correlated',xprob=.5):
    a,b=map(float,weights)
    def CE(v,r):
        m=max(v)
        return m+log(sum(exp(r*(z-m)) for z in v)/2)/r
    t=0.
    for x in (-1,1):
        for p0 in (0,1):
            stage=[]
            for e1 in (-1,1):
                p1=p0 ^ (e1==1)
                final=[]
                for e2 in (-1,1):
                    p2=p1 ^ (e2==1)
                    h1=a*x
                    h2=b*h1+kappa*(a-b)*(a-b)+e2*(x if variant=='correlated' else 1)/10
                    final.append((h2-x)**2+p2/50)
                stage.append(p1/20+.9*CE(final,(.5,1.)[p1]))
            total=.9*CE(stage,(.5,1.)[p0])
            t+=(xprob if x==1 else 1-xprob)/2*total
    return t+(a*a+b*b)/4
