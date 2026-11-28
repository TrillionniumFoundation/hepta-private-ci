"""Compare large-time rates and moment classifications to a separate survival-integral computation."""
import hashlib,json,math
from pathlib import Path
import numpy as np
from scipy.integrate import quad
from scipy.special import erf
from tonic_microdomains import zero_drift_dimensionless_moment,stationary_rate,infinite_count_when_outward


def main(out):
    sigma=.23;r=.30;h=.025;rows=[];maximum=0.;rng=np.random.default_rng(7242768)
    for n in (1,2,3,4,5,8,16):
        moments={}
        for k in (1,2):
            result=zero_drift_dimensionless_moment(n,k)
            if math.isinf(result):
                moments[str(k)]='divergent'
                assert n<=2*k
            else:
                # Independent direct integration: E[W^k]=k*integral t^(k-1)*S(t)^n dt.
                fn=lambda t:k*t**(k-1)*erf(1/math.sqrt(2*t))**n
                direct=quad(fn,0.,1.,epsabs=2e-12,epsrel=2e-12)[0]+quad(fn,1.,np.inf,epsabs=2e-12,epsrel=2e-12,limit=300)[0]
                err=abs(direct-result);maximum=max(maximum,err);assert err<2e-10
                moments[str(k)]=result
        rate=stationary_rate(n,r,0.,sigma,h)
        second=moments['2'];mean=moments['1']
        variance=(r/sigma)**4*(second-mean**2) if isinstance(second,float) else None
        fano=variance*rate**2 if variance is not None else None
        outward=infinite_count_when_outward(n,r,r,.03355,sigma)
        assert stationary_rate(n,r,.03355,sigma,h)==0
        draws=rng.geometric(outward['reset_group_escape'],size=400000).astype(np.float64)-1
        sem=draws.std(ddof=1)/math.sqrt(len(draws))
        assert abs(draws.mean()-outward['expected_total_from_initial'])<5*sem
        rows.append({'n':n,'unit_zero_drift_moments':moments,'zero_drift_rate':rate,'zero_drift_asymptotic_count_fano_if_finite':fano,
                     'source_outward_infinite_count':outward,'source_outward_count_geometric_mc':float(draws.mean()),
                     'source_outward_count_geometric_mc_se':float(sem),'inward_drift_rates':{str(mu):stationary_rate(n,r,mu,sigma,h)
                     for mu in (-.08,-.02,-.005,-.001)}})
    data={'reset':r,'sigma':sigma,'h':h,'source_outward_drift':.03355,'rows':rows,'max_absolute_moment_integral_disagreement':maximum,
          'geometric_MC_sequences':2800000,'scope':'Finite n with mutually independent Brownian paths and complete resets, fixed coefficients. A model unit of time has no assumed conversion to biological seconds.',
          'source':hashlib.sha256(Path(__file__).with_name('tonic_microdomains.py').read_bytes()).hexdigest()}
    out.write_text(json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print([(v['n'],v['zero_drift_rate'],v['source_outward_infinite_count']['expected_total_from_initial']) for v in rows])
    print('max absolute quadrature disagreement',maximum)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);main(p.parse_args().output)
