"""Same-law numerical costs and a one-factor recovery-shape intervention."""

import argparse
import copy
import hashlib
import json
import math
import platform
import time
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import scipy
from scipy.linalg import expm

from ..calibrated_operator_r11_20261031.numerics.kernel import Dual, FullHX
from ..unified_cell_r12_20261031.cell import BASE_THETA, PHYSICAL_INDICES
from .law import Law
from .world import DURATION_SETS, make_episode


def uniformized_transition(generator, dt, tolerance=1e-13, return_info=False):
    """Positive Poisson-series transition, independent of scipy.linalg.expm.

    A decreasing-ratio geometric tail bound controls truncation. Long time
    intervals are split to Poisson means <=16 and composed. No normalization
    repairs or clipping conceal truncation error or invalid generators.
    """
    q = np.asarray(generator, dtype=float)
    dt, tolerance = float(dt), float(tolerance)
    if (q.ndim != 2 or q.shape[0] != q.shape[1] or not np.isfinite(q).all()
            or not np.isfinite(dt) or dt < 0 or not 0 < tolerance < 1):
        raise ValueError("Invalid uniformization input")
    off = q.copy()
    np.fill_diagonal(off, 0.)
    if np.any(off < 0) or not np.allclose(q.sum(1), 0, rtol=0, atol=5e-12):
        raise ValueError("Uniformization requires a conservative row generator")
    rate = float(np.max(-np.diag(q)))
    identity = np.eye(len(q))
    if rate == 0 or dt == 0:
        info = dict(poisson_terms=1, segments=1, series_tail_bound=0., rate=rate)
        return (identity, info) if return_info else identity
    segments = max(1, math.ceil(rate * dt / 16))
    mean = rate * dt / segments
    embedded = identity + q / rate
    weight, power = math.exp(-mean), identity
    result = weight * power
    order, bound = 0, float("inf")
    while bound > tolerance / segments:
        order += 1
        weight *= mean / order
        power = power @ embedded
        result += weight * power
        if order + 2 > mean:
            next_weight = weight * mean / (order + 1)
            bound = next_weight / (1 - mean / (order + 2))
        if order > 10000:
            raise RuntimeError("Uniformization did not attain its truncation tolerance")
    if segments > 1:
        result = np.linalg.matrix_power(result, segments)
    info = dict(poisson_terms=order + 1, segments=segments,
                series_tail_bound=min(1., segments * bound), rate=rate,
                error_scope="Series truncation only; floating-point error is separately compared")
    return (result, info) if return_info else result


class UniformizedLaw:
    """Same mathematical law with an independently implemented transition."""

    def __init__(self, law, tolerance=1e-13):
        self._law, self.tolerance = law, float(tolerance)
        self._cache = {}
        body = dict(law=law.identity, implementation="positive-uniformization-v1",
                    tolerance=self.tolerance)
        self.implementation_identity = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def __getattr__(self, name):
        return getattr(self._law, name)

    def transition(self, dt, method="uniformization"):
        if method == "expm":
            return self._law.transition(dt)
        if method != "uniformization":
            raise ValueError("Unknown numerical implementation")
        dt = self._law._duration(dt)
        if dt not in self._cache:
            matrix = uniformized_transition(self.Q, dt, self.tolerance)
            matrix.setflags(write=False)
            self._cache[dt] = matrix
        return self._cache[dt]


def with_uniformization(law, tolerance=1e-13):
    return UniformizedLaw(law, tolerance)


def make_memoryless(law):
    """Replace the two recovery stages by one exponential clock of equal mean.

    Both represented recovery phases have the same direct-to-reset hazard;
    they are therefore lumpable. Natural absorption still enters phase eight.
    Active rates, emissions, reset distribution and content retention remain
    exactly unchanged. This is a candidate model, never a world intervention.
    """
    if isinstance(law, UniformizedLaw):
        law = law._law
    result = copy.copy(law)
    result.Q = law.Q.copy()
    result.params = json.loads(json.dumps(law.params))
    mean = float(law.params.get("recovery_mean", 2 / law.recovery_rate))
    result.recovery_rate = 1 / mean
    for phase in (8, 9):
        for content in range(4):
            source = 4 * phase + content
            result.Q[source] = 0.
            for destination_phase, weight in enumerate(law.reset_weights):
                for destination_content in range(4):
                    retention = law.same_content if destination_content == content else (
                        1 - law.same_content) / 3
                    result.Q[source, 4 * destination_phase + destination_content] = (
                        result.recovery_rate * weight * retention)
            result.Q[source, source] = -result.recovery_rate
    result.mode = "memoryless"
    result.params.update(mode=result.mode, recovery_rate=result.recovery_rate,
                         recovery_mean=mean, recovery_profile="memoryless_same_mean",
                         source_law_identity=law.identity)
    result._finish()
    return result


