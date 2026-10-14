"""Independent FLOAT numerical diagnostics; these do NOT enter the proof."""
import json
from math import isfinite
import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.optimize import root
from scipy.special import logsumexp
from certificate import A,B,certificate


def exact_branches(x,p,a,b):
    z=x+(a-1)*x*x+b*x**3-.5*x**4
    plus=(z+.2)**2+(1-p)*.05
    minus=(z-.2)**2+p*.05
    return plus,minus,z


def objective(theta,n=80):
    x,w=leggauss(n)
    a,b=theta
    result=0.0
    for p,r in ((0,.5),(1,1.)):
        plus,minus,z=exact_branches(x,p,a,b)
        ce=np.logaddexp(r*plus,r*minus)/r-np.log(2)/r
        result+=.5*.9*(w@ce)/2
    return float(result)


def gradient(theta,n=80):
    x,w=leggauss(n)
    a,b=theta
    z=x+(a-1)*x*x+b*x**3-.5*x**4
    gp=2*z+.2*(np.tanh(.5*(.4*z+.025))+np.tanh(.4*z-.025))
    return .9*np.array([w@(gp*x*x),w@(gp*x**3)])/2


def run():
    guess=[float(A),float(B)]
    optimal=root(gradient,guess,tol=1e-12)
    if not np.isfinite(optimal.x).all() or np.linalg.norm(gradient(guess),ord=np.inf)>1e-11:
        raise AssertionError('numerical cross-check not close')
    if max(abs(optimal.x-guess))>1e-10:
        raise AssertionError('candidate/rational mismatch')
    x=np.linspace(-1,1,101)
    mart_max=0.
    for p in (0,1):
        plus,minus,z=exact_branches(x,p,*guess)
        zmart=plus-minus
        mean=(plus+minus)/2
        mart_max=max(mart_max,float(np.max(np.abs((plus-mean)-zmart/2))),
                                  float(np.max(np.abs((minus-mean)+zmart/2))))
    if mart_max>1e-14:raise AssertionError('discrete martingale identity failed')
    return dict(schema='hepta.ndu.exact-two-weight.numeric-diagnostics.v1',
        numerical_theta=[float(x) for x in optimal.x],rational_candidate=guess,
        numerical_residual=[float(x) for x in gradient(guess)],
        objective_candidate=objective(guess),objective_numerical_root=objective(optimal.x),
        risk_neutral_theta=[19/14,-7/5],
        branch_martingale_max_defect=mart_max,
        rigorous_proof_uses_these_floats=False,
        scipy_solver_success=bool(optimal.success))


if __name__=='__main__':print(json.dumps(run(),indent=2,sort_keys=True))
