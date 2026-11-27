"""R14 actual population optimizers: same two-weight law, no oracle training labels."""
import json
import resource
import time
from fractions import Fraction as Q
from itertools import product
import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from problem import XS,PS,EPS,GAMMA,RHO,leaves
from certificate import A,B,certificate

G=float(GAMMA)
QUALITY=Q(1,10**6)
CAP=3.0
SEEDS=(11,23,47,59,83)
METHODS=('adam','newton','lbfgs')


def logce_branch(data,rho):
    """(cost, gradient, Hessian) of binary entropic certainty equivalent."""
    vals=np.array([x[0] for x in data],dtype=float)
    logits=float(rho)*vals
    weights=np.exp(logits-logsumexp(logits))
    f=(logsumexp(logits)-np.log(2))/float(rho)
    grad=sum(w*d[1] for w,d in zip(weights,data))
    hess=sum(w*d[2] for w,d in zip(weights,data))
    hess+=float(rho)*sum(w*np.outer(d[1]-grad,d[1]-grad) for w,d in zip(weights,data))
    return float(f),grad,hess


def population(theta):
    a,b=map(float,theta)
    total=0.;grad=np.zeros(2);hess=np.zeros((2,2))
    for x,p0 in product(XS,PS):
        first=[]
        for e1 in EPS:
            l1,g1,p1,terminal=leaves(a,b,float(x),p0,e1)
            v=np.array((float(x)**2,float(x)**3))
            g1=np.asarray(g1,dtype=float)
            h1=2*np.outer(v,v)
            gain=float(1+e1*x/10)
            terminal_data=[(float(loss),np.asarray(der,dtype=float),2*gain**2*np.outer(v,v))
                           for loss,der,p2 in terminal]
            ce,ce_g,ce_h=logce_branch(terminal_data,RHO[p1])
            first.append((float(l1)+G*ce,g1+G*ce_g,h1+G*ce_h))
        value,d,h=logce_branch(first,RHO[p0])
        total+=G*value/(len(XS)*len(PS))
        grad+=G*d/(len(XS)*len(PS))
        hess+=G*h/(len(XS)*len(PS))
    return float(total),grad,hess


def initial(seed):
    rng=np.random.default_rng(seed)
    return rng.uniform(-.7,.7,size=2)


def verified_quality(theta,radius):
    if not np.isfinite(theta).all() or radius >= QUALITY:return False
    # Euclidean gap to rational candidate rigorously compared with exact rational slack.
    dx=Q.from_float(float(theta[0]))-A
    dy=Q.from_float(float(theta[1]))-B
    return dx*dx+dy*dy<(QUALITY-radius)**2


class StopQuality(Exception):pass
class StopBudget(Exception):pass


def fit(seed,method,radius,cap=CAP):
    if seed not in SEEDS or method not in METHODS or cap<=0:raise ValueError('invalid case')
    started=time.perf_counter();started_cpu=time.process_time()
    clock=lambda:time.process_time()-started_cpu
    x=initial(seed)
    history=[];counts=dict(objective=0,gradient=0,hessian=0,updates=0,backtracks=0)
    qualifies=False;observed_cpu=None;status='cap'
    def check_point():
        nonlocal qualifies,observed_cpu,status
        t=clock();good=verified_quality(x,radius)
        history.append(dict(step=counts['updates'],cpu=t,quality=good,theta=x.tolist()))
        if good and t<=cap:
            qualifies=True;observed_cpu=t;status='quality';raise StopQuality()
    def budget():
        if clock()>cap:raise StopBudget()
    check_point_caught=False
    try:
        check_point()
        if method=='adam':
            m=np.zeros(2);v=np.zeros(2);rate=.045
            for k in range(1,100000):
                budget()
                cost,grad,_=population(x)
                counts['objective']+=1;counts['gradient']+=1
                if not np.isfinite(grad).all():raise FloatingPointError('gradient nonfinite')
                m=.9*m+.1*grad;v=.999*v+.001*grad*grad
                x-=rate*(m/(1-.9**k))/(np.sqrt(v/(1-.999**k))+1e-8)
                counts['updates']+=1
                check_point()
        elif method=='newton':
            for k in range(10000):
                budget()
                cost,g,H=population(x)
                counts['objective']+=1;counts['gradient']+=1;counts['hessian']+=1
                if np.linalg.eigvalsh(H).min()<=0:raise FloatingPointError('nonpositive Hessian')
                step=np.linalg.solve(H,g)
                alpha=1.
                while True:
                    budget()
                    proposal=x-alpha*step
                    newcost=population(proposal)[0];counts['objective']+=1
                    if newcost<cost or np.linalg.norm(g)<1e-13:break
                    counts['backtracks']+=1;alpha/=2
                    if alpha<2**-20:raise FloatingPointError('Armijo stall')
                x=proposal;counts['updates']+=1
                check_point()
        else:
            def fun(z):
                budget()
                cost,grad,_=population(z)
                counts['objective']+=1;counts['gradient']+=1
                return cost,grad
            def cb(z):
                nonlocal x
                x=z.copy();counts['updates']+=1
                check_point()
            result=minimize(fun,x,jac=True,method='L-BFGS-B',callback=cb,
                            options=dict(gtol=1e-12,ftol=1e-16,maxiter=100000,maxls=40))
            x=result.x;status=str(result.message)
    except StopQuality:
        pass
    except StopBudget:
        pass
    # One final diagnostic: does NOT retrospectively qualify after cap.
    endcost,endgrad,endh=population(x)
    report=dict(seed=seed,method=method,initial=initial(seed).tolist(),selected=x.tolist(),
                success=qualifies,first_quality_cpu=observed_cpu,final_quality=verified_quality(x,radius),
                status=status,cpu=clock(),wall=time.perf_counter()-started,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                counts=counts,history=history,final_cost=endcost,
                final_grad_inf=float(max(abs(endgrad))),final_hessian_min=float(np.linalg.eigvalsh(endh).min()),
                oracle_parameters_used_in_training=False,
                certificate_used_for_stopping_only=True)
    return report


if __name__=='__main__':
    r=Q(certificate()['distance_to_unique_global_optimum_upper'])
    for seed in SEEDS:
        for method in METHODS:
            out=fit(seed,method,r)
            print(seed,method,out['success'],out['first_quality_cpu'],out['counts'],out['final_cost'])
