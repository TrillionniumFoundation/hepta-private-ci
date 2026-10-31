"""Prespecified renewal audit; writes every case and retains failures/raw counts."""

import argparse
import hashlib
import itertools
import json
import math
import platform
import re
import sys
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.stats import invgauss, levy

import renewal as r


def protocol():
    return {
        "schema": "hcsn-renewal-protocol-v1",
        "contract": "constant drift/noise; immediate count; fixed refractory; fixed reset",
        "main": {"mu": [-1, -.25, 0, .25, 1], "sigma": [.2, 1, 2],
                 "x": [0, .05, .4, 1.5, 3], "horizon": [.1, 1, 3],
                 "reset": [.4, .8, 1.4], "refractory": [.15, .5], "cases": 1350},
        "zero_refractory": {"refractory": [0], "cases": 675,
                            "tail_atol": r.TAIL_ATOL, "tail_rtol": r.TAIL_RTOL,
                            "max_terms": r.MAX_TERMS},
        "integration": {"mu": [-1, 0, 1], "sigma": [.7, 1.5], "x": [.2, .8],
                        "refractory": [0, .15], "horizon": 1.5, "reset": .8,
                        "cases": 24, "convolution_orders": [2, 3]},
        "monte_carlo": {"mu": [-1, 0, 1], "sigma": [.7, 1.5], "refractory": [0, .15],
                        "x": .4, "horizon": 1.5, "reset": .8, "cases": 12,
                        "samples_per_case": 50000, "generator": "PCG64",
                        "seed_base": 2026103100},
        "thresholds": {"cdf_atol": 2e-11, "cdf_rtol": 2e-9,
                       "fd_atol": 3e-8, "fd_rtol": 3e-7,
                       "right_fd_atol": 2e-6, "right_fd_rtol": 5e-6,
                       "convolution_atol": 2e-8, "convolution_rtol": 2e-7,
                       "mass_atol": 1e-8, "pmf_min": -2e-13, "pmf_sum_atol": 2e-11,
                       "mc_standard_errors": 6, "mc_probability_floor": "3/N"},
        "finite_difference": {"central_h": "min(1e-5*max(1,x),x/4)",
                              "right_h": 1e-6, "right_formula": "(-3f(0)+4f(h)-f(2h))/(2h)"},
        "quad": {"epsabs": 2e-11, "epsrel": 2e-9, "limit": 200},
        "boundary": "x=0 immediate atom; H=0,x=0 count=1 and dx=NaN; sigma=0 rejected",
    }


def scalar(value):
    return float(np.asarray(value))


def source_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("renewal.py", "renewal_audit.py", "MATHEMATICS.md")}


class Recorder:
    def __init__(self, path):
        self.raw = (path / "cases.jsonl").open("x")
        self.failed = (path / "failures.jsonl").open("x")
        self.total = 0
        self.failures = 0
        self.groups = {}

    def add(self, group, case, passed, **evidence):
        row = {"group": group, "case": case, "passed": bool(passed), **evidence}
        line = json.dumps(row, sort_keys=True, allow_nan=False) + "\n"
        self.raw.write(line)
        self.raw.flush()
        self.total += 1
        self.groups[group] = self.groups.get(group, 0) + 1
        if not passed:
            self.failed.write(line)
            self.failed.flush()
            self.failures += 1

    def close(self):
        self.raw.close()
        self.failed.close()


def independent_cdf(x, mu, sigma, horizon):
    if x == 0:
        return 1.0
    if horizon <= 0:
        return 0.0
    if mu == 0:
        return float(levy.cdf(horizon, scale=(x / sigma) ** 2))
    factor = math.exp(-2 * mu * x / sigma ** 2) if mu > 0 else 1.0
    return factor * float(invgauss.cdf(horizon, sigma ** 2 / (abs(mu) * x),
                                      scale=x ** 2 / sigma ** 2))


def raw_density(t, distance, mu, sigma):
    if t <= 0 or distance <= 0:
        return 0.0
    return (distance / (sigma * math.sqrt(2 * math.pi) * t ** 1.5)
            * math.exp(-(distance + mu * t) ** 2 / (2 * sigma ** 2 * t)))


