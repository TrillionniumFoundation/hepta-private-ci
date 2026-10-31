"""Reproduce two exact-source defects and verify narrow corrected copies."""

import argparse
from dataclasses import asdict
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
import time

import mpmath as mp
import numpy as np
import scipy
from scipy.integrate import quad
from scipy.linalg import expm

ROOT = Path(__file__).resolve().parent


def load_source(kind, filename):
    path = ROOT / "vendor" / kind / filename
    name = "round10_" + kind + "_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_identity():
    manifest = json.loads((ROOT / "SOURCE.json").read_text())
    records = []
    for item in manifest["sources"]:
        data = (ROOT / item["upstream_local"]).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != item["blob_sha"]:
            raise AssertionError("Pinned upstream bytes changed: " + item["path"])
        patch_data = (ROOT / item["patched_local"]).read_bytes()
        records.append(dict(item, upstream_sha256=hashlib.sha256(data).hexdigest(),
                            patched_sha256=hashlib.sha256(patch_data).hexdigest()))
    return records


def discount_audit():
    old = load_source("upstream", "moving_boundary_enclosure.py")
    new = load_source("patched", "moving_boundary_enclosure.py")
    counterexamples = []
    for sigma, digits in (("1e-40", 50), ("1e-80", 100)):
        for discount in (".2", "1.25"):
            args = ("1", "0", "-1", sigma, "0", "2", discount)
            before = old.linear_boundary_first_hit(*args, dps=digits)
            after = new.linear_boundary_first_hit(*args, dps=digits)
            with localcontext() as ctx:
                ctx.prec = digits
                nu, vol, q = Decimal(-1), Decimal(sigma), Decimal(discount)
                radical = (nu * nu + 2 * q * vol * vol).sqrt()
                raw_rate = (nu + radical) / (vol * vol)
                stable_rate = 2 * q / (radical - nu)
            with mp.workdps(150):
                q, vol = mp.mpf(discount), mp.mpf(sigma)
                epsilon, horizon = mp.mpf(".001"), mp.mpf(2)
                # On sup_[0,T]|sigma W| <= epsilon, the hit time lies in
                # [1-epsilon,1+epsilon]. Reflection and Gaussian Chernoff
                # give this independent physical error bound.
                exceptional = 4 * mp.exp(-epsilon**2 / (2 * vol**2 * horizon))
                lower = mp.exp(-q * (1 + epsilon)) * (1 - exceptional)
                upper = mp.exp(-q * (1 - epsilon)) + exceptional
                assert not lower <= before.discounted <= upper
                assert lower <= after.discounted <= upper
                assert before.discounted == 1
                counterexamples.append(dict(sigma=sigma, dps=digits, q=discount,
                    original_G=mp.nstr(before.discounted, 40),
                    corrected_G=mp.nstr(after.discounted, 40),
                    independent_physical_interval=[float(lower), float(upper)],
                    original_absolute_error_vs_zero_noise_limit=float(abs(before.discounted-mp.exp(-q))),
                    corrected_absolute_error_vs_zero_noise_limit=float(abs(after.discounted-mp.exp(-q))),
                    decimal_unstable_rate=str(raw_rate), decimal_rationalized_rate=str(stable_rate),
                    interval_scope="Physical Brownian bound; not a floating-point interval certificate"))
    ordinary = []
    for gap, drift, vol, horizon, q in ((1., -.3, .7, 2., .2), (.6, .4, .8, 1.3, .5),
                                     (.2, 0., .35, .9, 1.1), (1.2, -1., .45, 1.6, .3)):
        def density(t):
            if t <= 0:
                return 0.
            return gap * math.exp(-(gap+drift*t)**2/(2*vol*vol*t)) / (vol*math.sqrt(2*math.pi*t**3))
        f, ferr = quad(density, 0, horizon, epsabs=2e-13, epsrel=2e-13)
        g, gerr = quad(lambda t: math.exp(-q*t)*density(t), 0, horizon,
                       epsabs=2e-13, epsrel=2e-13)
        got = new.linear_boundary_first_hit(gap, 0, drift, vol, 0, horizon, q)
        errors = [abs(float(got.probability)-f), abs(float(got.discounted)-g)]
        assert max(errors) < 5e-12
        zero = new.linear_boundary_first_hit(gap, 0, drift, vol, 0, horizon, 0)
        assert zero.discounted == zero.probability
        ordinary.append(dict(parameters=[gap, drift, vol, horizon, q], absolute_errors=errors,
                             quadrature_estimates=[ferr, gerr]))
    return dict(counterexamples=counterexamples, ordinary_time_density_checks=ordinary,
                defect="Negative-drift radical cancellation admitted G=1 despite a genuine discount")


