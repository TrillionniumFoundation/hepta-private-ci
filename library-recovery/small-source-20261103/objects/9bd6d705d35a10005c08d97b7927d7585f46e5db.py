"""Independent P0 metamorphic probes: no certified intervals or HX full model.

Checks first passage invariants on an interior compact parameter domain using
high-precision closed form and, for selected points, independent quadrature.
"""
from __future__ import annotations
import random
from mpmath import mp
from fpt_reference import FPT, formula, transformed_integral, boundary_derivatives


def audit(seed=20261031, n=48, dps=75):
    rng=random.Random(seed)
    checked=0
    max_quad_delta=mp.zero
    max_grad_delta=mp.zero
    tol=mp.mpf('1e-42')
    for k in range(n):
        x=rng.uniform(.08,2.0)
        drift=rng.uniform(-.8,.8)
        sigma=rng.uniform(.3,1.5)
        horizon=rng.uniform(.1,3.)
        discount=rng.uniform(.001,.7)
        p=FPT(x,drift,sigma,horizon,discount)
        with mp.workdps(dps):
            def fg(pp):
                a=formula(pp,dps)
                return mp.mpf(a['F']),mp.mpf(a['G'])
            f,g=fg(p)
            assert mp.zero<g<f<mp.one,('physical',k)
            farther=FPT(x+.12,drift,sigma,horizon,discount)
            f_far,g_far=fg(farther)
            assert f_far<=f+tol and g_far<=g+tol,('distance',k)
            later=FPT(x,drift,sigma,horizon+.3,discount)
            f_later,g_later=fg(later)
            assert f_later+tol>=f and g_later+tol>=g,('horizon',k)
            expensive=FPT(x,drift,sigma,horizon,discount+.12)
            f_q,g_q=fg(expensive)
            assert abs(f_q-f)<tol and g_q<=g+tol,('discount',k)
            f_zero,g_zero=fg(FPT(x,drift,sigma,horizon,0.))
            assert abs(f_zero-g_zero)<tol,('zero discount',k)
            if k%4==0:
                quad=transformed_integral(p,65)
                err=max(abs(f-mp.mpf(quad['F'])),abs(g-mp.mpf(quad['G'])))
                max_quad_delta=max(max_quad_delta,err)
                assert err<mp.mpf('1e-38'),('quadrature',k,str(err))
                grad=boundary_derivatives(p,75)
                e=mp.mpf(grad['abs_delta'])
                max_grad_delta=max(max_grad_delta,e)
                assert e<mp.mpf('1e-38'),('derivative',k,str(e))
            checked+=1
    return {'seed':seed,'parameter_cases':checked,'metamorphic_relations':checked*5,
            'independent_quadrature_cases':(checked+3)//4,
            'max_abs_quadrature_delta':mp.nstr(max_quad_delta,12),
            'max_abs_gradient_delta':mp.nstr(max_grad_delta,12),
            'valid_domain':'x in [.08,2], mu in [-.8,.8], sigma in [.3,1.5], T in [.1,3], q in [.001,.7]',
            'limitation':'Not global, not verified interval arithmetic, not original coupled HX model'}

if __name__=='__main__':
    print(audit())
