"""Write reproducible raw evidence; no training, optimization or GPU execution."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import time
import traceback

import numpy as np
import scipy

from qualification.hcsn.reference import HXParams, hx_boundary
from qualification.hcsn_regenerative.audit import (
    five_point_derivative, hit_integral, pde_value, stationary_hx_pde, survivor_integral,
)
from qualification.hcsn_regenerative.process import (
    KilledDiffusion, ResetRule, finite_horizon_value, stationary_hx_value,
)


BASE = dict(x=.35, horizon=1.4, mu=-.1, sigma=.3, discount=.15, margin=.25,
            refractory=.11, active_reward=.4, terminal_reward=.2, hit_reward=1.0)
LOW_NOISE = dict(x=.12, horizon=.8, mu=-.2, sigma=.015, discount=.1,
                 margin=.08, refractory=.07, hit_reward=1.0)


def candidate(case):
    process = KilledDiffusion(case["mu"], case["sigma"], case["discount"])
    reset = ResetRule(case["margin"], case.get("refractory", 0), case.get("hit_reward", 1))
    return finite_horizon_value(process, reset, case["x"], case["horizon"],
                                active_reward=case.get("active_reward", 0),
                                terminal_reward=case.get("terminal_reward", 0))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def run():
    started = time.monotonic()
    checks, records = [], {}

    def check(name, observed, expected, tolerance):
        error = abs(observed - expected)
        checks.append(dict(name=name, observed=observed, oracle=expected, absolute_error=error,
                           tolerance=tolerance, passed=math.isfinite(error) and error <= tolerance))

    cases = [(0, 0, -.1, .2, .1), (0, 1, -.1, .2, .1), (.4, 0, -.1, .2, .1),
             (.4, 1, -.2, .3, .1), (1e-5, 1e-5, -.2, .2, .1),
             (.12, .8, -.2, .015, .1), (4, .5, .2, .2, .1), (.4, 4, .2, .3, .1),
             (.4, 1e-5, -.1, .2, .1)]
    rows = []
    for args in cases:
        x, horizon, mu, sigma, q = args
        oracle = hit_integral(*args)
        observed = KilledDiffusion(mu, sigma, q).discounted_hit(x, horizon)
        rows.append(dict(parameters=dict(zip(["x", "horizon", "mu", "sigma", "discount"], args)),
                         integral=asdict(oracle), candidate=observed))
        if oracle.value > 0:
            check(f"hit_log:{args}", math.log(observed) if observed > 0 else -math.inf,
                  oracle.log_absolute_value, 1e-8)
        else:
            check(f"hit_zero:{args}", observed, oracle.value, 0)
    records["hit_density_integrals"] = rows
    bad_inputs = [lambda: hit_integral(0, 0, math.nan, .2),
                  lambda: survivor_integral(0, 0, math.inf, .2),
                  lambda: survivor_integral(.1, 1, -.1, .2, upper=math.nan),
                  lambda: pde_value(0, 0, math.nan, .2, .1, .25),
                  lambda: pde_value(.1, 1, -.1, .2, .1, .25, active_reward=math.nan)]
    for index, call in enumerate(bad_inputs):
        rejected = False
        try:
            call()
        except ValueError:
            rejected = True
        check(f"invalid_input_rejected:{index}", float(rejected), 1, 0)
    rows = []
    for point in [[.4, 1, -.2, .3, .1], [.12, .8, -.2, .015, .1]]:
        for field, index in [("x", 0), ("mu", 2), ("sigma", 3), ("discount", 4)]:
            def function(value):
                p = point.copy()
                p[index] = value
                return KilledDiffusion(p[2], p[3], p[4]).discounted_hit(p[0], p[1])
            step = min(1e-5, abs(point[index]) / 20) if point[index] else 1e-5
            full = five_point_derivative(function, point[index], step)
            half = five_point_derivative(function, point[index], step / 2)
            oracle = hit_integral(*point, derivative=field)
            rows.append(dict(point=point, parameter=field, candidate_step=full,
                             candidate_half_step=half, step=step, integral=asdict(oracle)))
            check(f"hit_gradient:{point}:{field}", half, oracle.value, 2e-7)
            check(f"hit_gradient_step:{point}:{field}", half, full, 2e-7)
    records["hit_derivatives"] = rows

    rows = []
    for x, horizon, mu, sigma in [(.25, .7, -.2, .3), (.8, .9, .4, .25)]:
        edges = [0, .2, .6, 1]
        observed = KilledDiffusion(mu, sigma).transition(x, horizon, edges)
        bins = [survivor_integral(x, horizon, mu, sigma, lo, hi)
                for lo, hi in zip(edges[:-1], edges[1:])]
        tail = survivor_integral(x, horizon, mu, sigma, edges[-1])
        hit = hit_integral(x, horizon, mu, sigma).value
        rows.append(dict(x=x, horizon=horizon, mu=mu, sigma=sigma, edges=edges,
                         candidate=asdict(observed), oracle_bins=bins, oracle_tail=tail, oracle_hit=hit))
        for index, (value, reference) in enumerate(zip(observed.survivor_bins, bins)):
            check(f"survivor_bin:{x}:{index}", value, reference, 1e-11)
        check(f"survivor_tail:{x}", observed.upper_tail, tail, 1e-11)
        check(f"survivor_mass:{x}", sum(bins) + tail + hit, 1, 1e-11)
    records["transition_integrals"] = rows

    def sweep(name, case, configurations):
        expected = candidate(case)
        values = []
        for dx, dt, domain in configurations:
            result = pde_value(**case, space_step=dx, time_step=dt, domain=domain)
            values.append(dict(pde=asdict(result), single_error=result.single_cycle - expected.single_cycle,
                               regenerative_error=result.regenerative - expected.regenerative))
        records[name] = dict(case=case, candidate=asdict(expected), values=values)
        return expected, values

    expected, time_rows = sweep("time_refinement", BASE, [(.00125, dt, 3) for dt in [.01, .005, .0025, .00125]])
    _, space_rows = sweep("space_refinement", BASE, [(dx, .0005, 3) for dx in [.02, .01, .005, .0025]])
    _, domain_rows = sweep("domain_expansion", BASE, [(.005, .001, size) for size in [.8, 1.2, 2, 3]])
    for name, rows in [("time", time_rows), ("space", space_rows)]:
        check(f"{name}_fine_E", rows[-1]["pde"]["single_cycle"], expected.single_cycle, 3e-4)
        check(f"{name}_fine_U", rows[-1]["pde"]["regenerative"], expected.regenerative, 3e-4)
        for component in ["single_error", "regenerative_error"]:
            check(f"{name}_error_reduction:{component}",
                  float(abs(rows[-1][component]) < abs(rows[0][component])), 1, 0)
    check("expanded_domain_stability", domain_rows[-1]["pde"]["regenerative"],
          domain_rows[-2]["pde"]["regenerative"], 1e-7)

    short = dict(x=.1, horizon=.15, mu=-.3, sigma=.2, discount=.1, margin=.12,
                 refractory=.03, active_reward=.2, terminal_reward=.1)
    exact, rows = sweep("short_horizon", short, [(.005, .002, 1.5), (.0025, .001, 1.5), (.00125, .00025, 1.5)])
    check("short_E", rows[-1]["pde"]["single_cycle"], exact.single_cycle, 3e-4)
    check("short_U", rows[-1]["pde"]["regenerative"], exact.regenerative, 3e-4)
    exact, low_time = sweep("low_noise_time", LOW_NOISE, [(.00025, dt, .8) for dt in [.002, .001, .0005, .00025]])
    _, low_space = sweep("low_noise_space", LOW_NOISE, [(dx, .00025, .8) for dx in [.002, .001, .0005, .00025]])
    for name, rows in [("time", low_time), ("space", low_space)]:
        check(f"low_noise_{name}_E", rows[-1]["pde"]["single_cycle"], exact.single_cycle, 3e-4)
        check(f"low_noise_{name}_U", rows[-1]["pde"]["regenerative"], exact.regenerative, 3e-4)
    records["failed_coarse_low_noise_control"] = dict(
        case=LOW_NOISE, pde=asdict(pde_value(**LOW_NOISE, domain=.8, space_step=.01, time_step=.004)),
        candidate=asdict(exact), qualification="unresolved_coarse_grid_expected_failure",
        required_tolerance=.0003)

    rows = []
    for field, step in [("x", .0025), ("mu", .002), ("sigma", .002),
                        ("discount", .002), ("margin", .005), ("refractory", .005), ("horizon", .005)]:
        centre = BASE[field]
        function = lambda v: candidate(dict(BASE, **{field: v})).regenerative
        observed = five_point_derivative(function, centre, step / 5)
        half = five_point_derivative(function, centre, step / 10)
        grid_derivatives = []
        for dx, dt in [(.005, .001), (.0025, .0005)]:
            values = [pde_value(**dict(BASE, **{field: centre + sign * step}),
                                space_step=dx, time_step=dt).regenerative for sign in [-1, 1]]
            grid_derivatives.append((values[1] - values[0]) / (2 * step))
        rows.append(dict(parameter=field, independent_difference_step=step,
                         candidate_step=observed, candidate_half_step=half,
                         pde_derivatives=grid_derivatives))
        check(f"renewal_gradient:{field}", half, grid_derivatives[-1], .0012)
        check(f"renewal_gradient_step:{field}", half, observed, 1e-5)
        check(f"renewal_gradient_grid:{field}", grid_derivatives[-1], grid_derivatives[0], .002)
    records["renewal_parameter_sensitivity"] = rows
    instant_rows = []
    for start in [0, .35]:
        case = dict(BASE, x=start, refractory=0)
        exact = candidate(case)
        result = pde_value(**case, space_step=.0025, time_step=.0005)
        instant_rows.append(dict(case=case, candidate=asdict(exact), pde=asdict(result)))
        check(f"instant_reset_E:{start}", result.single_cycle, exact.single_cycle, .00015)
        check(f"instant_reset_U:{start}", result.regenerative, exact.regenerative, .00015)
    records["positive_deadline_instant_reset"] = instant_rows

    par, reset = HXParams(), ResetRule(.25, .11, .3)
    boundary = hx_boundary(par)
    stationary = stationary_hx_value(par, reset, .5)
    rows = [asdict(stationary_hx_pde(par, boundary, .25, .11, .3, .5, space_step=dx))
            for dx in [.04, .02, .01, .005]]
    domains = [asdict(stationary_hx_pde(par, boundary, .25, .11, .3, .5,
                                       space_step=.01, domain=size)) for size in [4, 6, 8]]
    observed_slope = five_point_derivative(lambda x: stationary_hx_value(par, reset, x).regenerative, .5, 1e-4)
    records["stationary_hx"] = dict(parameters=asdict(par), fixed_boundary=boundary, reset=asdict(reset),
                                    x=.5, candidate=asdict(stationary), space_refinement=rows,
                                    domain_expansion=domains, candidate_slope=observed_slope)
    check("stationary_E", rows[-1]["single_cycle"], stationary.single_cycle, .0015)
    check("stationary_U", rows[-1]["regenerative"], stationary.regenerative, .003)
    check("stationary_U_gradient", observed_slope, rows[-1]["regenerative_slope"], .007)
    check("stationary_domain", domains[-1]["regenerative"], domains[-2]["regenerative"], 2e-5)

    instant = pde_value(0, 0, -.1, .3, .15, .25, 0, terminal_reward=.7)
    before = pde_value(0, .199, -.1, .3, .15, .25, .2, terminal_reward=.7)
    release = pde_value(0, .2, -.1, .3, .15, .25, .2, terminal_reward=.7)
    check("atom_initial_E", instant.single_cycle, 1, 0)
    check("atom_initial_U", instant.regenerative, 1.7, 0)
    check("atom_before_release", before.regenerative, 1, 0)
    check("atom_exact_release", release.regenerative, 1 + math.exp(-.15*.2)*.7, 1e-12)
    atom_case = dict(BASE, x=0, horizon=.45, refractory=.2, terminal_reward=.7)
    atom = candidate(atom_case).regenerative
    remaining = candidate(dict(atom_case, x=.25, horizon=.25)).regenerative
    wrong_full = 1 + math.exp(-.15*.2) * candidate(dict(atom_case, x=.25)).regenerative
    check("remaining_time_identity", atom, 1 + math.exp(-.15*.2) * remaining, 1e-12)
    counterfeit = [dict(kind="reuse_full_deadline_after_reset", wrong=wrong_full, correct=atom,
                        rejection_margin=abs(wrong_full-atom), rejected=abs(wrong_full-atom)>.05),
                   dict(kind="reuse_E_gradient_for_U", wrong=rows[-1]["single_slope"], correct=observed_slope,
                        rejection_margin=abs(rows[-1]["single_slope"]-observed_slope),
                        rejected=abs(rows[-1]["single_slope"]-observed_slope)>50)]
    records["counterfeit_controls"] = counterfeit
    for row in counterfeit:
        check(f"counterfeit_rejected:{row['kind']}", float(row["rejected"]), 1, 0)
    root = Path(__file__).resolve().parent
    paths = [root / "audit.py", root / "process.py", root / "run_audit.py", root / "tests/test_audit.py"]
    preflight = sorted((root / "evidence").glob("audit_preflight*.json"))
    return _clean(dict(
        schema="hcsn-independent-regenerative-audit/v1", utc=datetime.now(timezone.utc).isoformat(),
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        candidate_base_commit="a20ea6a862e501d8a4993195c7da1ac52ca9a7be",
        original_campaign_source="f355cfe2",
        provenance="New isolated candidate on a20; original 170-run results are not qualifications for this model.",
        source_sha256={str(p.relative_to(root)): _sha(p) for p in paths},
        preserved_preflight_sha256={p.name: _sha(p) for p in preflight},
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                     platform=platform.platform(), elapsed_seconds=time.monotonic()-started),
        scope="Scalar FP64 constant generator, fixed reset, physical refractory and stated rewards",
        derivative_scope="Candidate finite differences vs independent density scores/PDE; no autodiff certificate",
        successor_scope="regenerative_transition is qualified separately in tests/test_process.py; this audit does not certify its full state PDE.",
        user_decisive_requirement_complete=False,
        limitations=["No production autodiff or tensor derivative API was exercised.",
                     "Dynamic boundaries, value feedback and nonconstant generators are outside this slice.",
                     "PDE limits are empirical refinement evidence, not global numerical error bounds.",
                     "Stationary HX uses a supplied fixed boundary and does not solve regenerative optimal stopping.",
                     "Underflowing probabilities retain oracle log magnitude; zero equality is not relative accuracy.",
                     "No learning, encoder streaming, energy or original 170-run performance claim."],
        checks=checks, records=records,
        checks_passed=sum(c["passed"] for c in checks), checks_total=len(checks),
        status="bounded_audit_pass_autodiff_unqualified" if all(c["passed"] for c in checks) else "audit_failed"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve the existing receipt and choose a new output path")
    try:
        result = run()
    except Exception as error:
        result = dict(status="audit_exception", utc=datetime.now(timezone.utc).isoformat(),
                      exception_type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ["status", "checks_passed", "checks_total", "runtime"]
                      if key in result}))
    return 0 if result["status"] == "bounded_audit_pass_autodiff_unqualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
