"""Deterministic, bounded, fail-closed P0+P2 research diagnostics.

Executable from repo root via:
  python -m experiments.hcsn_hx_unified_v3.p0_p2_diagnostic
No source-data access, no trained checkpoint, no GPU/CI claims.
"""
from __future__ import annotations
import json
import math
import random
from scipy.special import lambertw

from .regenerative_qvi_oracle_v2 import RegenerativeNeuron,UnresolvedQVI
from experiments.hcsn_distributional_v2.deterministic_refractory_reference import (
    constant_rate_stats,PathState,advance_path)


def run() -> dict:
    rng=random.Random(2026103117)
    n_p0=2500
    valid=0
    rejected=0
    max_lambert_gap=0.
    for _ in range(n_p0):
        p=RegenerativeNeuron(rng.uniform(-1,1),rng.uniform(.15,2.0),
                rng.uniform(.03,2),rng.uniform(.2,5),rng.uniform(-4,-.1),
                rng.uniform(0,2))
        try:
            s=p.solution
            z=1+lambertw(-math.exp(-p.discount*p.refractory-p.kappa*(p.cost-p.reset))
                         /math.e,k=0).real
            expected=p.cost+z/p.kappa
            max_lambert_gap=max(max_lambert_gap,abs(s.boundary-expected))
            for v in (-3,-1,-1e-5,0,1e-5,1,3):
                probe=p.qvi(s.boundary+v/s.kappa)
                if probe.max_qvi_residual>1e-12:
                    raise AssertionError('analytic QVI sign violation')
            valid+=1
        except UnresolvedQVI:
            rejected+=1
    n_p2=2500
    max_first_gap=0.
    for _ in range(n_p2):
        lam=rng.uniform(.05,8)
        tau=rng.uniform(.03,2)
        T=rng.uniform(.05,8)
        report=constant_rate_stats(lam,tau,T)
        max_first_gap=max(max_first_gap,
            abs(report.first_fire_probability-(-math.expm1(-lam*T))))
        if report.expected_event_count+1e-12<report.first_fire_probability:
            raise AssertionError('expected count smaller than first event probability')
    for _ in range(1000):
        seed=rng.randrange(2**32);tau=rng.uniform(.01,1)
        init=PathState.initial(seed,tau)
        lam=rng.uniform(.1,5);t1=rng.uniform(.03,1);t2=rng.uniform(.03,1)
        a=advance_path(advance_path(init,lam,t1),lam,t2)
        b=advance_path(init,lam,t1+t2)
        if a.fired_count!=b.fired_count:
            raise AssertionError('causal split changes event count')
    return {
        'scope':'OFFLINE_P0_QVI_SUBSET_AND_P2_RENEWAL_REFERENCE',
        'random_seed':2026103117,
        'p0_tested':n_p0,'p0_admitted':valid,'p0_explicit_refusals':rejected,
        'p0_lambert_w_max_abs_boundary_gap':max_lambert_gap,
        'p2_analytic_cases':n_p2,'p2_first_event_probability_max_abs_gap':max_first_gap,
        'p2_split_stream_cases':1000,
        'exact_HX_coupled_equilibrium':False,
        'native_Rust_GPU_executed':False,
        'all_blockers_closed':False,'production_activation_allowed':False,
        'decision':'DENY_ALL_RESEARCH_ONLY'
    }

if __name__ == '__main__':
    print(json.dumps(run(),ensure_ascii=False,indent=2,sort_keys=True))
