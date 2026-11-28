"""Binary branch decoding for specified finite, independent tagged-particle observations."""
import argparse
import json
import math
from pathlib import Path

from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import ndtri, ndtr, log_ndtr
from scipy.stats import binom

RESET, DELAY, D = .3, .25, .23**2 / 2


def stationary_spike(u, window):
    mean = RESET/u + DELAY
    t = window-DELAY
    if t <= 0:
        return window/mean
    a, sigma = RESET, math.sqrt(2*D*t)
    positive = ndtr((u*t-a)/sigma)
    image = math.exp(u*a/D + log_ndtr((-u*t-a)/sigma))
    truncated_first = a/u*(positive-image)
    positive_tail = a/u-truncated_first-t*(1-positive-image)
    return 1-positive_tail/mean


def check_spike(u, window):
    def survive(t):
        return ndtr((RESET-u*t)/math.sqrt(2*D*t))-math.exp(u*RESET/D+log_ndtr((-u*t-RESET)/math.sqrt(2*D*t)))
    add = quad(survive, 0, window-DELAY, epsabs=1e-13)[0] if window > DELAY else 0.
    return (min(window,DELAY)+add)/(RESET/u+DELAY)


def optimal_risk(n, p, q):
    # Under q > p the likelihood ratio is increasing in the observed count.
    log0 = math.log1p(-(q-p)/(1-p))
    k = math.ceil(-n*log0/(math.log1p((q-p)/p)-log0))
    return .5*(binom.sf(k-1,n,p)+binom.cdf(k-1,n,q))


def required(p, q, target=.05):
    hi = 1
    while optimal_risk(hi,p,q) > target:
        hi *= 2
    lo = 0
    while lo+1 < hi:
        mid = (lo+hi)//2
        if optimal_risk(mid,p,q) <= target:
            hi = mid
        else:
            lo = mid
    return dict(p_low=float(p),p_high=float(q),N=hi,risk=float(optimal_risk(hi,p,q)),
                preceding_risk=float(optimal_risk(hi-1,p,q)) if hi>1 else .5,
                risk_1000=float(optimal_risk(1000,p,q)))


def run(src):
    points = json.loads(src.read_text())
    rows={}
    for name,names in [('sender',('source_low','source_high')),
                       ('low_receiver',('receiver_low_low','receiver_high_low')),
                       ('high_receiver',('receiver_low_high','receiver_high_high'))]:
        low,high = [float(points[n]['u'][0]) for n in names]
        rates = [u/(RESET+DELAY*u) for u in (low,high)]
        row = {'refractory_snapshot':required(*(DELAY*j for j in rates))}
        for t in (.25, .5, 1., 2., 4.):
            ps = [stationary_spike(u,t) for u in (low,high)]
            if max(abs(check_spike(u,t)-p) for u,p in zip((low,high),ps))>2e-12:
                raise ArithmeticError("Residual-life quadrature mismatch")
            row[str(t)] = required(*ps)
        rows[name]=row
    # The receiver drive obeys atanh(v) = atanh(base) + log(B/B0).
    v_high = float(points["receiver_high_high"]["v"][0])
    v_low = float(points["receiver_low_high"]["v"][0])
    dy = math.atanh(v_high) - math.atanh(v_low)
    # Equal-prior Gaussian readout error at the midpoint is Phi(-gap/(2 sigma)).
    return dict(prior_high=.5,observation="Independent stationary tagged particles conditional on deterministic mean field; one binary indicator per trajectory",rows=rows,
                wall_gap=dy,max_iid_gaussian_wall_sd_for_single_95_percent=dy/(2*ndtri(.95)))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('operating_points',type=Path)
    args=parser.parse_args()
    data=run(args.operating_points)
    Path(__file__).with_name('readout_noise.json').write_text(json.dumps(data,indent=2)+'\n')
    for n,d in data['rows'].items(): print(n,{t:z['N'] for t,z in d.items()})
    print(data['max_iid_gaussian_wall_sd_for_single_95_percent'])
