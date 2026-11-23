"""Independent positive time/space integrals for delayed marked renewal.

No imports from the candidate, released_interval or original HCSN modules.
Time and space Gauss nodes have independent orders. Spatial integration uses
the positive killed Brownian image factor, never a reflected Gaussian CDF
difference. Rare point values use a separate arbitrary-precision inversion.
"""
import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import time

import mpmath as mp
import numpy as np
from scipy.special import ndtr, roots_legendre
import scipy


HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "protocol.json").read_bytes())
ROOT_2PI = math.sqrt(2 * math.pi)
CUTS = [-39, -32, -24, -18, -12, -8, -5, -3, 0, 3, 5, 8, 12, 18, 24, 32, 39]


@lru_cache(None)
def gauss(order):
    nodes, weight = roots_legendre(order)
    return (nodes + 1) / 2, weight / 2


def time_quadrature(low, high, order):
    u, w = gauss(order)
    angle = np.pi * u / 2
    sin, cos = np.sin(angle), np.cos(angle)
    return low + (high-low)*sin**2, (high-low)*cos**2, np.pi*(high-low)*sin*cos*w


def first_density(length, elapsed, mu, sigma):
    return length / (sigma*ROOT_2PI*elapsed**1.5) * np.exp(-(length + mu*elapsed)**2/(2*sigma**2*elapsed))


def first_mass(length, low, high, mu, sigma, order):
    if high <= max(0,low):
        return 0.0
    elapsed, _, weights = time_quadrature(max(0,low), high, order)
    return float(weights @ first_density(length, elapsed, mu, sigma))


def point_density(start, t, y, mu, sigma):
    scale = sigma*np.sqrt(t)
    return np.exp(-0.5*((y-start-mu*t)/scale)**2) / (ROOT_2PI*scale) * -np.expm1(-2*start*y/(scale**2))


def surviving_bins(start, t, edges, mu, sigma, space_order):
    """Positive Gaussian/absorbing-factor integral on physical bins, vectorized in t."""
    mean = start + mu*t
    stdev = sigma*np.sqrt(t)
    u, w = gauss(space_order)
    result = np.zeros((len(t),len(edges)))
    bounds = [*edges, np.inf]
    for col,(lo,hi) in enumerate(zip(bounds,bounds[1:])):
        left, right = (lo-mean)/stdev, (hi-mean)/stdev
        for c,d in zip(CUTS,CUTS[1:]):
            low = np.maximum(c,left)
            high = np.minimum(d,right)
            chosen = np.flatnonzero(high>low)
            if not len(chosen):
                continue
            l, h = low[chosen,None], high[chosen,None]
            z = l + (h-l)*u
            y = mean[chosen,None] + stdev[chosen,None]*z
            weight = np.exp(-z*z/2)/ROOT_2PI * -np.expm1(-2*start*y/stdev[chosen,None]**2)
            result[chosen,col] += np.sum((h-l)*w*weight,axis=1)
    return result


@lru_cache(maxsize=256)
def physics(x,mu,sigma,a,delay,horizon,edges,ys,phase_edges,to,so):
    counts = int(math.floor(horizon/delay))
    spatial, density, phase, cumulative, rates = [], [], [], [], []
    spatial.append(surviving_bins(x,np.array([horizon]),edges,mu,sigma,so)[0])
    density.append(point_density(x,np.array([horizon]),np.array(ys),mu,sigma))
    for n in range(1,counts+2):
        length = x+(n-1)*a
        h = horizon-n*delay
        hit_time = horizon-(n-1)*delay
        cumulative.append(first_mass(length,0,hit_time,mu,sigma,to))
        rates.append(float(first_density(length,hit_time,mu,sigma)) if hit_time>0 else 0.0)
        phase.append([first_mass(length,h+delay*l,h+delay*r,mu,sigma,to) for l,r in zip(phase_edges,phase_edges[1:])])
        if h<=0:
            continue
        s, remaining, weights = time_quadrature(0,h,to)
        hit_weights = weights * first_density(length,s,mu,sigma)
        spatial.append(hit_weights @ surviving_bins(a,remaining,edges,mu,sigma,so))
        density.append(hit_weights @ point_density(a,remaining[:,None],np.array(ys),mu,sigma))
    return tuple(map(np.array,(spatial,density,phase,cumulative,rates)))


