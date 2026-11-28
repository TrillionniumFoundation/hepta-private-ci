"""Check the scientific likelihood on deterministic artificial inputs before fitting any recorded neuron."""
import json,math,sys
from pathlib import Path
import numpy as np
from scipy import integrate,stats
from isi_likelihood import ARMS,RiskSet,standardized,contributions
from prepare_isi import sha,write_once


def check():
    largest_pdf=largest_sf=largest_integral=0.;comparisons=0
    times=np.geomspace(1e-3,30.,130)
    for k in (.2,1.,4.,20.):
        distributions={'ig1':stats.invgauss(1/k,scale=k),'gamma':stats.gamma(k,scale=1/k),
                       'lognormal':stats.lognorm(1/math.sqrt(k),scale=math.exp(-.5/k)),
                       'exponential':stats.expon()}
        for name in ARMS:
            d=distributions['ig1' if name.startswith('ig') else name]
            n=int(name[2:]) if name.startswith('ig') else 1
            lp,ls=standardized(name,k,times)
            expect_lp=math.log(n)+d.logpdf(times)+(n-1)*d.logsf(times)
            expect_ls=n*d.logsf(times)
            largest_pdf=max(largest_pdf,float(np.max(np.abs(lp-expect_lp))))
            largest_sf=max(largest_sf,float(np.max(np.abs(ls-expect_ls))))
            def dens(y):
                u=np.array([math.exp(y)])
                value=standardized(name,k,u)[0][0]+y
                return math.exp(value) if value>-745 else 0.
            # Integral on log time; known tail survival terms account for the small excluded probability.
            bins=30;left=-25;right=12
            total=integrate.quad(dens,left,right,epsabs=1e-10,epsrel=1e-10,limit=140)[0]
            low=1-math.exp(float(standardized(name,k,np.array([math.exp(left)]))[1][0]))
            high=math.exp(float(standardized(name,k,np.array([math.exp(right)]))[1][0]))
            largest_integral=max(largest_integral,abs(total+low+high-1));comparisons+=len(times)
    assert largest_pdf<2e-9 and largest_sf<2e-9 and largest_integral<2e-9
    rows=[{'cell':1,'current':0.,'duration':.63,'spikes_s':[.1,.16,.23,.29]},
          {'cell':1,'current':0.,'duration':.8,'spikes_s':[.13]},
          {'cell':2,'current':0.,'duration':.32,'spikes_s':[]}]
    dataset=RiskSet.build(rows);rate=12.;dead=.0005
    terminal=contributions(dataset,'exponential',[-math.log(rate),0.],'stationary').sum()
    exact=3*math.log(rate)-rate*sum(max(0.,t-dead) for t in dataset.interval)
    assert abs(terminal-exact)<1e-12 and abs(dataset.exposure.sum()-1.20)<1e-12
    return {'numerical_probability_comparisons':comparisons,'max_log_density_error_vs_scipy':largest_pdf,
            'max_log_survival_error_vs_scipy':largest_sf,'max_integrated_mass_error':largest_integral,
            'manufactured_censored_exponential_loglik_error':abs(terminal-exact),
            'likelihood_sha256':sha(Path(__file__).with_name('isi_likelihood.py').read_bytes())}


if __name__=='__main__':
    result=check();write_once(Path(sys.argv[1]),result);print(result)