def scalar_cdf_for_quadrature(x, mu, sigma, t):
    # Independent elementary implementation only for the moderate integration domain.
    if t <= 0:
        return 0.0
    scale = sigma * math.sqrt(2 * t)
    first = .5 * math.erfc((x + mu * t) / scale)
    second = math.exp(-2 * mu * x / sigma ** 2) * .5 * math.erfc((x - mu * t) / scale)
    return first + second


def integrate(function, upper, distance, mu, sigma, lower=0.0):
    if upper <= lower:
        return 0.0, 0.0
    mode = 2 * distance ** 2 / (math.sqrt(9 * sigma ** 4 + 4 * mu ** 2 * distance ** 2)
                               + 3 * sigma ** 2)
    points = [mode] if lower < mode < upper else None
    return quad(function, lower, upper, epsabs=2e-11, epsrel=2e-9, limit=200, points=points)


def convolution(order, distance, mu, sigma, available, reset):
    if available <= 0:
        return 0.0
    if order == 1:
        return scalar_cdf_for_quadrature(distance, mu, sigma, available)
    return integrate(lambda t: raw_density(t, distance, mu, sigma)
                     * convolution(order - 1, reset, mu, sigma, available - t, reset),
                     available, distance, mu, sigma)[0]


def grid_cases(config, refractory):
    axes = [config[key] for key in ("mu", "sigma", "x", "horizon", "reset")]
    for mu, sigma, x, horizon, reset, d in itertools.product(*axes, refractory):
        yield {"x": x, "mu": mu, "sigma": sigma, "horizon": horizon,
               "reset": reset, "refractory": d}


def audit_grid(rec, cases, group):
    for case in cases:
        details = r.expected_count_details(**case)
        mean, dx = scalar(details["mean"]), scalar(details["dx"])
        terms = details["summed_terms"]
        pmf = r.count_pmf(np.arange(terms + 1), **case)
        missing = scalar(r.count_tail(terms + 1, **case))
        mean_pmf = float(np.arange(terms + 1) @ pmf)
        cdf = scalar(r.first_passage_cdf(*[case[k] for k in ("x", "mu", "sigma", "horizon")]))
        reference = independent_cdf(*[case[k] for k in ("x", "mu", "sigma", "horizon")])
        x = case["x"]
        if x == 0:
            h = 1e-6
            fd = (-3 * mean + 4 * scalar(r.expected_count(**{**case, "x": h}))
                  - scalar(r.expected_count(**{**case, "x": 2 * h}))) / (2 * h)
            tolerance = 2e-6 + 5e-6 * abs(dx)
            derivative_kind = "right"
        else:
            h = min(1e-5 * max(1, x), x / 4)
            fd = (scalar(r.expected_count(**{**case, "x": x + h}))
                  - scalar(r.expected_count(**{**case, "x": x - h}))) / (2 * h)
            tolerance = 3e-8 + 3e-7 * abs(dx)
            derivative_kind = "central"
        mb, db = scalar(details["mean_remainder_bound"]), scalar(details["dx_remainder_bound"])
        checks = {"cdf_reference": abs(cdf - reference) <= 2e-11 + 2e-9 * abs(reference),
                  "cdf_domain": 0 <= cdf <= 1, "nonnegative_count": mean >= 0,
                  "monotone_dx": dx <= 2e-13, "gradient": abs(fd - dx) <= tolerance,
                  "pmf_nonnegative": float(pmf.min()) >= -2e-13,
                  "pmf_mass": abs(float(pmf.sum()) + missing - 1) <= 2e-11,
                  "pmf_mean": abs(mean_pmf + terms * missing - mean) <= 2e-11,
                  "mean_tail": mb <= r.TAIL_ATOL + r.TAIL_RTOL * abs(mean),
                  "dx_tail": db <= r.TAIL_ATOL + r.TAIL_RTOL * abs(dx)}
        rec.add(group, case, all(checks.values()), checks=checks, cdf=cdf, cdf_reference=reference,
                mean=mean, dx=dx, finite_difference=fd, fd_step=h, derivative_kind=derivative_kind,
                gradient_tolerance=tolerance, summed_terms=terms, mean_remainder_bound=mb,
                dx_remainder_bound=db, pmf=pmf.tolist(), omitted_probability=missing)


