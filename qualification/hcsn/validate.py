"""Reproduce FP64 HX numerical evidence with exact source-file SHA256 binding.

Run from the repository root:
    PYTHONPATH=qualification python -m hcsn.validate \
        --output qualification/hcsn/evidence/kernel_reference.json

This command validates stationary scalar kernels. It does not execute PyTorch,
train a neural model, or measure throughput, GPU memory, or energy consumption.
"""

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.special import log_ndtr

from . import reference as hx


def _derivative(function, value, step):
    return (function(value-2*step)-8*function(value-step)+8*function(value+step)
            -function(value+2*step))/(12*step)


def _second_derivative(function, value, step=3e-4):
    return (-function(value+2*step)+16*function(value+step)-30*function(value)
            +16*function(value-step)-function(value-2*step))/(12*step*step)


def _check(values, tolerance):
    maximum = max(float(value) for value in values)
    return {"cases":len(values), "max_abs_error":maximum, "tolerance":tolerance,
            "passed":math.isfinite(maximum) and maximum <= tolerance}


def _smooth_pasting_integral(boundary, params):
    """Independent Green-kernel boundary condition, with the asset tail exact."""
    eta = params.roots()[3]
    bounded = quad(lambda x: math.exp(-eta*x)*(
        -(1-params.tax)*params.coupon+hx.hx_debt(x,params.maturity,params,boundary)-params.p),
        0,np.inf,epsabs=2e-11,epsrel=2e-12)[0]
    return params.delta*boundary/(eta-1)+bounded


