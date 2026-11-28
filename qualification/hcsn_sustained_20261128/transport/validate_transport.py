"""Independent CPU comparison and time/memory measurements against the dense HCSN law."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

import numpy as np
import scipy
from scipy.special import ndtr

from fft_transport import transported_mass

LAW = dict(sigma=.23, a=(.08-.02-.23**2/2)/.23**2, dt=.25)


def dense(mass, shift, grid, *, sigma, a, dt, gradient=False):
    """Scalar Gaussian CDF antiderivative at every bin edge, or its shift derivative."""
    x = np.maximum(grid + shift[..., None], 0)
    scale, drift = sigma * np.sqrt(dt), a * sigma**2 * dt
    edges = np.r_[0., (grid[1:] + grid[:-1])/2, np.inf].astype(grid.dtype)
    u = (edges - x[..., None] - drift)/scale
    v = (edges + x[..., None] - drift)/scale
    w = np.exp(-2*a*x)
    F, M = ndtr(u), ndtr(v)
    live = grid + shift[..., None] > 0
    q = ndtr((-x-drift)/scale) + w*ndtr((-x+drift)/scale)
    if gradient:
        phi = lambda z: np.exp(-z*z/2)/math.sqrt(2*math.pi)
        cdf_derivative = -phi(u)/scale + w[..., None]*(2*a*M - phi(v)/scale)
        # Derivative at infinity: 2*a*w, which also follows from this expression.
        kernel = np.diff(cdf_derivative, axis=-1)
        hit = (-phi((-x-drift)/scale)/scale
               + w*(-2*a*ndtr((-x+drift)/scale)-phi((-x+drift)/scale)/scale))
        hit = np.where(live, hit, 0.)
    else:
        kernel = np.maximum(np.diff(F, axis=-1)-w[..., None]*np.diff(M, axis=-1), 0.)
        hit = np.where(live, q, 1.)
    kernel = np.where(live[..., None], kernel, 0.)
    return (mass[..., None]*kernel).sum(-2), (mass*hit).sum(-1)


def case(k, count, shift_kind, seed, dtype, profile="distributed"):
    rng = np.random.default_rng(seed)
    grid = np.linspace(.015, 1.30, k).astype(dtype)
    mass = rng.random((count, k))**2
    if profile == "one_hot":
        mass = np.eye(k)[rng.integers(k, size=count)]
    mass /= mass.sum(-1, keepdims=True)
    if shift_kind == "typical":
        shift = rng.uniform(-.22,.22,count)
    elif shift_kind == "all_stopped":
        shift = rng.uniform(-2.,-1.35,count)
    elif shift_kind == "contact":
        shift = -grid[rng.integers(0,k,count)]
    else:
        shift = rng.uniform(.20,.60,count)
    return mass.astype(dtype), shift.astype(dtype), grid


def verify():
    maxima = {}
    closest = 1.
    for dtype in (np.float64, np.float32):
        metrics = {}
        for k in (3, 7, 8, 16, 63, 128, 255):
            for profile in ("distributed", "one_hot"):
                for kind in ("typical","all_stopped","contact","positive"):
                    m,d,g = case(k, 4, kind, k+13, dtype, profile)
                    for a in (LAW['a'], 0., -1.):
                        law = dict(LAW, a=a)
                        ref, h = dense(m,d,g,**law)
                        actual, hf = transported_mass(m,d,g,**law)
                        for key, error in (
                            ("live_max_abs",np.max(abs(actual-ref))),
                            ("flow_max_abs",np.max(abs(h-hf))),
                            ("mass_balance_max_abs",np.max(abs(actual.sum(-1)+hf-m.sum(-1))))
                        ):
                            metrics[key]=max(metrics.get(key,0.),float(error))
            if dtype == np.float64:
                # Stay strictly on a smooth piece while testing shift and mass pullbacks.
                m,d,g = case(k, 4, "typical", k+51, dtype)
                distance = float(np.min(abs(g+d[...,None])))
                closest = min(closest,distance)
                eps = min(1e-6,distance/4)
                rng=np.random.default_rng(k)
                psi,eta = rng.normal(size=m.shape), rng.normal(size=d.shape)
                def scalar(mm,dd):
                    bins,hit=transported_mass(mm,dd,g,**LAW)
                    return (bins*psi).sum(-1)+hit*eta
                dx,dh=dense(m,d,g,**LAW,gradient=True)
                expected=(psi*dx).sum(-1)+eta*dh
                observed=(scalar(m,d+eps)-scalar(m,d-eps))/(2*eps)
                dm=rng.uniform(-.3,.3,m.shape)*m
                db,df=dense(dm,d,g,**LAW)
                dm_expected=(psi*db).sum(-1)+eta*df
                dm_observed=(scalar(m+1e-5*dm,d)-scalar(m-1e-5*dm,d))/(2e-5)
                for key, err in (("shift_vjp_max_abs",np.max(abs(expected-observed))),
                                 ("mass_directional_max_abs",np.max(abs(dm_observed-dm_expected)))):
                    metrics[key]=max(metrics.get(key,0.),float(err))
        tol=2e-11 if dtype == np.float64 else 5e-5
        if any(metrics[k]>tol for k in ("live_max_abs","flow_max_abs","mass_balance_max_abs")):
            raise ValueError(f"{dtype}: {metrics}")
        if dtype == np.float64 and (metrics["shift_vjp_max_abs"]>2e-7 or metrics["mass_directional_max_abs"]>2e-9):
            raise ValueError(f"derivatives: {metrics}")
        maxima[np.dtype(dtype).name]=metrics
    maxima["minimum_margin_distance_for_two_sided_derivative"]=closest
    return maxima


def trajectory():
    k,n,t=64,5,60
    m,d,g=case(k,n,"typical",816,np.float64)
    rng=np.random.default_rng(20261128)
    ext=rng.uniform(-.21,.21,(t,n))
    reset=np.zeros(k)
    i=np.searchsorted(g,.30)
    reset[i]=(.30-g[i-1])/(g[i]-g[i-1]); reset[i-1]=1-reset[i]
    def run(fn):
        mass=m.copy(); ref=np.zeros(n); old=np.zeros(n); outputs=[]
        for drive in ext:
            boundary=.25*np.tanh(3*drive+.8*ref)
            new, hit=fn(mass,old-boundary,g,**LAW)
            mass=new+ref[:,None]*reset
            ref,old=hit,boundary
            outputs.append(np.c_[mass, ref, old])
        return np.array(outputs)
    a,b=run(dense),run(transported_mass)
    residual=float(np.max(abs(a-b)))
    balance=float(np.max(abs(b[...,:k+1].sum(-1)-1)))
    if max(residual,balance)>2e-11: raise ValueError("trajectory parity failed")
    return dict(steps=t,rows=n,atoms=k,max_abs_state_difference=residual,max_abs_mass_residual=balance)


def benchmark(k, batch, repeats):
    m,d,g = case(k, batch, "typical", 3141, np.float64)
    def measure(fn):
        start=time.perf_counter()
        bins, hit=fn(m,d,g,**LAW)
        return time.perf_counter()-start, float(bins.sum()+hit.sum())
    samples={"dense":[],"fft":[]}
    for fn in (dense,transported_mass): measure(fn)
    for i in range(repeats):
        seq=(("dense",dense),("fft",transported_mass))
        for name,fn in (seq if i%2==0 else seq[::-1]):
            elapsed,checksum=measure(fn)
            if abs(checksum-batch)>1e-9: raise ValueError("timed conservation")
            samples[name].append(elapsed)
    row=dict(atoms=k,rows=batch,median_seconds={n:statistics.median(v) for n,v in samples.items()},
             seconds=samples)
    row["median_forward_speed_ratio"]=row["median_seconds"]["dense"]/row["median_seconds"]["fft"]
    return row


def memory(method, k, count):
    m,d,g=case(k,count,"typical",9,np.float64)
    def resident(field):
        lines=Path("/proc/self/status").read_text().splitlines()
        return int(next(line.split()[1] for line in lines if line.startswith(field+":")))
    # Linux VmHWM is per executed image. ru_maxrss may retain a parent's
    # pre-exec high-water mark, hiding small allocations in a fresh subprocess.
    before=resident("VmRSS")
    (dense if method=="dense" else transported_mass)(m,d,g,**LAW)
    after=resident("VmHWM")
    return {"method":method,"k":k,"rows":count,"peak_increment_kib":after-before,
            "peak_process_kib":after,"initial_resident_kib":before}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--memory",nargs=3)
    parser.add_argument("--output",type=Path,default=Path("transport_result.json"))
    args=parser.parse_args()
    if args.memory:
        name,k,count=args.memory
        print(json.dumps(memory(name,int(k),int(count))))
        sys.exit(0)
    report={"source":"b3fdc981568ab9ce122d2fb569372651e0b4b314",
            "python":sys.version,"machine":platform.machine(),"processor":platform.processor(),
            "numpy":np.__version__,"scipy":scipy.__version__, "law":LAW,
            "tolerances":{"float64_forward":2e-11,"float32_forward":5e-5,
                          "shift_pullback":2e-7,"mass_directional":2e-9},
            "validation":verify(),"recurrent_validation":trajectory()}
    report['timing']=[benchmark(k,8,7) for k in (8,12,32,64,128,256,512)]
    report['memory']=[json.loads(subprocess.check_output(
        [sys.executable,__file__,"--memory",m,"768","8"], text=True)) for m in ("dense","fft")]
    report['files_sha256']={p:hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest()
                            for p in ("fft_transport.py","validate_transport.py")}
    args.output.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("validation","recurrent_validation","memory")},indent=2))
    print([(r['atoms'],round(r['median_forward_speed_ratio'],2)) for r in report['timing']])