def audit_integrals(rec, cases):
    for case in cases:
        x, mu, sigma, h, reset, d = [case[k] for k in ("x", "mu", "sigma", "horizon", "reset", "refractory")]
        for n in (2, 3):
            numerical = convolution(n, x, mu, sigma, h - (n - 1) * d, reset)
            analytic = scalar(r.count_tail(n, **case))
            rec.add("convolution", {**case, "order": n},
                    abs(numerical - analytic) <= 2e-8 + 2e-7 * abs(numerical),
                    analytic=analytic, numerical=numerical, absolute_error=abs(numerical - analytic))
        initial_active = 1 - independent_cdf(x, mu, sigma, h)
        active, recovering, error = initial_active, 0.0, 0.0
        terms = r.expected_count_details(**case)["summed_terms"]
        for j in range(1, terms + 1):
            distance = x + (j - 1) * reset
            remaining = h - j * d
            integral, err = integrate(lambda t: raw_density(t, distance, mu, sigma)
                                      * (1 - scalar_cdf_for_quadrature(reset, mu, sigma, remaining - t)),
                                      remaining, distance, mu, sigma)
            active += integral
            error += err
            integral, err = integrate(lambda t: raw_density(t, distance, mu, sigma),
                                      h - (j - 1) * d, distance, mu, sigma, max(0.0, remaining))
            recovering += integral
            error += err
        killed, killed_error = quad(lambda y: scalar(r.killed_density(y, x, mu, sigma, h)),
                                    0, np.inf, epsabs=2e-11, epsrel=2e-9, limit=200)
        passed = abs(active + recovering - 1) <= 1e-8 and abs(killed - initial_active) <= 1e-8
        rec.add("mass_integrals", case, passed, active=active, refractory=recovering,
                total=active + recovering, quadrature_error_estimate=error, killed_mass=killed,
                independent_survival=initial_active, killed_quadrature_error=killed_error, summed_terms=terms)


def sample_hitting_times(rng, distance, mu, sigma, size):
    if distance == 0:
        return np.zeros(size)
    if mu == 0:
        z = rng.standard_normal(size)
        return (distance / (sigma * z)) ** 2
    times = rng.wald(distance / abs(mu), distance ** 2 / sigma ** 2, size)
    if mu > 0:
        times[rng.random(size) >= math.exp(-2 * mu * distance / sigma ** 2)] = np.inf
    return times


def sample_counts(case, size, seed):
    rng = np.random.Generator(np.random.PCG64(seed))
    counts = np.zeros(size, dtype=np.uint32)
    elapsed = sample_hitting_times(rng, case["x"], case["mu"], case["sigma"], size)
    while True:
        firing = np.flatnonzero(elapsed <= case["horizon"])
        if not len(firing):
            break
        counts[firing] += 1
        elapsed[firing] += case["refractory"] + sample_hitting_times(
            rng, case["reset"], case["mu"], case["sigma"], len(firing))
    return counts


def audit_mc(rec, cases, size, path):
    for i, case in enumerate(cases):
        seed = 2026103100 + i
        counts = sample_counts(case, size, seed)
        filename = f"mc_counts_{i:02d}.npz"
        np.savez_compressed(path / filename, counts=counts, seed=np.array(seed))
        analytic = scalar(r.expected_count(**case))
        observed = float(counts.mean())
        se = float(counts.std(ddof=1) / math.sqrt(size))
        k = np.arange(int(counts.max()) + 4)
        pmf = r.count_pmf(k, **case)
        observed_pmf = np.bincount(counts, minlength=len(k)) / size
        threshold = 6 * np.sqrt(pmf * (1 - pmf) / size) + 3 / size
        checks = {"mean": abs(observed - analytic) <= 6 * se + 3 / size,
                  "pmf": bool(np.all(np.abs(observed_pmf - pmf) <= threshold))}
        rec.add("monte_carlo", {**case, "seed": seed, "samples": size}, all(checks.values()),
                checks=checks, analytic_mean=analytic, observed_mean=observed, mean_standard_error=se,
                analytic_pmf=pmf.tolist(), observed_pmf=observed_pmf.tolist(),
                pmf_tolerance=threshold.tolist(), raw_counts=filename)


