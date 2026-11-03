"""Iteration 9, research-only, reproducible stochastic moving-boundary evidence.

Reuses independent first-hitting-time density, finite differences and exact
conditional Brownian bridges. Produces a SOURCE-BOUND evidence JSON. No gate
receives external scientific attestation and no production path is enabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import torch
try:
    from .moving_boundary_first_passage import (
        affine_hitting_torch, density_reference, sample_affine_hitting,
        piecewise_affine_hitting_mc)
except ImportError:
    from moving_boundary_first_passage import (
        affine_hitting_torch, density_reference, sample_affine_hitting,
        piecewise_affine_hitting_mc)


def scalar(a): return torch.tensor(a,dtype=torch.float64)


def _call(v):
    r=affine_hitting_torch(*(scalar(x) for x in v))
    return float(r.probability),float(r.discounted_probability)


def run():
    torch.set_num_threads(1)
    rng=np.random.default_rng(12001)
    panels=[]
    for k in range(96):
        vals=[float(np.exp(rng.uniform(math.log(1e-4),math.log(2.)))),
              float(np.exp(rng.uniform(math.log(.08),math.log(7.)))),
              float(rng.uniform(-.3,.3)),float(rng.uniform(.11,.85)),
              float(rng.uniform(-.18,.18)),float(rng.uniform(0.,.25))]
        analytic=_call(vals)
        independent=density_reference(*vals)
        panels.append({'index':k,'parameters':vals,'analytic':analytic,
                       'independent_density':independent,
                       'absolute_errors':[abs(a-b) for a,b in zip(analytic,independent)]})

    v=[.37,2.4,.04,.32,.07,.095]
    xs=[scalar(a).requires_grad_(True) for a in v]
    val=affine_hitting_torch(*xs).discounted_probability
    derivatives=[float(x) for x in torch.autograd.grad(val,xs)]
    derivative_errors=[]
    for k in range(6):
        h=2.e-5*max(1.,abs(v[k]))
        u=v.copy();d=v.copy();u[k]+=h;d[k]-=h
        df=(density_reference(*u)[1]-density_reference(*d)[1])/(2*h)
        derivative_errors.append(abs(df-derivatives[k]))

    mc=[]
    for mu in [-.15,0.,.15]:
        x=.34;sig=.38;T=2.8;lam=.12;slope=.05;n=140000
        times=sample_affine_hitting(x,mu+slope,sig,slope,n,seed=55)
        hit=np.isfinite(times)&(times<=T)
        f=float(hit.mean());g=float(np.where(hit,np.exp(-lam*np.minimum(times,T)),0).mean())
        af,ag=_call([x,T,mu+slope,sig,slope,lam])
        # Conservative bounded [0,1] SE for weighted probability and Bernoulli F.
        se_f=math.sqrt(f*(1-f)/n)
        se_g=math.sqrt(g*(1-g)/n)
        mc.append({'relative_drift':mu,'paths':n,'observed':[f,g],
                   'analytic':[af,ag], 'z_scores':[abs(f-af)/se_f,abs(g-ag)/se_g]})

    piecewise=[]
    x=.3; sig=.31; drift=.02; slope=.11;T=3.
    af,_=_call([x,T,drift,sig,slope,.1])
    for k in [1,3,12]:
        est=piecewise_affine_hitting_mc(x,drift,sig,np.full(k,slope),
                          np.full(k,T/k),paths=150000,seed=522)
        piecewise.append({'segments':k,'estimate':est.hit_probability,
            'standard_error':est.standard_error,'affine_exact':af,
            'z_score':abs(est.hit_probability-af)/est.standard_error})
    early=piecewise_affine_hitting_mc(.22,0.,.26,[.45,-.45],[.8,.8],
                                     paths=250000,seed=1234)
    late=piecewise_affine_hitting_mc(.22,0.,.26,[-.45,.45],[.8,.8],
                                    paths=250000,seed=1234)

    # Input QUANTIZATION sensitivity only: all special-function math runs in
    # FP64 after inputs are rounded to a given dtype. This is NOT BF16/FP32
    # kernel arithmetic and is NOT a hardware or accelerator certification.
    rng=np.random.default_rng(21212)
    quant=[]
    for _ in range(256):
        vals=[float(np.exp(rng.uniform(math.log(1e-6),math.log(1.5)))),
              float(rng.uniform(.08,4.)),float(rng.uniform(-.25,.25)),
              float(rng.uniform(.15,.6)),float(rng.uniform(-.2,.2)),
              float(rng.uniform(.005,.3))]
        ref=_call(vals)
        record={'values':vals,'fp64':ref}
        for tag,dtype in [('fp32_input',torch.float32),('bf16_input',torch.bfloat16)]:
            rounded=[float(torch.tensor(z,dtype=dtype).to(torch.float64)) for z in vals]
            got=_call(rounded)
            record[tag]={'result':got,'abs_error':[abs(a-b) for a,b in zip(ref,got)]}
        quant.append(record)

    # Feature-only CPU measurement; NOT end-to-end encoder benchmark.
    rng=np.random.default_rng(100)
    batch=2048
    data=[torch.tensor(rng.uniform(lo,hi,size=batch),dtype=torch.float64) for lo,hi in
          [(.01,1.5),(.2,5.),(-.3,.3),(.15,.7),(-.2,.2),(.005,.2)]]
    with torch.no_grad():
        for _ in range(10):affine_hitting_torch(*data)
        times=[]
        for _ in range(120):
            t0=time.perf_counter()
            affine_hitting_torch(*data)
            times.append(1000*(time.perf_counter()-t0))

    src=Path(__file__).resolve().parent
    sources=['moving_boundary_first_passage.py','test_moving_boundary_first_passage.py',
             'p2_affine_stochastic_evidence.py']
    record={
      'schema':'hcsn.p2.affine-moving-stochastic-evidence.v1',
      'scope':'research-only; not globally HX certified; NO P0-P6 phase closed',
      'device':str(data[0].device),'torch':torch.__version__,
      'source_sha256':{name:hashlib.sha256((src/name).read_bytes()).hexdigest() for name in sources},
      'density_panel_count':len(panels),
      'max_abs_analytic_vs_independent_density':max(max(p['absolute_errors']) for p in panels),
      'density_panels':panels,
      'autograd_via_density_fd_max_abs_error':max(derivative_errors),
      'autograd_component_errors':derivative_errors,
      'mc_exact_first_hit':mc,
      'piecewise_bridge_affine_checks':piecewise,
      'boundary_history':{
          'same_final_boundary':True,
          'early_high_hit_probability':early.hit_probability,
          'late_high_hit_probability':late.hit_probability,
          'early_minus_late':early.hit_probability-late.hit_probability,
          'early_se':early.standard_error,'late_se':late.standard_error,
          'paths_per_case':250000,
      },
      'quantization_policy':'round INPUTS to FP32 or BF16; EVALUATE kernel in FP64; no low-precision arithmetic claim',
      'quantized_input_panels':len(quant),
      'max_abs_fp32_input_quantization':max(max(x['fp32_input']['abs_error']) for x in quant),
      'max_abs_bf16_input_quantization':max(max(x['bf16_input']['abs_error']) for x in quant),
      'cpu_feature_only_batch':batch,
      'cpu_feature_only_ms_p50':float(np.percentile(times,50)),
      'cpu_feature_only_ms_p99':float(np.percentile(times,99)),
      'p0_scientific_gate':'OPEN','p1_scientific_gate':'OPEN','p2_scientific_gate':'OPEN',
      'p3_scientific_gate':'OPEN','p4_scientific_gate':'OPEN',
      'p5_scientific_gate':'OPEN','p6_scientific_gate':'OPEN',
      'production_activation':False,
      'external_scientific_attestation':False,
    }
    if (record['max_abs_analytic_vs_independent_density']>=1e-9
        or record['autograd_via_density_fd_max_abs_error']>=2e-8
        or any(max(z['z_scores'])>=6. for z in mc)
        or any(z['z_score']>=6. for z in piecewise)):
        raise ArithmeticError('Research validation tolerance violated')
    return record


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    result=run()
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k in (
       'density_panel_count','max_abs_analytic_vs_independent_density',
       'autograd_via_density_fd_max_abs_error','boundary_history',
       'max_abs_fp32_input_quantization','max_abs_bf16_input_quantization',
       'cpu_feature_only_ms_p50','cpu_feature_only_ms_p99')},indent=2))

if __name__=='__main__':main()