def _measure(function, repeats, iterations=1):
    cpu, wall = [], []
    for _ in range(repeats):
        start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
        for _ in range(iterations):
            function()
        cpu.append((time.process_time_ns() - start_cpu) / 1e9)
        wall.append((time.perf_counter_ns() - start_wall) / 1e9)
    return dict(repeats=repeats, iterations_per_repeat=iterations,
                calls_total=repeats * iterations,
                cpu_total_seconds=float(sum(cpu)), wall_total_seconds=float(sum(wall)),
                cpu_median_seconds_per_call=float(np.median(cpu) / iterations),
                wall_median_seconds_per_call=float(np.median(wall) / iterations),
                cpu_repeat_seconds=cpu, wall_repeat_seconds=wall)


def _financial(theta):
    values = BASE_THETA.copy()
    values[PHYSICAL_INDICES] = [*theta, 1.3]
    tangent = np.zeros((9, 3))
    tangent[PHYSICAL_INDICES] = np.eye(3)
    return FullHX([Dual(value, tangent[j]) for j, value in enumerate(values)])


def _financial_bank(hx, centers):
    values = []
    for center in centers:
        x = Dual(center, np.zeros(3))
        equity = hx.equity(x)
        hit, discounted_hit = hx.first_hit(x, hx.m)
        debt = hx.c / hx.R + hx.discount * hx.q * (1 - hit)
        debt += (hx.alpha * hx.b / hx.m - hx.c / hx.R) * discounted_hit
        values.append((equity.v, hit.v, discounted_hit.v, debt.v))
    return np.asarray(values)


def _sensitivity(law, memoryless, episodes=16):
    """Fixed public histories, with no policy or confirmation-dependent choice."""
    nll = {"erlang": 0., "memoryless": 0.}
    beliefs = []
    observations = 0
    fingerprints = []
    for episode in range(episodes):
        world = make_episode(law, 815200 + episode, "iid" if episode % 2 == 0 else "ood")
        fingerprints.append(world.fingerprint)
        states = [np.stack([model.initial_prior(int(value)) for value in world.initial_values])
                  for model in (law, memoryless)]
        for query, key in enumerate(world.query_keys):
            key = int(key)
            for event in world.events_at(query):
                if event["kind"] == "WRITE":
                    for state in states:
                        phase = state[event["key"]].reshape(10, 4).sum(1)
                        state[event["key"]] = 0.
                        state[event["key"], event["value"]::4] = phase
            previous_step = 0
            for step, quality in ((1, "read"), (3, "refresh")):
                dt = float((step - previous_step) * world.dts[query])
                absolute = float(world.deadlines[query] if step == 3 else
                                 world.starts[query] + step * world.dts[query])
                token = world.observe(key, absolute, quality, query, step)
                for j, (name, model) in enumerate((("erlang", law), ("memoryless", memoryless))):
                    states[j] = states[j] @ model.transition(dt)
                    emission = model.E_read if quality == "read" else model.E_refresh
                    evidence = float(states[j][key] @ emission[:, token])
                    if evidence <= 0:
                        raise ValueError("Public history has zero likelihood")
                    nll[name] -= math.log(evidence)
                    states[j][key] *= emission[:, token] / evidence
                a = states[0][key].reshape(10, 4).sum(0)
                b = states[1][key].reshape(10, 4).sum(0)
                beliefs.append(float(np.max(np.abs(a - b))))
                observations += 1
                previous_step = step
    return dict(scope="Development prediction sensitivity, not a confirmatory utility claim",
                episodes=episodes, observations=observations,
                mean_observation_nll={key: value / observations for key, value in nll.items()},
                mean_max_content_difference=float(np.mean(beliefs)),
                max_content_difference=float(max(beliefs)), world_fingerprints=fingerprints)


def _wrong_endpoint_controls(law):
    """Audit-only counterexamples to replacing full regeneration by one hit."""
    augmented = np.zeros((44, 44))
    augmented[:40, :40] = law.killed
    augmented[np.arange(4), 40 + np.arange(4)] = law.event_rate[:4]
    reset = np.zeros((4, 40))
    reset[np.arange(4), 32 + np.arange(4)] = 1.

    def wrong(duration):
        matrix = expm(duration * augmented)
        surviving, first_by_content = matrix[:40, :40], matrix[:40, 40:]
        return surviving, surviving + first_by_content @ reset

    rows = []
    for dt in (.5, 2., 10.):
        killed, endpoint = wrong(dt)
        _, double = wrong(2 * dt)
        truth = law.transition(dt)
        rows.append(dict(dt=dt,
                         killed_only_mass_deficit=float(np.max(1 - killed.sum(1))),
                         reset_at_window_end_max_error=float(np.max(np.abs(endpoint - truth))),
                         reset_at_window_end_semigroup_error=float(np.max(np.abs(endpoint @ endpoint - double))),
                         first_hit=float(law.first_hit(law.prior, dt)),
                         repeated_count=float(law.event_count(law.prior, dt))))
    return dict(scope="Wrong substitutes for the declared Q; excluded from main efficacy arms", rows=rows)


