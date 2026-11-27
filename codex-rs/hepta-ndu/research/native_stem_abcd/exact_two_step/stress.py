"""Independent float-only continuous-X population change; deliberately not certified."""
import json
import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.optimize import minimize
from scipy.special import logsumexp
from certificate import A,B
from problem import GAMMA,RHO,EPS


def evaluate_continuous(theta,n=48):
    a,b=theta; xs,ws=leggauss(n)
    g=.9
    total=0.;total_grad=np.zeros(2)
    for i,x in enumerate(xs):
        gradx=np.array([x*x,x*x*x]);base=x+a*x*x+b*x**3;target=x*x+x**4/2
        for p0 in (0,1):
            children=[]
            for e1 in EPS:
                p1=p0^(e1==1);h1=base+e1/5
                gain=1+e1*x/10
                v1=(h1-target)**2+p1/20
                d1=2*(h1-target)*gradx
                vals=[]
                for e2 in EPS:
                    p2=p1^(e2==1)
                    gap=gain*h1+e2/10-(gain*target+x/8)
                    vals.append((gap*gap+p2/25,2*gap*gain*gradx))
                logits=float(RHO[p1])*np.array([z[0] for z in vals]);ww=np.exp(logits-logsumexp(logits))
                ce=(logsumexp(logits)-np.log(2))/float(RHO[p1])
                children.append((v1+g*ce,d1+g*sum(w*pair[1] for w,pair in zip(ww,vals))))
            logit=float(RHO[p0])*np.array([z[0] for z in children]);ww=np.exp(logit-logsumexp(logit))
            total+=ws[i]/2 *g*(logsumexp(logit)-np.log(2))/float(RHO[p0])/2
            total_grad+=ws[i]/2*g*sum(w*pair[1] for w,pair in zip(ww,children))/2
    return total,total_grad


def run():
    from problem import evaluate
    import scipy
    sol=minimize(lambda t:evaluate_continuous(t),[float(A),float(B)],method='BFGS',jac=True,
                 options={'gtol':1e-11,'maxiter':60})
    before=evaluate_continuous([float(A),float(B)])
    return dict(law='X uniform continuous [-1,1], DIFFERENT from certified 5-atom law',
                certified_discrete_candidate=[float(A),float(B)],
                separate_continuous_root=[float(z) for z in sol.x],
                continuous_cost_at_discrete_candidate=float(before[0]),
                continuous_cost_at_continuous_numeric_root=float(sol.fun),
                continuous_candidate_gap=float(before[0]-sol.fun),
                continuous_gradient_at_discrete_candidate=list(map(float,before[1])),
                numeric_root_success=bool(sol.success),
                rigorous_continuous_population_certificate=False)
if __name__=='__main__':print(json.dumps(run(),indent=2,sort_keys=True))