def audit_domains(rec):
    base = dict(x=.4, mu=-.25, sigma=1., horizon=1., reset=.8, refractory=.15)
    invalid = [(key, value) for key in base for value in (float("nan"), float("inf"))]
    invalid += [("x", -.1), ("sigma", 0), ("sigma", -1), ("horizon", -1),
                ("reset", 0), ("reset", -1), ("refractory", -1)]
    for key, value in invalid:
        try:
            r.expected_count(**{**base, key: value})
            raised = False
        except ValueError:
            raised = True
        rec.add("invalid_domain", {"parameter": key, "value": str(value)}, raised)
    for x, h in ((0, 0), (.4, 0), (0, .1), (0, .15)):
        mean = scalar(r.expected_count(**{**base, "x": x, "horizon": h}))
        dx = scalar(r.expected_count_dx(**{**base, "x": x, "horizon": h}))
        expected = 1.0 if x == 0 else 0.0
        rec.add("boundary", {"x": x, "horizon": h}, mean == expected and
                (math.isnan(dx) if x == 0 and h == 0 else math.isfinite(dx)),
                count=mean, dx="NaN: undefined corner" if math.isnan(dx) else dx)
    for mu, sigma, x, h in ((-8,.05,.1,.01),(-8,.05,1.,1.),(8,.05,.1,1.),
                            (-1,.0001,1.,1.),(-1,.0001,.1,1.),(1,.0001,.1,1.),
                            (0,.001,.001,.01),(0,2.,10.,100.),(-1,1.,.1,1e4),(1,1.,.1,1e4)):
        actual = scalar(r.first_passage_cdf(x, mu, sigma, h))
        reference = independent_cdf(x, mu, sigma, h)
        dx = scalar(r.first_passage_cdf_dx(x, mu, sigma, h))
        rec.add("extreme_cdf", dict(x=x,mu=mu,sigma=sigma,horizon=h),
                abs(actual-reference) <= 2e-11+2e-9*abs(reference) and math.isfinite(dx) and dx<=0,
                cdf=actual, reference=reference, dx=dx)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("protocol", "development", "formal"), default="protocol")
    parser.add_argument("--out", required=True)
    parser.add_argument("--frozen-commit", default="")
    args = parser.parse_args()
    if args.stage == "formal" and not re.fullmatch(r"[0-9a-fA-F]{40}", args.frozen_commit):
        parser.error("formal requires the reviewed/frozen 40-character commit identity")
    path = Path(args.out)
    path.mkdir(parents=True, exist_ok=False)
    config = protocol()
    protocol_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
    (path / "protocol.json").write_text(protocol_text)
    manifest = {"stage": args.stage, "frozen_commit": args.frozen_commit or None,
                "source_sha256": source_hashes(), "python": platform.python_version(),
                "numpy": np.__version__, "scipy": scipy.__version__,
                "protocol_sha256": hashlib.sha256(protocol_text.encode()).hexdigest()}
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if args.stage == "protocol":
        print(json.dumps(manifest, sort_keys=True))
        return 0
    rec = Recorder(path)
    main_cases = list(grid_cases(config["main"], [.15, .5]))
    zero_cases = list(grid_cases(config["main"], [0]))
    integration = [dict(x=x,mu=mu,sigma=s,horizon=1.5,reset=.8,refractory=d)
                   for mu,s,x,d in itertools.product([-1,0,1],[.7,1.5],[.2,.8],[0,.15])]
    mc = [dict(x=.4,mu=mu,sigma=s,horizon=1.5,reset=.8,refractory=d)
          for mu,s,d in itertools.product([-1,0,1],[.7,1.5],[0,.15])]
    if args.stage == "development":
        main_cases, zero_cases, integration, mc = main_cases[::71], zero_cases[::83], integration[::7], mc[::4]
    audit_grid(rec, main_cases, "finite_refractory_grid")
    audit_grid(rec, zero_cases, "zero_refractory_diagnostic")
    audit_integrals(rec, integration)
    audit_mc(rec, mc, 50000 if args.stage == "formal" else 5000, path)
    audit_domains(rec)
    summary = {"stage": args.stage, "cases": rec.total, "failures": rec.failures,
               "groups": rec.groups, "all_passed": rec.failures == 0}
    rec.close()
    (path / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return int(rec.failures != 0)


if __name__ == "__main__":
    sys.exit(main())