def run_study(theta=(.30, .018), repeats=7, propagation_iterations=500):
    if repeats < 1 or propagation_iterations < 1:
        raise ValueError("Benchmark counts must be positive")
    try:
        from threadpoolctl import threadpool_info, threadpool_limits
        limits = threadpool_limits(limits=1)
    except ImportError:
        threadpool_info = lambda: []
        limits = nullcontext()
    with limits:
        law = Law(theta)
        uniform = with_uniformization(law)
        hx = _financial(theta)
        frozen_payload = law.export()
        preparation = dict(
            full_financial_boundary_with_three_tangents=_measure(lambda: _financial(theta), repeats),
            eight_center_financial_value_bank_with_tangents=_measure(
                lambda: _financial_bank(hx, law.centers), repeats),
            full_hx_to_law_construction=_measure(lambda: Law(theta), repeats),
            frozen_matrix_restore=_measure(lambda: Law.from_payload(frozen_payload), repeats))
        durations = sorted(set(DURATION_SETS["iid"] + DURATION_SETS["ood"]))
        transitions, propagation = [], []
        rng = np.random.default_rng(815100)
        for dt in durations:
            expected = expm(dt * law.Q)
            actual, info = uniformized_transition(law.Q, dt, return_info=True)
            transitions.append(dict(dt=dt, max_absolute_error=float(np.max(np.abs(actual - expected))),
                                    row_l1_error=float(np.max(np.sum(np.abs(actual - expected), axis=1))),
                                    row_sum_error=float(np.max(np.abs(actual.sum(1) - 1))),
                                    min_entry=float(actual.min()), series=info,
                                    expm_cold=_measure(lambda: expm(dt * law.Q), repeats),
                                    uniformization_cold=_measure(lambda: uniformized_transition(law.Q, dt), repeats)))
            law.transition(dt)
            uniform.transition(dt)
            for batch in (1, 64):
                p = rng.dirichlet(np.ones(40), size=batch)
                propagation.append(dict(dt=dt, batch=batch, belief_nbytes=int(p.nbytes),
                                        output_nbytes=int(p.nbytes),
                                        expm_cached=_measure(lambda: p @ law.transition(dt), repeats, propagation_iterations),
                                        uniformization_cached=_measure(lambda: p @ uniform.transition(dt), repeats, propagation_iterations)))
        memoryless = make_memoryless(law)
        memoryless_prior = law.prior
        recovery = dict(mean=2 / law.recovery_rate,
                        erlang_identity=law.identity, memoryless_identity=memoryless.identity,
                        active_row_max_difference=float(np.max(np.abs(law.Q[:32] - memoryless.Q[:32]))),
                        restored_identity_matches=Law.from_payload(memoryless.export()).identity == memoryless.identity,
                        event_metrics=[dict(dt=dt, erlang_first=float(law.first_hit(memoryless_prior, dt)),
                                            memoryless_first=float(memoryless.first_hit(memoryless_prior, dt)),
                                            erlang_count=float(law.event_count(memoryless_prior, dt)),
                                            memoryless_count=float(memoryless.event_count(memoryless_prior, dt)))
                                       for dt in (.5, 2., 10.)],
                        history_sensitivity=_sensitivity(law, memoryless))
        storage = dict(generator_nbytes=int(law.Q.nbytes), four_address_state_nbytes=4 * 40 * 8,
                       emissions_nbytes=int(law.E_read.nbytes + law.E_refresh.nbytes),
                       six_duration_cache_nbytes=6 * int(law.Q.nbytes),
                       scope="Principal float64 arrays only, excluding Python objects and library workspace")
        return dict(schema="hcsn-r15-numerics-study-v1", law_identity=law.identity,
                    implementation_identity=uniform.implementation_identity,
                    environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                     platform=platform.platform(), threadpools=threadpool_info()),
                    timing_scope="Warm imported libraries; cold means no cached transition result. Per-call timings include Python call overhead.",
                    preparation=preparation, transitions=transitions,
                    cached_propagation=propagation, storage=storage, recovery=recovery,
                    wrong_negative_controls=_wrong_endpoint_controls(law),
                    limitations=["Financial valuation and CTMC state propagation are different tasks.",
                                 "Law construction currently includes inherited R12 financial-value derivatives; timings are implementation-specific.",
                                 "Uniformization compares the identical finite Q, not continuum accuracy.",
                                 "Memoryless changes the recovery-time distribution; equal mean does not equal conditional residual lifetime.",
                                 "No energy, GPU, native Rust, network or deployment throughput is measured."])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--propagation-iterations", type=int, default=500)
    args = parser.parse_args()
    result = run_study(repeats=args.repeats, propagation_iterations=args.propagation_iterations)
    encoded = json.dumps(result, indent=2, allow_nan=False)
    if args.output is None:
        print(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")


if __name__ == "__main__":
    main()