def compute(values, edges=tuple(SPEC["edges"]), ys=tuple(SPEC["target_y"]), to=256, so=32):
    x,mu,sigma,a,d,t,m,n,*r = values
    state = physics(x,mu,sigma,a,d,t,edges,ys,tuple(SPEC["phase_fraction_edges"]),to,so)
    active,density,phase,cum,rate = state
    mat = np.array(r).reshape((2,2))
    marks = [np.array([m,n])]
    for _ in range(max(len(active),len(phase))-1):
        marks.append(mat@marks[-1])
    marks = np.array(marks)
    active_marks = active[:,:,None]*marks[:len(active),None,:]
    phase_marks = phase[:,:,None]*marks[:len(phase),None,:]
    density_marks = density[:,:,None]*marks[:len(active),None,:]
    pc = np.r_[active.sum(axis=0),phase.sum(axis=0)]
    cc = np.vstack([active_marks.sum(axis=0),phase_marks.sum(axis=0)])
    cv,ev = cum@marks[:len(cum)],rate@marks[:len(rate)]
    msize,dim=cc.shape
    objective = pc @ (np.arange(1,msize+1)/msize) + np.sum(cc*(np.arange(1,msize*dim+1).reshape(cc.shape)/(msize*dim))) + np.dot([.37,-.21],cv)+np.dot([-.08,.04],ev)
    return {"active_by_release":active.tolist(),"density_by_release":density.tolist(),"phase_by_hit":phase.tolist(),
            "event_probability_by_hit":cum.tolist(),"event_rate_by_hit":rate.tolist(),"marks":marks.tolist(),
            "P":pc.tolist(),"C":cc.tolist(),"density":density.sum(axis=0).tolist(),"density_content":density_marks.sum(axis=0).tolist(),
            "cumulative_hits":float(cum.sum()),"event_rate":float(rate.sum()),
            "marked_cumulative_hits":cv.tolist(),"marked_event_rate":ev.tolist(),
            "mass_residual":float(pc.sum()-1),"objective":float(objective)}


def inverse_check(n,y,config):
    with mp.workdps(62):
        x,mu,sigma,a,d,t=map(lambda v:mp.mpf(str(v)),config[:6])
        y=mp.mpf(str(y))
        def transform(p):
            k=mp.sqrt(mu*mu + 2*sigma**2*p)/sigma**2
            hit=lambda b:mp.exp(-b*(mu/sigma**2+k))
            killed=mp.exp(mu*(y-a)/sigma**2)*(mp.exp(-k*abs(y-a))-mp.exp(-k*(y+a)))/(sigma**2*k)
            return hit(x)*hit(a)**(n-1)*killed
        return float(mp.invertlaplace(transform,t-n*d,method="dehoog"))


