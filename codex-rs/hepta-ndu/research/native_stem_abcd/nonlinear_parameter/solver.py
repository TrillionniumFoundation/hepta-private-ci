"""R15 three matched numerical solvers; independent rational proof never trains models."""
import resource
import time
from fractions import Fraction as Q
import numpy as np
from scipy.optimize import minimize
from problem import population,BOX
from certificate import A,B

CAP_CPU=2.
GATE=Q(1,10**6)
SEEDS=(11,23,47,59,83,97,101,109)
METHODS=('adam','newton','lbfgs')
ARMS=('certified','oscillatory')

class CapReached(Exception):pass
class QualityReached(Exception):pass


def initial(seed):
    return np.random.default_rng(seed).uniform(-1.8,1.8,2)


def observed_quality(theta, radius):
    if not np.isfinite(theta).all() or radius>=GATE:return False
    if any(not float(BOX[0])<=z<=float(BOX[1]) for z in theta):return False
    da=Q.from_float(float(theta[0]))-A
    db=Q.from_float(float(theta[1]))-B
    return da*da+db*db <= (GATE-radius)**2


def kkt_violation(theta,grad,tolerance=5e-9):
    violations=[]
    for a,g in zip(theta,grad):
        if a<=float(BOX[0])+tolerance:violations.append(max(0.,-g))
        elif a>=float(BOX[1])-tolerance:violations.append(max(0.,g))
        else:violations.append(abs(g))
    return max(violations)


def fit(seed,method,arm,radius,cap=CAP_CPU):
    if method not in METHODS or arm not in ARMS or seed not in SEEDS or cap<=0:
        raise ValueError('invalid run identity')
    started=time.perf_counter();cpu_start=time.process_time()
    elapsed=lambda:time.process_time()-cpu_start
    x=initial(seed).copy()
    osc=arm=='oscillatory'
    counts=dict(objective=0,gradient=0,hessian=0,updates=0,backtracks=0,
                damped_newton=0,rejected=0)
    history=[];successful=False;first_cpu=None;status='cpu_cap'
    def fun(z):
        f,g,H=population(z,oscillatory=osc)
        counts['objective']+=1;counts['gradient']+=1;counts['hessian']+=1
        if not np.isfinite(f) or not np.isfinite(g).all() or not np.isfinite(H).all():
            raise FloatingPointError('nonfinite fit state')
        return f,g,H
    def audit_checkpoint():
        nonlocal successful,first_cpu,status
        f,g,H=fun(x)
        checked=observed_quality(x,radius) if not osc else None
        t=elapsed()
        row=dict(theta=x.tolist(),cpu=t,objective=f,gradient_inf=float(np.abs(g).max()),
                 hessian_min=float(np.linalg.eigvalsh(H)[0]),quality=checked,
                 kkt_violation=kkt_violation(x,g))
        history.append(row)
        if checked and t<=cap:
            successful=True;first_cpu=t;status='quality_observed';raise QualityReached()
    def budget():
        if elapsed()>=cap:raise CapReached()
    try:
        audit_checkpoint()
        if method=='adam':
            rate=.045;m=np.zeros(2);v=np.zeros(2)
            for k in range(1,200000):
                budget()
                _,grad,_=fun(x)
                m=.9*m+.1*grad;v=.999*v+.001*grad**2
                nx=np.clip(x-rate*(m/(1-.9**k))/(np.sqrt(v/(1-.999**k))+1e-8),float(BOX[0]),float(BOX[1]))
                if np.array_equal(x,nx):status='adam_clipped_stall';break
                x=nx;counts['updates']+=1;audit_checkpoint()
        elif method=='newton':
            for _ in range(10000):
                budget()
                f,g,H=fun(x)
                eig=np.linalg.eigvalsh(H)
                regularization=max(0.,.001-eig[0]);counts['damped_newton']+=int(regularization>0)
                step=np.linalg.solve(H+regularization*np.eye(2),g)
                if np.linalg.norm(g,ord=np.inf)<1e-10:
                    status='newton_stationary';break
                alpha=1.;accepted=False
                for _ in range(40):
                    budget()
                    z=np.clip(x-alpha*step,float(BOX[0]),float(BOX[1]))
                    if np.array_equal(z,x):break
                    newcost=fun(z)[0]
                    if newcost <= f + 1e-4*np.dot(g,z-x):
                        accepted=True;break
                    alpha*=.5;counts['backtracks']+=1;counts['rejected']+=1
                if not accepted:
                    # For nonconvex stress, derivative descent may be blocked at boundary.
                    status='newton_line_search_stalled';break
                x=z;counts['updates']+=1;audit_checkpoint()
        else:
            def objective(theta):
                budget()
                f,g,_=fun(theta)
                return f,g
            def callback(z):
                nonlocal x
                x=z.copy();counts['updates']+=1;audit_checkpoint()
            result=minimize(objective,x,jac=True,method='L-BFGS-B',
                bounds=[(float(BOX[0]),float(BOX[1]))]*2,callback=callback,
                options=dict(gtol=1e-12,ftol=1e-15,maxls=40,maxiter=100000))
            x=result.x.copy();status=str(result.message)
    except QualityReached:pass
    except CapReached:pass
    f,g,H=fun(x)
    eigen=np.linalg.eigvalsh(H)
    report=dict(seed=seed,arm=arm,method=method,initial=initial(seed).tolist(),selected=x.tolist(),
        certified_gate_success=successful if not osc else None,
        quality_first_cpu=first_cpu if not osc else None,
        stress_numerical_local_candidate=bool(osc and kkt_violation(x,g)<1e-6 and eigen[0]>1e-5),
        stress_global_certificate=False if osc else True,
        status=status,fit_cpu=elapsed(),fit_wall=time.perf_counter()-started,
        process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        final_cost=float(f),final_gradient=g.tolist(),final_kkt_violation=kkt_violation(x,g),
        final_hessian_eigenvalues=eigen.tolist(),history=history,counts=counts,
        parameter_count=2,training_uses_oracle_labels=False,
        reference_used_only_for_quality_monitor=not osc,
        energy_joules=None,full_flops=None)
    return report

if __name__=='__main__':
    import json
    from certificate import proof
    r=Q(proof()['true_global_optimum_distance_upper'])
    for arm in ARMS:
        for seed in SEEDS[:2]:
            for meth in METHODS:
                v=fit(seed,meth,arm,r)
                print(arm,seed,meth,v['status'],v['final_cost'],v['quality_first_cpu'],v['counts']['updates'],v['final_hessian_eigenvalues'])
