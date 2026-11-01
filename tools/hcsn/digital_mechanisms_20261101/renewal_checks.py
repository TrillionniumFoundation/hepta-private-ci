"""Independent law checks, event Monte Carlo, and actual Rust process replay.

Run as a module with --rustc PATH. Writes a JSON result to stdout; all executable
and path fixtures live in a temporary directory. Monte Carlo uses NumPy's RNG
and a separate vectorized sampler, not the research xorshift implementation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import subprocess
import tempfile
import time

import numpy as np
from scipy.integrate import quad
from scipy.linalg import expm, expm_frechet

from .renewal import (Sampler, expected_events, export_native, fingerprint,
                      first_hit, forecast, generator, transition)


def monte_carlo(q, horizon, samples, seed):
    """Independently implement Gillespie via batch exponential/categorical draws."""
    rng = np.random.default_rng(seed)
    n = len(q)-2
    states, clocks = np.full(samples, n//2), np.zeros(samples)
    counts, first = np.zeros((samples, 2), dtype=int), np.zeros(samples, dtype=int)
    live = np.arange(samples)
    off = q.copy()
    np.fill_diagonal(off, 0.)
    probabilities = np.cumsum(off/(-np.diag(q))[:, None], axis=1)
    for iteration in range(100000):
        if not len(live):
            return states, counts, first
        current = states[live]
        times = clocks[live] + rng.exponential(1/(-np.diag(q)[current]))
        accept = times <= horizon
        live, times, current = live[accept], times[accept], current[accept]
        uniform = rng.random(len(live))
        targets = np.sum(uniform[:, None] >= probabilities[current], axis=1)
        if np.any(targets >= len(q)):
            raise AssertionError("Monte Carlo categorical normalization")
        for side in (0, 1):
            hit = (current < n) & (targets == n+side)
            counts[live[hit], side] += 1
            first[live[hit & (first[live] == 0)]] = side+1
        states[live], clocks[live] = targets, times
    raise RuntimeError("Monte Carlo jump cap exceeded")


def run(rustc, samples=12000):
    started, cpu = time.perf_counter(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    if samples < 1000:
        raise ValueError("at least 1000 Monte Carlo paths required")
    p = dict(boundary=1., diffusion=.575, gain=.45, drift_bias=.04,
             reset_plus=-.24, reset_minus=.19, recovery_rate=1.125)
    q, x = generator(p, 1, .85)
    initial = np.eye(17)[7]
    max_mass, max_semigroup = 0., 0.
    for symbol in (-1, 0, 1):
        matrix, _ = generator(p, symbol, .85)
        for a, b in ((0., .3), (.25, .75), (1.5, 3.)):
            t = transition(matrix, a+b)
            max_mass = max(max_mass, float(np.max(np.abs(t.sum(axis=1)-1))))
            max_semigroup = max(max_semigroup, float(np.max(np.abs(t-transition(matrix, a)@transition(matrix, b)))))
    assert max_mass < 2e-12 and max_semigroup < 2e-12
    bank = forecast(q, initial, (.25, .75, 1.5, 6.), x, (-.5, 0., .5))
    partition_defect = max(abs(sum(r[k] for k in ("active_below_equal", "active_above", "lower_refractory", "upper_refractory"))-1) for r in bank)
    assert partition_defect < 2e-12
    hit = first_hit(q, initial[:15], 6.)
    density_integrals = [quad(lambda t: initial[:15]@expm(q[:15, :15]*t)@q[:15, 15+side], 0., 6., epsabs=1e-11)[0] for side in (0, 1)]
    hit_error = max(abs(density_integrals[i]-hit[k]) for i, k in enumerate(("lower", "upper")))
    counts = expected_events(q, initial, 6.)
    integral_counts = [quad(lambda t: initial@expm(q*t)@np.r_[q[:15, 15+i], 0., 0.], 0., 6., epsabs=1e-11)[0] for i in (0, 1)]
    count_error = float(np.max(np.abs(counts-integral_counts)))
    assert hit_error < 2e-11 and count_error < 2e-11
    assert sum(counts) > hit["lower"]+hit["upper"]+.2
    h = 2*p["boundary"]/16
    dq = np.zeros_like(q)
    for i in range(15):
        dq[i, i] = -1/h
        dq[i, i+1 if i < 14 else 16] = 1/h
    eps = 1e-6
    plus, _ = generator(dict(p, drift_bias=p["drift_bias"]+eps), 1, .85)
    minus, _ = generator(dict(p, drift_bias=p["drift_bias"]-eps), 1, .85)
    finite_difference = (expm(plus*.75)-expm(minus*.75))/(2*eps)
    frechet = expm_frechet(q*.75, dq*.75, compute_expm=False)
    gradient_error = float(np.max(np.abs(finite_difference-frechet)))
    assert gradient_error < 2e-8
    mc = []
    # Union bound covers 4 horizons × (17 final states + 2 first-event signs).
    simultaneous_bound = math.sqrt(math.log(2*76/.001)/(2*samples))
    for j, horizon in enumerate((.25, .75, 1.5, 6.)):
        states, event_counts, first = monte_carlo(q, horizon, samples, 861100+j)
        predicted = initial@transition(q, horizon)
        empirical = np.bincount(states, minlength=17)/samples
        hit_prediction = first_hit(q, initial[:15], horizon)
        hit_empirical = np.array([(first == side+1).mean() for side in (0, 1)])
        prediction_counts = expected_events(q, initial, horizon)
        count_se = event_counts.std(axis=0, ddof=1)/math.sqrt(samples)
        count_z = np.abs(event_counts.mean(axis=0)-prediction_counts)/np.maximum(count_se, 1/samples)
        max_error = max(float(np.max(np.abs(empirical-predicted))), float(np.max(np.abs(hit_empirical-[hit_prediction["lower"], hit_prediction["upper"]]))))
        assert max_error <= simultaneous_bound
        mc.append(dict(horizon=horizon, samples=samples, maximum_probability_error=max_error,
                       expected_event_counts=prediction_counts.tolist(), empirical_event_counts=event_counts.mean(axis=0).tolist(),
                       descriptive_count_standard_errors=count_z.tolist(), first_hit=hit_prediction))
    native = Path(__file__).with_name("renewal_native.rs")
    replay_cases, context_cases, receipts = 0, 0, []
    with tempfile.TemporaryDirectory(prefix="hcsn-renewal-") as folder:
        d = Path(folder)
        binary, model, changed = d/"renewal", d/"model.txt", d/"changed.txt"
        build = subprocess.run([rustc, "--edition=2024", "-O", str(native), "-o", str(binary)], capture_output=True, text=True)
        if build.returncode:
            raise RuntimeError(build.stderr)
        compiler = subprocess.check_output([rustc, "--version"], text=True).strip()
        binary_sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()
        model_identity = export_native(model, q)
        other, _ = generator(p, -1, .65)
        export_native(changed, other)
        def invoke(*args, success=True):
            result = subprocess.run([str(binary), *map(str, args)], capture_output=True, text=True)
            if (result.returncode == 0) != success:
                raise AssertionError((args, result.stdout, result.stderr))
            return json.loads(result.stdout) if success else result.stderr.strip()
        for seed in (17, 123, 98765, 18446744073709551615):
            for start in (7, 15, 16):
                prefix = f"{seed}-{start}"
                full, cut, resumed = [d/f"{prefix}-{name}" for name in ("full", "cut", "resumed")]
                out = invoke("new", model, seed, 6., full, str(full)+".events", start)
                invoke("new", model, seed, .75, cut, str(cut)+".events", start)
                invoke("resume", model, cut, 6., resumed, str(resumed)+".events")
                assert full.read_bytes() == resumed.read_bytes()
                assert Path(str(full)+".events").read_bytes() == Path(str(cut)+".events").read_bytes()+Path(str(resumed)+".events").read_bytes()
                python = Sampler(q, start, seed)
                python.advance(6.)
                events = [json.loads(line) for line in Path(str(full)+".events").read_text().splitlines()]
                assert python.state == out["state"] and python.jumps == out["jumps"] and len(python.events) == len(events)
                assert all(s == e["side"] and abs(t-e["time"]) < 3e-13 for (t, s), e in zip(python.events, events))
                receipts.append(dict(seed=seed, initial_state=start, summary=out, events=events,
                                     final_checkpoint=full.read_text(),
                                     final_checkpoint_sha256=hashlib.sha256(full.read_bytes()).hexdigest(),
                                     whole_split_checkpoint_and_trace_identical=True))
                replay_cases += 1
        switched = d/"switched"
        invoke("switch", model, changed, cut, 6., switched, str(switched)+".events")
        python = Sampler(q, start, seed)
        python.advance(.75)
        python.change_generator(other)
        switched_events = python.advance(6.)
        recorded = [json.loads(line) for line in Path(str(switched)+".events").read_text().splitlines()]
        assert len(switched_events) == len(recorded)
        assert all(s == e["side"] and abs(t-e["time"]) < 3e-13 for (t, s), e in zip(switched_events, recorded))
        context_cases += 1
        context_receipt = dict(seed=seed, initial_state=start, cut=.75, events=recorded,
                               final_checkpoint=switched.read_text(), python_agrees=True)
        rejections = []
        rejections.append(invoke("resume", changed, cut, 6., d/"badmodel", d/"badmodel.events", success=False))
        damaged = d/"damaged"
        damaged.write_text(cut.read_text().replace("HCNC1", "HCNC9"))
        rejections.append(invoke("resume", model, damaged, 6., d/"damagedout", d/"damaged.events", success=False))
        body = cut.read_text().splitlines()[0].split()
        body[6] = "0"
        invalid = " ".join(body)+"\n"
        damaged.write_text(invalid+f"{fingerprint(invalid.encode()):016x}\n")
        rejections.append(invoke("resume", model, damaged, 6., d/"invalid", d/"invalid.events", success=False))
        rejections.append(invoke("resume", model, cut, .25, d/"reverse", d/"reverse.events", success=False))
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(schema="digital-renewal-verification-v1", passed=True, model="continuous-time finite upwind CTMC; not exact Brownian",
                source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), native, Path(__file__).with_name("renewal.py"))},
                compiler=compiler, native_binary_sha256=binary_sha256, model_fnv64=model_identity,
                maximum_mass_defect=max_mass, maximum_semigroup_error=max_semigroup,
                forecast_partition_defect=partition_defect, first_hit_density_integral_error=hit_error,
                event_count_integral_error=count_error, frechet_gradient_error=gradient_error,
                monte_carlo=mc, monte_carlo_simultaneous_hoeffding_coverage=.999,
                monte_carlo_simultaneous_absolute_bound=simultaneous_bound,
                native_fresh_process_replay_cases=replay_cases, native_context_change_cases=context_cases,
                native_replay_receipts=receipts, native_context_receipt=context_receipt,
                corruption_and_mismatch_rejections=rejections, research_only=True, production_activation=False,
                timing=dict(wall_seconds=time.perf_counter()-started, python_cpu_seconds=time.process_time()-cpu,
                            subprocess_cpu_seconds=child_end.ru_utime+child_end.ru_stime-child_start.ru_utime-child_start.ru_stime,
                            subprocess_scope="Rust compilation, compiler-version call, and all native path/rejection executions"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--samples", type=int, default=12000)
    args = parser.parse_args()
    print(json.dumps(run(args.rustc, args.samples), sort_keys=True, indent=2, allow_nan=False))
