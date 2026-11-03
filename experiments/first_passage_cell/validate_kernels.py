"""Independent integral, time-composition, gradient and belief checks.

Run: python -m experiments.first_passage_cell.validate_kernels --output FILE
References use direct scalar formulas and scipy adaptive quadrature, separately
from the stabilized production expressions. These are deterministic numerical
checks, not task efficacy evidence or a proof over every floating-point input.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr

from .filtering import EventObservation, killed_transition_matrix, survival_filter
from .kernels import (first_passage, first_passage_gradients, killed_cdf,
                      killed_density, killed_gradients, killed_log_density)


def _ref_density(t, x, mu, sigma):
    if t <= 0:
        return 0.0
    return x / (sigma * math.sqrt(2 * math.pi * t ** 3)) * math.exp(
        -(x + mu * t) ** 2 / (2 * sigma * sigma * t))


def _ref_killed(x, y, mu, sigma, t):
    var = sigma * sigma * t
    # Independently written image solution, not the production factored density.
    return math.exp(mu * (y-x) / sigma ** 2 - mu * mu * t / (2 * sigma ** 2)) * (
        math.exp(-(y-x)**2/(2*var)) - math.exp(-(y+x)**2/(2*var))) / math.sqrt(2*math.pi*var)


def _quad_density(x, mu, sigma, t, q=0.0, moment=0):
    return quad(lambda s: s ** moment * math.exp(-q*s) * _ref_density(s, x, mu, sigma),
                0.0, t, epsabs=2e-13, epsrel=2e-12, limit=250)[0]


def validate():
    started = time.perf_counter()
    records = []
    counters = {}

    def check(name, error, tolerance, detail=None):
        error = float(error)
        if not math.isfinite(error) or error > tolerance:
            raise AssertionError(f"{name}: {error} exceeds {tolerance}; {detail}")
        records.append({"check": name, "error": error, "tolerance": tolerance, "detail": detail})
        counters[name] = counters.get(name, 0) + 1

    cases = [(.08, -.6, .35, .2), (.7, -.4, .6, 2.0), (1., 0., 1., 1.),
             (.2, .4, .8, 1.5), (1.2, 1.0, .5, 3.), (2., -.8, 1.2, .4),
             (.01, -1.0, .4, 3.), (3., 1.2, .7, .3), (.15, 0., 2., .03)]
    for case in cases:
        x, mu, sigma, t = case
        p = first_passage(*case, .3)
        f_ref = _quad_density(*case)
        h_ref = _quad_density(*case, q=.3)
        mass = quad(lambda y: _ref_killed(x, y, mu, sigma, t), 0.0,
                    x + abs(mu)*t + 14*sigma*np.sqrt(t), epsabs=1e-12,
                    epsrel=3e-12, limit=200)[0]
        check("F_integral", abs(p["F"] - f_ref), 3e-11, case)
        check("H_integral", abs(p["H"] - h_ref), 3e-11, case)
        check("killed_mass", abs(p["S"] - mass), 3e-11, case)
        check("mass_conservation", abs(p["F"]+p["S"]-1), 3e-15, case)
        check("discount_bounds", max(0.0, p["H"]-p["F"], np.exp(-.3*t)*p["F"]-p["H"]), 3e-15, case)
        check("density_reference", abs(p["f"]-_ref_density(t,x,mu,sigma)), 3e-13, case)
        for y in (.03, .7, 2.5):
            integral = quad(lambda z: _ref_killed(x,z,mu,sigma,t), 0., y,
                            epsabs=1e-13, epsrel=2e-12)[0]
            check("killed_cdf_integral", abs(killed_cdf(x,y,mu,sigma,t)-integral), 3e-11, case+(y,))

    for x, mu, sigma, s, t, y in [(1.,-.2,.7,.4,.8,.9), (.2,.5,.4,.1,.7,.3),
                                  (.8,0.,1.,.3,.2,1.5), (2.,-.8,.8,.6,.5,.2)]:
        composed = quad(lambda z: _ref_killed(x,z,mu,sigma,s)*_ref_killed(z,y,mu,sigma,t),
                        0., 12., epsabs=2e-12, epsrel=1e-11, limit=200)[0]
        direct = float(killed_density(x,y,mu,sigma,s+t))
        check("continuous_semigroup", abs(composed-direct), 3e-11, [x,mu,sigma,s,t,y])
        later_hit = quad(lambda z: _ref_killed(x,z,mu,sigma,s)*
                         (ndtr((-z-mu*t)/(sigma*np.sqrt(t))) +
                          math.exp(-2*mu*z/sigma**2)*ndtr((-z+mu*t)/(sigma*np.sqrt(t)))),
                         0., 12., epsabs=2e-12, epsrel=1e-11, limit=200)[0]
        p1, p2 = first_passage(x,mu,sigma,s), first_passage(x,mu,sigma,s+t)
        check("first_hit_time_composition", abs(p2["F"]-p1["F"]-later_hit), 3e-11)

    keys = ("x", "mu", "sigma", "horizon", "discount")
    gradient_cases = [(1.,0.,1.,1.,.2), (.4,-.7,.6,1.3,.4), (1.1,.5,.7,.8,.3),
                      (.02,-.2,.8,.1,.05), (3.,.2,.6,.4,.7), (.3,-2.,.5,4.,.2)]
    for case in gradient_cases:
        analytic = first_passage_gradients(*case)
        for j, key in enumerate(keys):
            step = 1e-5*max(abs(case[j]), .1)
            terms = []
            for multiplier in (-2,-1,1,2):
                point = list(case)
                point[j] += multiplier*step
                terms.append(first_passage(*point))
            for output in ("log_F", "log_S", "log_f", "log_H"):
                numerical = (terms[0][output]-8*terms[1][output]+8*terms[2][output]-terms[3][output])/(12*step)
                exact = float(analytic[output][key])
                err = abs(float(numerical)-exact)/(1+abs(exact))
                check("analytic_log_gradient", err, 3e-6, [list(case),output,key])
    for x, mu, sigma, t in [(1.,0.,1.,1.), (.1,0.,.7,.5), (20.,0.,1.,1.), (.2,-.5,.6,2.)]:
        derivative = float(first_passage_gradients(x,mu,sigma,t,0.)["H"]["discount"])
        reference = -_quad_density(x,mu,sigma,t,moment=1)
        check("zero_discount_gradient", abs(derivative-reference), 3e-11, [x,mu,sigma,t])

    for distance in (20.0, 50.0):
        # Scale out the tiny hit probability; an absolute check on H itself
        # would not detect an incorrect conditional-time derivative here.
        a = distance * distance / 2.0
        def scaled_weight(s):
            return 0.0 if s <= 0 else s ** -1.5 * np.exp(-a * (1.0/s - 1.0))
        denominator = quad(scaled_weight, 0., 1., epsabs=1e-14, epsrel=1e-12)[0]
        numerator = quad(lambda s: s*scaled_weight(s), 0., 1., epsabs=1e-14, epsrel=1e-12)[0]
        actual = -first_passage_gradients(distance,0.,1.,1.,0.)["log_H"]["discount"]
        check("rare_hit_discount_log_gradient", abs(actual-numerator/denominator), 3e-11, distance)

    for case in [(.2,.4,-.3,.7,.5), (1.,1.2,.2,.8,1.), (.01,.02,-1.,.3,.2)]:
        analytic = killed_gradients(*case)
        for j,key in enumerate(("x","y","mu","sigma","horizon")):
            h = 1e-5*max(.01,abs(case[j]))
            lo,hi = list(case),list(case)
            lo[j]-=h; hi[j]+=h
            numeric = (killed_log_density(*hi)-killed_log_density(*lo))/(2*h)
            exact = float(analytic["log_k"][key])
            check("killed_log_gradient", abs(numeric-exact)/(1+abs(exact)), 3e-7, [list(case),key])

    extreme = [(1e-12,-10.,1.,1.,0.), (1e-10,0.,1.,1.,1e-18),
               (30.,0.,1.,1.,.1), (1.,10.,.1,1.,.1), (.1,-10.,.1,1.,.1),
               (.001,0.,.2,1e-8,1.), (.1,.3,.2,1e-8,1.),
               (1.,-1.,.01,100.,1e-9)]
    for case in extreme:
        p = first_passage(*case)
        g = first_passage_gradients(*case)
        check("extreme_log_finite", float(not all(np.isfinite(p[k]) for k in ("log_F","log_S","log_f","log_H"))), 0., case)
        check("extreme_gradient_finite", float(not all(np.isfinite(v) for item in g.values() for v in item.values())), 0., case)
        check("extreme_mass", abs(p["F"]+p["S"]-1.), 3e-14, case)
    tail = first_passage(20.,0.,1.,1.)
    check("log_survival_tail_retained", abs(tail["log_S"]/(-tail["F"])-1), 2e-14)
    for mu in (-10.,-1.,0.,1.,10.):
        x1,x2=1e-10,2e-10
        l1,l2=first_passage(x1,mu,1.,1.)["log_S"],first_passage(x2,mu,1.,1.)["log_S"]
        check("boundary_survival_linear_limit", abs((l2-l1)-np.log(2.)), 2e-8, mu)

    for distance in (1e-150, 1e-200):
        log_k = float(killed_log_density(distance,distance,0.,1.,1.))
        reference = np.log(2.) - .5*np.log(2*np.pi) + 2*np.log(distance)
        g = killed_gradients(distance,distance,0.,1.,1.)
        check("tiny_killed_log_density",abs(log_k-reference),3e-12,distance)
        check("tiny_killed_log_gradient",abs(float(g["log_k"]["x"])*distance-1),3e-14,distance)
        expected = np.sqrt(2/np.pi)*distance
        check("underflowed_density_retains_gradient",abs(float(g["k"]["x"])/expected-1),3e-12,distance)
    for drift in (-10.,-1.,0.,1.,10.):
        for side in (1.-1e-5,1.+1e-5):
            distance=.03/(1+abs(drift))*side
            integral=quad(lambda y: 2/math.sqrt(2*math.pi)*
                math.exp(drift*(y-distance)-.5*(y*y+distance*distance))*
                math.sinh(distance*y)/distance,0.,max(drift,0.)+16.,
                epsabs=1e-12,epsrel=1e-12,limit=200)[0]
            reference=math.log(integral)+math.log(distance)-drift*drift/2
            actual=float(first_passage(distance,drift,1.,1.)["log_S"])
            check("boundary_expansion_seam",abs(actual-reference),2e-10,[drift,side])
    bound_error=0.; bound_cases=0
    for distance in (1e-12,.01,1.,30.):
        for drift in (-10.,-.3,0.,.5,10.):
            for sigma in (.1,1.,3.):
                for horizon in (1e-8,.1,10.):
                    for discount in (1e-12,.1,100.,1e8):
                        p=first_passage(distance,drift,sigma,horizon,discount)
                        bound_error=max(bound_error,float(p["log_H"]-p["log_F"]),
                                        float(p["log_F"]-discount*horizon-p["log_H"]))
                        bound_cases+=1
    check("discount_log_bounds_grid",bound_error,0.,{"parameter_tuples":bound_cases})

    for x,t,expected in [(0.,0.,(1.,0.,1.)),(0.,1.,(1.,0.,1.)),(1.,0.,(0.,1.,0.))]:
        p=first_passage(x,.2,.4,t,.3)
        check("boundary_values", max(abs(float(p[k])-v) for k,v in zip(("F","S","H"),expected)), 0.)
    bad=[(-1,0,1,1,0),(1,0,0,1,0),(1,0,1,-1,0),(1,0,1,1,-1),(1,np.nan,1,1,0)]
    for case in bad:
        try:
            first_passage(*case)
        except ValueError:
            check("invalid_input_rejected",0.,0.)
        else:
            raise AssertionError("Invalid kernel input accepted")

    grid=np.linspace(.025,6.,80)
    prior=np.exp(-.5*((grid-.65)/.2)**2); prior/=prior.sum()
    mat=killed_transition_matrix(grid,-.2,.6,.5)
    check("grid_row_mass",np.max(abs(mat.sum(1)-first_passage(grid,-.2,.6,.5)["S"])),5e-12)
    unknown=survival_filter(grid,prior,-.2,.6,.5,event_observation=EventObservation.MISSING)
    survived=survival_filter(grid,prior,-.2,.6,.5,event_observation=EventObservation.OBSERVED_SURVIVAL)
    observed=survival_filter(grid,prior,-.2,.6,.5,event_observation=EventObservation.OBSERVED_SURVIVAL,sensor=(.8,.05))
    check("missing_preserves_event_atom",float(unknown["event_mass"]<=0),0.)
    check("belief_mass",abs(unknown["alive_mass"].sum()+unknown["event_mass"]-1.),5e-12)
    check("survival_conditions",max(abs(survived["alive_mass"].sum()-1.),survived["event_mass"]),5e-12)
    check("sensor_conditions",abs(observed["alive_mass"].sum()-1.),5e-12)
    check("missing_not_survival",float(np.array_equal(unknown["alive_mass"],survived["alive_mass"])),0.)
    try:
        survival_filter(grid,prior,-.2,.6,.5,event_observation="missing",sensor=(.8,.05))
    except ValueError:
        check("sensor_semantics_rejected",0.,0.)
    else:
        raise AssertionError("Undeclared cemetery sensor likelihood accepted")

    cumulative=survival_filter(grid,.7*prior,0.,.6,0.,prior_event_mass=.3,
                               event_observation="observed_event")
    check("observed_event_is_cumulative_cycle",abs(cumulative["observation_probability"]-.3),0.)
    missing_prior=survival_filter(grid,.7*prior,-.2,.6,.5,prior_event_mass=.3,
                                  event_observation="missing")
    check("missing_retains_prior_event_atom",float(missing_prior["event_mass"]<.3),0.)

    source = {name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
              for name in ("kernels.py","filtering.py","validate_kernels.py")}
    return {"schema":"hepta.first_passage.kernel_validation.v1", "pass":True,
            "checks":len(records), "counts":counters,
            "max_errors":{name:max(r["error"] for r in records if r["check"]==name) for name in counters},
            "reference":"independent scalar image/fpt formulas + scipy.integrate.quad",
            "source_sha256":source,"numpy":np.__version__,
            "wall_seconds":time.perf_counter()-started,"records":records,
            "scope":"deterministic numeric and contract validation; no network efficacy claim"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=validate()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print(json.dumps({"pass":result["pass"],"checks":result["checks"],
                      "wall_seconds":result["wall_seconds"],"output":str(args.output)}))


if __name__=="__main__":
    main()
