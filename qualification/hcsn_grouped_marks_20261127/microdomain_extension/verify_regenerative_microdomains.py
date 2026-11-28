"""Compare repeated-event brackets with a single-path identity and independent exact waiting-time draws."""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import torch
from scipy.special import log_ndtr

from regenerative_microdomains import repeated_count_bounds


def cdf(distance, time, n, drift, sigma):
    if distance<=0: return 1.
    if time<=0: return 0.
    scale=sigma*math.sqrt(time)
    p=math.exp(min(0.,np.logaddexp(log_ndtr((-distance-drift*time)/scale),
                                   -2*drift*distance/sigma**2+log_ndtr((drift*time-distance)/scale))))
    return -math.expm1(n*math.log1p(-p)) if p<1 else 1.


def wait_draw(rng, distance, size, copies, drift, sigma):
    """Wald for drift toward the wall, defective Wald for outward drift, and Levy at zero drift."""
    if distance<=0: return np.zeros(size)
    shape=(size,copies)
    if drift==0.:
        waits=(distance/(sigma*rng.standard_normal(shape)))**2
    else:
        waits=rng.wald(distance/abs(drift),(distance/sigma)**2,size=shape)
        if drift>0:
            waits=np.where(rng.uniform(size=shape)<math.exp(-2*drift*distance/sigma**2),waits,np.inf)
    return waits.min(axis=1)


def simulate(rng, size, x, reset, copies, drift, sigma, T, h):
    t=wait_draw(rng,x,size,copies,drift,sigma)
    active=np.flatnonzero(t<=T);counts=np.zeros(size,dtype=np.int16)
    while len(active):
        counts[active]+=1
        t[active]+=h+wait_draw(rng,reset,len(active),copies,drift,sigma)
        active=active[t[active]<=T]
    return float(counts.mean()),float(counts.std(ddof=1)/math.sqrt(size))


def main(out):
    torch.set_num_threads(1)
    seed=2732108;rng=np.random.default_rng(seed)
    T,h,sigma,reset=.25,.025,.23,.085
    rows=[];max_gradient_error=0.
    for drift in (-.2,0.,.03355):
        for n in (1,2,4,8):
            for x in (.07,0.):
                samples=100000
                mean,se=simulate(rng,samples,x,reset,n,drift,sigma,T,h)
                naive = sum(cdf(x+(k-1)*reset,T-(k-1)*h,n,drift,sigma)
                            for k in range(1,round(T/h)+2))
                brackets=[]
                for bins in (80,160,320,640,1280):
                    dist=torch.tensor(x,dtype=torch.float64,requires_grad=True)
                    rho=torch.tensor(reset,dtype=torch.float64,requires_grad=True)
                    bound=repeated_count_bounds(dist,rho,n,drift,sigma,T,h,bins)
                    a,b=float(bound.lower.detach()),float(bound.upper.detach())
                    assert a<=b+2e-12 and a>=0 and b<=1+T/h+1e-12
                    assert torch.all(bound.per_event_lower<=bound.per_event_upper+2e-13)
                    if n==1:assert a-3e-12<=naive<=b+3e-12
                    if brackets:
                        assert brackets[-1][1]<=a+3e-12 and b<=brackets[-1][2]+3e-12
                    brackets.append([bins,a,b])
                    if bins==320 and x>0:
                        grad=torch.autograd.grad((bound.lower+bound.upper)/2,(dist,rho))
                        def mid(D,R):
                            v=repeated_count_bounds(torch.tensor(D,dtype=torch.float64),torch.tensor(R,dtype=torch.float64),n,drift,sigma,T,h,bins)
                            return float((v.lower+v.upper)/2)
                        eps=1e-6;fd=[(mid(x+eps,reset)-mid(x-eps,reset))/(2*eps),
                                    (mid(x,reset+eps)-mid(x,reset-eps))/(2*eps)]
                        err=max(abs(float(v)-f)/max(1.,abs(f)) for v,f in zip(grad,fd))
                        assert err<2e-7,(n,drift,x,err);max_gradient_error=max(max_gradient_error,err)
                gap=max(a-mean,mean-b,0.)/max(se,1e-300)
                assert gap<4.5,(n,drift,x,mean,se,a,b)
                rows.append({'drift':drift,'copies':n,'x':x,'simulation_paths':samples,'simulation_mean':mean,
                             'simulation_se':se,'gap_outside_finest_grid_interval_in_MC_standard_errors':gap,
                             'single_path_distance_series_substituting_n_copy_cdf':naive,'grid_bounds':brackets})
    source=Path(__file__).with_name('regenerative_microdomains.py')
    import hashlib
    value={'seed':seed,'horizon':T,'volatility':sigma,'reset':reset,'refractory':h,'samples_drawn':len(rows)*samples,
           'finite_difference_relative_error_max_midpoint_at_320_bins':max_gradient_error,
           'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
           'verification_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'rows':rows,
           'scope':'Monte Carlo uses independent pathwise Wald/Levy waiting times. Grid nesting and the probability brackets are mathematical properties in exact arithmetic; no outward rounding certificate is claimed.'}
    out.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')
    for row in rows:
        if row['drift']==.03355 and row['x']==.07:
            print(row['copies'],row['grid_bounds'][-1],row['single_path_distance_series_substituting_n_copy_cdf'],row['simulation_mean'],row['simulation_se'])
    print('cases',len(rows),'simulated',value['samples_drawn'],'max outlying MC SE',max(r['gap_outside_finest_grid_interval_in_MC_standard_errors'] for r in rows),'grad max relative',max_gradient_error)


if __name__=='__main__':
    cli=argparse.ArgumentParser();cli.add_argument('output',type=Path);main(cli.parse_args().output)