def state_audit():
    old = load_source("upstream", "renewal_event_oracle.py")
    new = load_source("patched", "renewal_event_oracle.py")
    rejected = []
    for active, no_active, no_refractory in ((.1, .8, .1), (.9, .1, .8)):
        snapshot = dict(time=1., active=active, no_fire_active=no_active,
                        no_fire_refractory=no_refractory, ever_fired=.1,
                        expected_count=10., version=1)
        for duration in (0., .01):
            original = old.advance(old.RenewalState(**snapshot), 3., 4., duration)
            try:
                new.advance(new.RenewalState(**snapshot), 3., 4., duration)
            except ValueError:
                pass
            else:
                raise AssertionError("Impossible joint state accepted")
            rejected.append(dict(input=snapshot, duration=duration,
                original_output=asdict(original), corrected="ValueError",
                original_active_dominance_violation=original.no_fire_active-original.active,
                original_refractory_dominance_violation=original.no_fire_refractory-(1-original.active)))
    ordinary = []
    segments = ((3., 4., .01), (1.2, 2.3, .4), (4.3, .8, .06), (.7, 3.2, .9))
    for active in (0., .2, .7, 1.):
        state = new.RenewalState.initial(active)
        physical = np.array([active, 1-active])
        killed = physical.copy()
        count = 0.
        for lam, gamma, dt in segments:
            generator = np.array([[-lam, lam], [gamma, -gamma]])
            loss_generator = np.array([[-lam, 0.], [gamma, -gamma]])
            count += quad(lambda t: lam*(physical @ expm(generator*t))[0], 0, dt,
                          epsabs=1e-12, epsrel=1e-12)[0]
            physical = physical @ expm(generator*dt)
            killed = killed @ expm(loss_generator*dt)
            state = new.advance(state, lam, gamma, dt)
            errors = [abs(state.active-physical[0]), abs(state.no_fire_active-killed[0]),
                      abs(state.no_fire_refractory-killed[1]), abs(state.expected_count-count)]
            assert max(errors) < 5e-12
            assert state.no_fire_active <= state.active+1e-12
            assert state.no_fire_refractory <= 1-state.active+1e-12
            ordinary.append(dict(initial_active=active, segment=[lam, gamma, dt],
                                 absolute_errors=errors))
    return dict(counterexamples=rejected, independent_ctmc_checks=ordinary,
                defect="Killed no-fire joint masses exceeded their physical parent events")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    result = dict(schema="hcsn.round10.dynamics.regression.v1", sources=source_identity(),
                  discount=discount_audit(), joint_state=state_audit(), passed=True,
                  scope="Two narrow mathematical-reference fixes; not native production validation",
                  environment=dict(python=platform.python_version(), numpy=np.__version__,
                                   scipy=scipy.__version__, mpmath=mp.__version__),
                  wall_seconds=time.perf_counter()-started)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(passed=True, output=str(args.output),
                         reproduced_discount_counterexamples=4, rejected_joint_states=4,
                         independent_regular_checks=20, wall_seconds=result["wall_seconds"])))


if __name__ == "__main__":
    main()