def check_accounts(config, result):
    x,mu,sigma,a,d,t = config[:6]
    def cdf(length, h):
        if h <= 0:
            return 0.0
        scale = sigma*math.sqrt(h)
        return float(ndtr((-length-mu*h)/scale)+math.exp(-2*mu*length/sigma**2)*ndtr((-length+mu*h)/scale))
    active = np.sum(result["active_by_release"],axis=1)
    phase = np.sum(result["phase_by_hit"],axis=1)
    expected_active = [1-cdf(x,t)]
    expected_phase, expected_hits = [], []
    for n in range(1,len(phase)+1):
        z = x+(n-1)*a
        h = t-n*d
        expected_hits.append(cdf(z,t-(n-1)*d))
        expected_phase.append(expected_hits[-1]-cdf(z,h))
        if h > 0:
            expected_active.append(cdf(z,h)-cdf(z+a,h))
    balances={}
    for key, actual, expected in (("active_by_release_mass", active, expected_active),
                                   ("phase_by_hit_mass", phase, expected_phase),
                                   ("nth_hit_probability", result["event_probability_by_hit"], expected_hits)):
        diff = np.abs(np.array(actual)-expected)
        vals = np.array(expected)
        assert np.all(vals>0) and np.max(diff/vals) < 3e-11
        balances[key] = {"max_absolute":float(np.max(diff)), "max_relative":float(np.max(diff/vals))}
    return balances


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--timing",type=Path)
    args=p.parse_args()
    start=time.perf_counter()
    base=[SPEC[k]for k in ("x","mu","sigma","a","d")]+[.61,*SPEC["m0"],*np.array(SPEC["R"]).ravel().tolist()]
    report={"schema":"hepta.independent-marked-time-quadrature.v1","protocol_sha256":hashlib.sha256((HERE/"protocol.json").read_bytes()).hexdigest(),
            "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"versions":{"numpy":np.__version__,"scipy":scipy.__version__,"mpmath":mp.__version__},
            "horizons":{},"refinement":{}}
    for t in SPEC["horizons"]:
        v=base.copy();v[5]=t
        coarse=compute(v,to=128,so=20);fine=compute(v)
        report["horizons"][str(t)]=fine
        err={}
        for k in ("active_by_release","density_by_release","phase_by_hit","event_probability_by_hit","event_rate_by_hit","P","C","marked_cumulative_hits","marked_event_rate"):
            one,two=np.array(coarse[k]),np.array(fine[k]);diff=np.abs(one-two)
            nonzero=np.abs(two)>1e-280
            err[k]={"max_abs":float(np.max(diff)),"max_rel_above_1e-280":float(np.max(diff[nonzero]/np.abs(two[nonzero]))) if nonzero.any()else 0.0}
        report["refinement"][str(t)]=err
    fd={}
    for i,name in enumerate(("x","mu","sigma","a","d","T","m0_0","m0_1","R00","R01","R10","R11")):
        vals=[]
        for step in (2e-5,1e-5):
            f=[]
            for scale in (2,1,-1,-2):
                shifted=base.copy();shifted[i]+=step*scale
                f.append(compute(shifted)["objective"])
            vals.append((-f[0]+8*f[1]-8*f[2]+f[3])/(12*step))
        fd[name]={"h_2e-5":vals[0],"h_1e-5":vals[1],"abs_difference":abs(vals[0]-vals[1])}
    report["objective_fd"]=fd
    rr=SPEC["rare"]
    config=[rr[k] for k in ("x","mu","sigma","a","d","T")]+base[6:]
    rare=compute(config,edges=tuple(rr["edges"]),ys=tuple(rr["target_y"]))
    report["rare"]=rare
    report["named_mass_accounts"]={"rare":check_accounts(config,rare)}
    for t in SPEC["horizons"]:
        v=base.copy();v[5]=t
        report["named_mass_accounts"][str(t)]=check_accounts(v,report["horizons"][str(t)])
    report["inverse_laplace_point_checks"]=[]
    for n,cfg,ys,data in [(4,base,SPEC["target_y"],report["horizons"]["0.61"]),(1,config,rr["target_y"],rare)]:
        for j,y in enumerate(ys):
            direct=data["density_by_release"][n][j]
            inverted=inverse_check(n,y,cfg)
            report["inverse_laplace_point_checks"].append({"n":n,"T":cfg[5],"y":y,"time_quadrature":direct,"mp_dehoog":inverted,"relative":abs(inverted-direct)/abs(inverted)})
    assert all(abs(d["mass_residual"])<2e-11 for d in report["horizons"].values())
    assert max(r["relative"] for r in report["inverse_laplace_point_checks"]) < 2e-9
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    if args.timing:
        args.timing.write_text(json.dumps({"wall_seconds":time.perf_counter()-start, "output_sha256":hashlib.sha256(args.output.read_bytes()).hexdigest()},indent=2)+"\n")


if __name__=="__main__":
    main()
