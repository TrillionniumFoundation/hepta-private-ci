"""Exact rational NDU forward-Stem global optimum and CC5 counterexample."""
from fractions import Fraction as F
import json
from pathlib import Path
GAMMA=F(9,10)
NOISE=F(1,5)
CC5={0:F(1),2:F(1,3),4:F(1,5),6:F(2,15),8:F(1,10)}
def moment(k):
    if k<0: raise ValueError("negative")
    return F(0) if k%2 else F(1,k+1)
def coefficients(theta):
    a={1:F(1),2:-F(1),4:theta}
    out={0:NOISE**2}
    for i,c in a.items():
        for j,d in a.items():out[i+j]=out.get(i+j,F(0))+c*d
    return out
def score(theta,measure=moment):
    return GAMMA*sum((c*measure(k) for k,c in coefficients(theta).items()),F(0))
def ccscore(theta):
    return score(theta,lambda k:CC5.get(k,F(0)))
def certificate():
    exact,coarse=F(9,7),F(4,3)
    gap=GAMMA*moment(8)*(coarse-exact)**2
    assert score(coarse)-score(exact)==gap==F(1,4410)
    assert ccscore(coarse)<ccscore(exact)
    return dict(exact_theta=str(exact),coarse_theta=str(coarse),
        true_optimal_cost=str(score(exact)),coarse_model_true_cost=str(score(coarse)),
        rigorous_excess=str(gap),true_m6=str(moment(6)),coarse_m6=str(CC5[6]),
        true_m8=str(moment(8)),coarse_m8=str(CC5[8]),
        degree=8,global_quadratic_certificate=True,nonzero_risk_NDU=False,
        general_neural_bound=False)
if __name__=="__main__":
    print(json.dumps(certificate(),sort_keys=True))