def validate():
    started = time.perf_counter()
    checks = {}
    baseline = hx.HXParams()

    # Published A7-equivalent closed form versus an independently integrated
    # killed resolvent. Include both ell=0 and a nearly zero positive ell.
    scan = []
    parameter_screens = {}
    for sigma,maturity,ell,x in itertools.product(
            (0.05,0.2,0.7),(0.05,1.0,10.0),(0.0,1e-10,0.01,0.3),(0.01,0.1,0.5,2.0)):
        params = replace(baseline,sigma=sigma,maturity=maturity,ell=ell)
        key = (sigma,maturity,ell)
        if key not in parameter_screens:
            parameter_screens[key] = hx.parameter_feasibility(params)
        feasibility = parameter_screens[key]
        closed = hx.hx_equity_closed(x,params)
        oracle = hx.hx_equity(x,params)
        error = abs(closed-oracle)
        scan.append({"sigma":sigma,"maturity":maturity,"ell":ell,"x":x,
                     "boundary":hx.hx_boundary(params),"equity_closed":closed,
                     "equity_oracle":oracle,"absolute_error":error,
                     "scaled_error":error/(1+abs(oracle)),
                     "feasibility":feasibility,
                     "sample_equity_nonnegative":oracle >= -1e-9*(1+abs(feasibility["boundary"]))})
    checks["equity_closed_vs_independent_resolvent_scaled"] = _check(
        [row["scaled_error"] for row in scan],2e-9)
    counterexample = replace(baseline,sigma=0.2,maturity=0.05,ell=0.3)
    counterexample_screen = hx.parameter_feasibility(counterexample)
    counterexample_equity = hx.hx_equity(0.01,counterexample)
    checks["inadmissible_formal_solution_is_identified"] = {
        "passed":not counterexample_screen["local_admissible"] and counterexample_equity < 0,
        "parameters":asdict(counterexample),"feasibility":counterexample_screen,
        "equity_at_margin_0_01":counterexample_equity,
        "meaning":"ODE equality alone does not prove limited-liability equity admissibility."}

    cdf_errors, discounted_errors, laplace_errors, cdf_gradient_errors = [],[],[],[]
    for mu,sigma,x in itertools.product((-0.08,0.0,0.08),(0.2,0.5),(0.05,0.2,0.7,1.2)):
        pdf = lambda t: hx.first_passage_density(t,x,mu,sigma)
        for horizon in (0.25,1.0,3.0):
            integral = quad(pdf,0,horizon,epsabs=1e-12,epsrel=1e-11)[0]
            discounted = quad(lambda t: math.exp(-0.03*t)*pdf(t),0,horizon,
                              epsabs=1e-12,epsrel=1e-11)[0]
            cdf_errors.append(abs(integral-hx.first_passage_cdf(x,horizon,mu,sigma)))
            discounted_errors.append(abs(discounted-hx.discounted_first_passage(x,horizon,mu,sigma,0.03)))
            scale = sigma*math.sqrt(horizon)
            reflected = math.exp(-2*mu*x/sigma**2+log_ndtr((-x+mu*horizon)/scale))
            density = math.exp(-0.5*((-x-mu*horizon)/scale)**2)/math.sqrt(2*math.pi)
            analytic = -2*density/scale-2*mu/sigma**2*reflected
            numerical = _derivative(lambda xx: hx.first_passage_cdf(xx,horizon,mu,sigma),x,1e-5)
            cdf_gradient_errors.append(abs(analytic-numerical))
        integral = quad(lambda t: math.exp(-0.03*t)*pdf(t),0,np.inf,
                        epsabs=1e-12,epsrel=1e-11)[0]
        laplace_errors.append(abs(integral-hx.discounted_boundary_claim(x,mu,sigma,0.03)))
    checks["cdf_vs_density_integral"] = _check(cdf_errors,2e-10)
    checks["discounted_cdf_vs_density_integral"] = _check(discounted_errors,2e-10)
    checks["infinite_discounted_claim_vs_integral"] = _check(laplace_errors,2e-10)
    checks["cdf_spatial_derivative_vs_finite_difference"] = _check(cdf_gradient_errors,2e-8)

    debt_residuals, equity_residuals, boundary_integrals = [],[],[]
    value_matching, pasting_slopes, debt_matching = [],[],[]
    residual_parameters = (baseline,replace(baseline,ell=0),
                           replace(baseline,delta=0.03,ell=0),replace(baseline,recovery=0),
                           replace(baseline,maturity=5.0))
    for params in residual_parameters:
        boundary = hx.hx_boundary(params)
        boundary_integrals.append(abs(_smooth_pasting_integral(boundary,params)))
        value_matching.append(abs(hx.hx_equity(0,params)))
        step = 1e-6
        right_slope = (-3*hx.hx_equity(0,params)+4*hx.hx_equity(step,params)
                       -hx.hx_equity(2*step,params))/(2*step)
        pasting_slopes.append(abs(right_slope))
        debt_matching.append(abs(hx.hx_debt(0,0.8,params)-params.recovery*boundary/params.maturity))
        for x in (0.04,0.1,0.4,1.0):
            equity = lambda xx: hx.hx_equity(xx,params)
            running = (params.delta*boundary*math.exp(x)-(1-params.tax)*params.coupon
                       +hx.hx_debt(x,params.maturity,params)-params.p)
            equity_residuals.append(abs(params.r*equity(x)-params.mu*_derivative(equity,x,1e-4)
                                       -params.sigma**2/2*_second_derivative(equity,x)-running))
            for horizon in (0.25,0.8):
                debt = lambda xx: hx.hx_debt(xx,horizon,params)
                derivative_t = _derivative(lambda tt: hx.hx_debt(x,tt,params),horizon,1e-5)
                debt_residuals.append(abs(derivative_t-params.mu*_derivative(debt,x,1e-4)
                                         -params.sigma**2/2*_second_derivative(debt,x)
                                         -params.c+params.q*debt(x)))
    checks["debt_pde_residual"] = _check(debt_residuals,3e-5)
    checks["equity_ode_residual"] = _check(equity_residuals,3e-5)
    checks["smooth_pasting_independent_integral"] = _check(boundary_integrals,2e-8)
    checks["equity_value_matching"] = _check(value_matching,2e-12)
    checks["equity_right_derivative_at_boundary"] = _check(pasting_slopes,2e-7)
    checks["debt_value_matching"] = _check(debt_matching,2e-10)

    # Finite differences of the boundary's closed form are compared with
    # implicit differentiation of the independently integrated condition.
    # Neither result is presented as tensor/autograd validation.
    boundary = hx.hx_boundary(baseline)
    eta = baseline.roots()[3]
    partial_b = baseline.delta/(eta-1)+baseline.recovery/baseline.maturity*quad(
        lambda x: math.exp(-eta*x)*hx.discounted_first_passage(
            x,baseline.maturity,baseline.mu,baseline.sigma,baseline.q),
        0,np.inf,epsabs=2e-12,epsrel=2e-12)[0]
    sensitivities = []
    for name,value in asdict(baseline).items():
        step = max(abs(value),0.01)*1e-4
        direct = _derivative(lambda v: hx.hx_boundary(replace(baseline,**{name:v})),value,step)
        implicit = -_derivative(lambda v: _smooth_pasting_integral(
            boundary,replace(baseline,**{name:v})),value,step/2)/partial_b
        sensitivities.append({"parameter":name,"step":step,"closed_finite_difference":direct,
                              "implicit_integral_derivative":implicit,
                              "absolute_error":abs(direct-implicit),
                              "scaled_error":abs(direct-implicit)/(1+abs(implicit))})
    checks["boundary_parameter_gradient_vs_implicit_integral_scaled"] = _check(
        [row["scaled_error"] for row in sensitivities],3e-6)

    homogeneity = []
    original = hx.evaluate(boundary*math.exp(0.2),baseline,0.5)
    for scale in (0.001,0.1,10.0,1000.0):
        params = replace(baseline,coupon=baseline.coupon*scale,principal=baseline.principal*scale)
        result = hx.evaluate(boundary*scale*math.exp(0.2),params,0.5)
        values = [abs(result["b"]/(scale*original["b"])-1),
                  abs(result["E"]/(scale*original["E"])-1),
                  abs(hx.hx_debt(0.2,0.5,params)/(scale*hx.hx_debt(0.2,0.5,baseline))-1)]
        values.extend(abs(result[key]-original[key]) for key in ("F","G","f"))
        homogeneity.extend(values)
    checks["money_scale_homogeneity"] = _check(homogeneity,2e-10)

    time_covariance=[]
    original=hx.evaluate(boundary*math.exp(0.2),baseline,0.7)
    original_debt=hx.hx_debt(0.2,0.7,baseline)
    for scale in (0.01,0.1,10.0,100.0):
        params=replace(baseline,r=baseline.r/scale,delta=baseline.delta/scale,
                       ell=baseline.ell/scale,coupon=baseline.coupon/scale,
                       sigma=baseline.sigma/math.sqrt(scale),maturity=baseline.maturity*scale)
        actual=hx.evaluate(boundary*math.exp(0.2),params,0.7*scale)
        errors={key:abs(actual[key]/original[key]-1) for key in ("b","E","F","G")}
        errors["f_inverse_time"]=abs(actual["f"]*scale/original["f"]-1)
        errors["debt_per_maturity_unit_inverse_time"]=abs(hx.hx_debt(0.2,0.7*scale,params)*scale/original_debt-1)
        time_covariance.append({"time_scale":scale,"relative_errors":errors})
    checks["full_hx_time_unit_covariance"]=_check(
        [error for row in time_covariance for error in row["relative_errors"].values()],3e-10)

    limits = []
    limit_parameter_sets = (replace(baseline,ell=0),replace(baseline,delta=0.03,ell=0),
                            replace(baseline,maturity=0.01),replace(baseline,maturity=30),
                            replace(baseline,delta=1e-8),replace(baseline,sigma=0.03),
                            replace(baseline,recovery=1))
    for params in limit_parameter_sets:
        boundary = hx.hx_boundary(params)
        running0 = (params.delta*boundary-(1-params.tax)*params.coupon
                    +params.recovery*boundary/params.maturity-params.p)
        expected = -running0/params.sigma**2
        tiny_equity = hx.hx_equity(1e-7,params)
        relative_error = abs(tiny_equity/(1e-14*expected)-1)
        limits.append({"parameters":asdict(params),"boundary":boundary,
                       "equity_at_margin_1e_minus_7":tiny_equity,
                       "small_margin_quadratic_relative_error":relative_error,
                       "equity_at_margin_0_1":hx.hx_equity(0.1,params)})
    checks["small_margin_quadratic_limit"] = _check(
        [row["small_margin_quadratic_relative_error"] for row in limits],1e-4)

    origin = hx.evaluate(hx.hx_boundary(baseline),baseline,0)
    checks["time_zero_boundary_atom"] = {
        "passed":origin["E"] == 0 and origin["F"] == 1 and origin["G"] == 1
        and origin["f"] == 0 and origin["first_passage_atom"] == 1,
        "result":origin,
        "meaning":"F/G include the zero-time atom; f is only the regular density."}

    source_root = Path(__file__).resolve().parent
    paths = ("reference.py","validate.py","tests/test_reference.py","MATH.md")
    source_hashes = {name:hashlib.sha256((source_root/name).read_bytes()).hexdigest() for name in paths}
    passed = all(check["passed"] for check in checks.values())
    feasibility_counts = {
        "parameter_sets":len(parameter_screens),
        "sufficient_monotone_subdomain":sum(screen["sufficient_monotone_subdomain"] for screen in parameter_screens.values()),
        "necessary_screen_only":sum(screen["status"] == "necessary_screen_only" for screen in parameter_screens.values()),
        "inadmissible_local":sum(not screen["local_admissible"] for screen in parameter_screens.values()),
        "sampled_negative_equity_points":sum(not row["sample_equity_nonnegative"] for row in scan),
        "all_scanned_parameters_economically_admissible":all(screen["local_admissible"] for screen in parameter_screens.values()),
    }
    return {
        "schema":"hcsn-hx-kernel-reference-v1", "status":"passed" if passed else "failed",
        "scope":"FP64 formal stationary ODE kernels and independent integration, with separate economic feasibility screens; no tensor/training/performance claims",
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "source_files_sha256":source_hashes,
        "runtime":{"python":platform.python_version(),"numpy":np.__version__,
                   "scipy":scipy.__version__,"platform":platform.platform(),"dtype":"float64"},
        "reproduce_command":"PYTHONPATH=qualification python -m hcsn.validate --output qualification/hcsn/evidence/kernel_reference.json",
        "source_paper":{"title":"Rollover Risk and Credit Risk","authors":["Zhiguo He","Wei Xiong"],
                        "year":2012,"doi":"10.1111/j.1540-6261.2012.01721.x",
                        "url":"https://zhiguohe.net/wp-content/uploads/2023/12/The-Journal-of-Finance-2012-HE-Rollover-Risk-and-Credit-Risk.pdf",
                        "equations":["8","9","12","A5","A7"]},
        "baseline_parameters":asdict(baseline),"checks":checks,
        "feasibility_summary":feasibility_counts,
        "equity_scan":scan,"boundary_sensitivities":sensitivities,"limit_cases":limits,
        "time_unit_covariance":time_covariance,
        "elapsed_seconds":time.perf_counter()-started,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path(__file__).resolve().parent/"evidence/kernel_reference.json")
    args = parser.parse_args()
    report = validate()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"checks":report["checks"],
                      "output":str(args.output),"elapsed_seconds":report["elapsed_seconds"]},indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
