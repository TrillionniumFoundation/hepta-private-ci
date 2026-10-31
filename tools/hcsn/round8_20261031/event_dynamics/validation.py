"""Independent event-law qualification and reproducible raw numerical evidence."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import quad

from .event_kernel import (discounted_hit, first_hit, first_hit_gradient,
                           killed_density, two_segment_first_hit)
from .generator import (ResolutionError, absorbing_generator, erlang_recovery,
                        first_exit, hazard_from_reference_release, require_local_resolution)
from .renewal import expected_count, sample_counts


def reference_log_hit(distance, drift, sigma, time, *, discount=0.0, survival=False):
    """Integrate the inverse-Gaussian density directly, scaled at its mode.

    This reference does not use a CDF, reflection, erfcx, or the tested kernel.
    Survival integrates [time,infinity) and requires positive drift.
    """
    if survival and drift <= 0:
        raise ValueError("Tail reference requires eventual hit probability one")
    beta = math.hypot(drift, math.sqrt(2 * discount) * sigma)
    mode = 2 * distance**2 / (math.hypot(3*sigma**2, 2*beta*distance) + 3*sigma**2)
    lower, upper = (time, math.inf) if survival else (0.0, time)
    peak_time = max(lower, min(mode, upper))
    def log_density(t):
        return (math.log(distance/sigma) - .5*math.log(2*math.pi) - 1.5*math.log(t)
                -(distance-drift*t)**2/(2*sigma**2*t) - discount*t)
    peak = log_density(peak_time)
    def integrand(t):
        return 0.0 if t == 0 else math.exp(log_density(t)-peak)
    intervals = [(lower, peak_time), (peak_time, upper)] if lower < peak_time < upper else [(lower, upper)]
    value, error = 0.0, 0.0
    for left, right in intervals:
        area, estimate = quad(integrand, left, right, epsabs=1e-13, epsrel=3e-12, limit=500)
        value += area
        error += estimate
    return dict(log_value=peak+math.log(value), relative_quadrature_error_estimate=error/value)


def _moving_mc(distance, first, second, jump, paths=200000, seed=83103):
    """Exact endpoint plus Brownian-bridge crossing sampling for two segments."""
    rng = np.random.default_rng(seed)
    gap = np.full(paths, distance)
    hit = np.zeros(paths, dtype=bool)
    for index, (duration, drift, sigma) in enumerate((first, second)):
        if index:
            gap += jump
            hit |= gap <= 0
        live = np.flatnonzero(~hit)
        before = gap[live]
        after = before-drift*duration-sigma*math.sqrt(duration)*rng.normal(size=len(live))
        bridge = np.exp(-2*before*np.maximum(after, 0)/(sigma**2*duration))
        hit[live] = (after <= 0) | (rng.random(len(live)) < bridge)
        gap[live] = after
    estimate = float(hit.mean())
    return dict(probability=estimate, standard_error=math.sqrt(estimate*(1-estimate)/paths),
                hits=int(hit.sum()), paths=paths, seed=seed)


def audit():
    gates, kernels, gradients = [], [], []
    def gate(name, passed, criterion):
        gates.append(dict(name=name, passed=bool(passed), criterion=criterion))
    fixtures = ((1.,1.,.05,.8), (1.,-1.,.05,.8), (40.,0.,1.,1.),
                (1.,.4,.6,1.2), (.3,-.2,.7,.8))
    for values in fixtures:
        actual = first_hit(*values)
        reference = reference_log_hit(*values)
        difference = abs(actual["log_probability"]-reference["log_value"])
        kernels.append(dict(parameters=values, actual=actual, reference=reference, absolute_log_error=difference))
    gate("first_hit_tails_against_independent_density_integral",
         max(row["absolute_log_error"] for row in kernels) < 2e-10, "absolute log-CDF error < 2e-10, including underflow cases")
    survival = first_hit(1.,1.,.1,10.)
    survival_ref = reference_log_hit(1.,1.,.1,10.,survival=True)
    gate("survival_tail_preserved", abs(survival["log_survival"]-survival_ref["log_value"]) < 2e-10,
         "log survival agrees with independent tail integral within 2e-10; 1-F is not used")
    discounted = discounted_hit(1.,.4,.6,1.2,.7)
    discounted_ref = reference_log_hit(1.,.4,.6,1.2,discount=.7)
    gate("discounted_hit_is_value", abs(discounted["log_value"]-discounted_ref["log_value"]) < 2e-10,
         "discounted density integral agrees; G is separately named from probability F")
    for values in (fixtures[0], fixtures[3], fixtures[4]):
        analytic = first_hit_gradient(*values)
        for index, name in enumerate(("distance", "drift", "sigma", "time")):
            step = 2e-6 * max(.1, abs(values[index]))
            plus, minus = list(values), list(values)
            plus[index] += step
            minus[index] -= step
            numeric = (first_hit(*plus)["probability"]-first_hit(*minus)["probability"])/(2*step)
            error = abs(numeric-analytic[name])/max(1e-10,abs(analytic[name]))
            gradients.append(dict(parameters=values, parameter=name, analytic=analytic[name],
                                  central_difference=numeric, relative_error=error))
    gate("cdf_parameter_gradients", max(r["relative_error"] for r in gradients) < 2e-7,
         "central difference relative error < 2e-7 at registered regular/rare-event fixtures")
    killed_mass, killed_error = quad(lambda y:killed_density(1.,y,.4,.6,1.2), 0., math.inf,
                                      epsabs=1e-12, epsrel=1e-12)
    gate("killed_mass_matches_survival", abs(killed_mass-first_hit(1.,.4,.6,1.2)["survival"]) < 1e-11,
         "positive killed density integrates to survival within 1e-11")
    split = two_segment_first_hit(1.,(.3,1.,.05),(.5,1.,.05))
    exact = first_hit(1.,1.,.05,.8)["probability"]
    gate("piecewise_killed_composition", abs(split["probability"]-exact)/exact < 1e-8,
         "split first-hit composition relative error < 1e-8 in the low-noise fixture")
    moving = two_segment_first_hit(1.,(.6,.5,.6),(.8,.2,.5),boundary_jump=-.15)
    moving_mc = _moving_mc(1.,(.6,.5,.6),(.8,.2,.5),-.15)
    gate("moving_boundary_jump", abs(moving["probability"]-moving_mc["probability"]) < 5*moving_mc["standard_error"],
         "two affine segments plus a downward jump agree with exact bridge Monte Carlo within 5 standard errors")
    finite = []
    for grid in (15,31,63,127,255):
        for scheme in ("upwind","fitted"):
            flow = absorbing_generator(1.,.05,n_grid=grid,scheme=scheme)
            row = first_exit(flow,.8)
            try:
                require_local_resolution(flow["diagnostics"])
                admitted = True
            except ResolutionError:
                admitted = False
            finite.append(dict(grid=grid,scheme=scheme,**row,
                extra_variance_ratio=float(np.max(flow["diagnostics"]["extra_variance_ratio"])),
                absolute_probability_error=abs(row["plus"]-exact), local_moment_admitted=admitted))
    main = next(r for r in finite if r["grid"]==63 and r["scheme"]=="upwind")
    gate("historical_counterexample_reproduced", abs(main["plus"]-.13307838097843133)<1e-11,
         "R7 Brownian low-noise grid63 upper probability reproduced; independent exact upper value is 4.321826e-6")
    gate("coarse_generators_rejected_for_continuum_claim", not any(r["local_moment_admitted"] for r in finite),
         "all registered coarse low-noise upwind/SG grids fail the fixed 5% local variance gate")
    small = erlang_recovery(.5,2,.1)
    large = erlang_recovery(.5,2,1.)
    semigroup_error = float(np.max(np.abs(np.linalg.matrix_power(small,10)-large)))
    gate("physical_recovery_semigroup", semigroup_error < 2e-13,
         "10 physical 0.1-second recovery steps equal 1 second within 2e-13")
    args = [.8,.7,1.,.4,3.,.5]
    renewal = expected_count(*args)
    more = expected_count(*args,included_events=renewal["included_events"]+4)
    renewal_gradients = []
    for index,name in ((0,"initial_gap"),(1,"reset_gap"),(2,"drift"),(3,"sigma"),(5,"recovery_mean")):
        step = 2e-5*args[index]
        plus,minus = args.copy(),args.copy()
        plus[index] += step
        minus[index] -= step
        numeric = (expected_count(*plus,included_events=renewal["included_events"])["expected_count"]
                   -expected_count(*minus,included_events=renewal["included_events"])["expected_count"])/(2*step)
        renewal_gradients.append(dict(parameter=name, analytic=renewal["gradient"][name], numeric=numeric,
                                     absolute_error=abs(numeric-renewal["gradient"][name])))
    gate("renewal_count_gradients", max(r["absolute_error"] for r in renewal_gradients) < 2e-6,
         "analytic-integrand count derivatives agree with central differences within 2e-6")
    gradient_tail_change = max(abs(more["gradient"][k]-renewal["gradient"][k]) for k in renewal["gradient"])
    gate("renewal_truncation_fixture", gradient_tail_change < 1e-9 and renewal["count_tail_bound"] < 1e-10,
         "count tail has analytic bound <1e-10; adding 4 events changes fixture gradients <1e-9 (not a uniform derivative bound)")
    samples = sample_counts(*args)
    sample_mean = float(samples.mean())
    standard_error = float(samples.std(ddof=1)/math.sqrt(len(samples)))
    gate("repeated_events_independent_sampling", abs(sample_mean-renewal["expected_count"]) < 5*standard_error,
         "positive renewal integral agrees with independent Wald/Gamma event-time Monte Carlo within 5 standard errors")
    return dict(schema="hcsn_round8_event_audit_v1", gates=gates, all_new_model_gates_pass=all(g["passed"] for g in gates),
        source_baselines=dict(r7="1bbf9712140ec388f7fb7967fa7b22244386441d",native="e67a5e13ba82768a25858153452c15e76670b641"),
        environment=dict(numpy=np.__version__,scipy=scipy.__version__), kernels=kernels, cdf_gradients=gradients,
        survival=dict(actual=survival,reference=survival_ref),discounted=dict(actual=discounted,reference=discounted_ref),
        killed=dict(mass=killed_mass,quadrature_error_estimate=killed_error),piecewise=split,moving=dict(actual=moving,monte_carlo=moving_mc),
        low_noise_finite_generators=finite,physical_recovery=dict(semigroup_error=semigroup_error,
            one_second_release=float(large[0,-1]),reference_q=.65,matched_single_phase_hazard=hazard_from_reference_release(.65,1.)),
        renewal=dict(actual=renewal,gradients=renewal_gradients,gradient_tail_change=gradient_tail_change,
            monte_carlo=dict(mean=sample_mean,standard_error=standard_error,paths=len(samples),seed=20261031,histogram=np.bincount(samples).tolist())),
        limitations=["Exact Brownian fixed/affine boundary law, not an OU or interacting-network certificate.",
            "No old checkpoint was reinterpreted as the new continuous model.",
            "Finite SG/upwind examples remain rejected for continuous low-noise accuracy.",
            "Positive quadrature error estimates exclude floating-point roundoff; count-tail bounds do not certify derivative tails."])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=audit()
    source=Path(__file__).parent
    result["source_sha256"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.glob("*.py"))}
    # Infinity is meaningful for log probabilities; keep evidence strict JSON.
    def serializable(value):
        if isinstance(value,float) and not math.isfinite(value):
            if math.isnan(value):
                raise ArithmeticError("NaN cannot be published as numerical evidence")
            return "-Infinity" if value<0 else "Infinity"
        if isinstance(value,dict):
            return {k:serializable(v) for k,v in value.items()}
        if isinstance(value,(tuple,list)):
            return [serializable(v) for v in value]
        return value
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(serializable(result),indent=2,sort_keys=True,allow_nan=False)+"\n")
    print(json.dumps(dict(gates=result["gates"],output=str(args.output)),indent=2))
    if not result["all_new_model_gates_pass"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
