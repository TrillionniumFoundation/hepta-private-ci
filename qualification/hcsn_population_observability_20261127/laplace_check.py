"""Independent time/space quadratures against discounted first-passage resolvent identities."""
import argparse,json,math
from pathlib import Path
from scipy.integrate import quad
from scipy.special import ndtr
import numpy as np

def check():
    rows=[]
    for mu in (-.15,0.,.03355):
        sigma=.23
        for x in (.025,.18,.7):
            for s in (.03,.2,1.,3.):
                k=(mu+math.sqrt(mu*mu+2*sigma**2*s))/sigma**2
                def time_integrand(u):
                    # u=x/(sigma sqrt(t)); transformed density has no t^(-3/2) spike.
                    if u==0:return 0.
                    t=(x/(sigma*u))**2
                    return 2/math.sqrt(2*math.pi)*math.exp(-.5*(u+mu*x/(sigma*sigma*u))**2-s*t)
                all_hit=quad(time_integrand,0,np.inf,epsabs=1e-12,epsrel=1e-11)[0]
                expected=math.exp(-k*x)
                for dt in (.125,.25,.75):
                    G=quad(time_integrand,x/(sigma*math.sqrt(dt)),np.inf,epsabs=1e-12)[0]
                    std=sigma*math.sqrt(dt)
                    def kernel(y):
                        def normal(c):return math.exp(-.5*((y-c)/std)**2)/(std*math.sqrt(2*math.pi))
                        return math.exp(-k*y)*(normal(x+mu*dt)-math.exp(-2*mu*x/sigma**2)*normal(-x+mu*dt))
                    spatial=quad(kernel,0,np.inf,epsabs=1e-12,epsrel=1e-11)[0]
                    rows.append(dict(mu=mu,sigma=sigma,x=x,s=s,dt=dt,
                                    laplace_time_error=abs(all_hit-expected),
                                    recurrence_absolute_error=abs(spatial-math.exp(s*dt)*(expected-G))))
    result=dict(cases=len(rows),max_time_error=max(r["laplace_time_error"] for r in rows),
                max_recurrence_error=max(r["recurrence_absolute_error"] for r in rows),cases_detail=rows)
    assert result["max_time_error"]<1e-9 and result["max_recurrence_error"]<1e-9
    return result
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("output",type=Path);a=p.parse_args()
    a.output.write_text(json.dumps(check(),indent=2)+"\n")
