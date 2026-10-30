"""Run bounded, reproducible dynamics checks without model training.

Usage: OPENBLAS_NUM_THREADS=1 python run_validation.py
Artifacts are written next to this script. Every reported measurement comes
from the fixed protocols below; failures are retained in the JSON.
"""

import hashlib
import json
import os
from pathlib import Path
import platform
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/hcsn_dynamics_matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy
from scipy.linalg import expm
from scipy.signal import find_peaks

from gradient_check import run_checks
from model import Parameters, bounds, contraction_certificate, equilibria, fixed_step, gates, jacobian, reference, upward_crossings

HERE = Path(__file__).resolve().parent
P = Parameters()
ZERO = np.zeros((1, 1))


def response_summary(t, states, start):
    q = gates(states[:, 0])[0]
    mask = t >= start
    peaks, _ = find_peaks(q[mask], prominence=.02)
    peak_times = t[mask][peaks]
    span = float(np.ptp(q[mask]))
    label = "steady" if span < 1e-5 else "oscillatory" if len(peaks) >= 3 else "transient_or_unresolved"
    return dict(classification=label, late_q_range=[float(q[mask].min()), float(q[mask].max())],
                late_q_span=span, detected_peaks=int(len(peaks)),
                mean_interval=float(np.diff(peak_times).mean()) if len(peaks)>1 else None,
                upward_boundary_crossings=upward_crossings(t, states[:, 0]),
                max_abs_state=float(np.abs(states).max()))


def scan_parameters():
    rows = []
    for g in [2., 4., 6.]:
        for h in [4., 6.]:
            for tau in [2., 5.]:
                for current in [-.2, 0., 1., 2.]:
                    p = Parameters(regen_gain=g, recovery_gain=h, recovery_time=tau)
                    initial = np.array([-.5, 1.5])
                    t, state = reference(initial, p, ZERO, lambda t, i=current: i, 150., sample=.1)
                    limit = bounds(initial, p, ZERO, abs(current))
                    eqs = equilibria(current, p)
                    eig = [np.linalg.eigvals(jacobian(eq, p, ZERO)) for eq in eqs]
                    item = dict(parameters=p.__dict__, current=current,
                                continuous_bound=limit.tolist(),
                                maximum_bound_fraction=float(np.max(np.abs(state)/limit)),
                                equilibria=[dict(state=s.tolist(), max_real_eigenvalue=float(e.real.max()))
                                            for s, e in zip(eqs, eig)],
                                **response_summary(t, state, 100.))
                    item["bounded_check_passed"] = bool(np.all(np.isfinite(state)) and item["maximum_bound_fraction"] <= 1+1e-9)
                    if item["classification"] == "transient_or_unresolved":
                        tx, sx = reference(state[-1], p, ZERO, lambda t, i=current: i, 350., sample=.1)
                        item["targeted_extension"] = dict(total_time=500., **response_summary(tx+150, sx, 450.))
                    rows.append(item)
    return {"protocol": "48 fixed configurations; last 50 of 150 time units classify behavior", "runs": rows,
            "class_counts": {label: sum(x["classification"]==label for x in rows)
                             for label in ["steady", "oscillatory", "transient_or_unresolved"]},
            "final_class_counts": {label: sum(x.get("targeted_extension", x)["classification"]==label for x in rows)
                                   for label in ["steady", "oscillatory", "transient_or_unresolved"]},
            "all_bounds_passed": all(x["bounded_check_passed"] for x in rows)}


def paired_pulses():
    initial = equilibria(-.2, P)[0]
    pulse = lambda t, center: np.exp(-.5*((t-center)/.5)**2)
    t, single = reference(initial, P, ZERO, lambda t: -.2+pulse(t, 10), 100.)
    baseline_q = float(gates(initial[0])[0])
    qsingle = gates(single[:, 0])[0]
    matched_window = (t>=10) & (t<=24)
    single_area = np.trapezoid(np.maximum(qsingle[matched_window]-baseline_q, 0), t[matched_window])
    data = []
    trajectories = {}
    for gap in [.5, 1., 2., 4., 8., 16., 32.]:
        fn = lambda t, gap=gap: -.2+pulse(t, 10)+pulse(t, 10+gap)
        _, state = reference(initial, P, ZERO, fn, 100.)
        q = gates(state[:, 0])[0]
        window = (t >= 10+gap) & (t <= 24+gap)
        incremental_area = np.trapezoid(np.maximum(q[window]-qsingle[window], 0), t[window])
        item = dict(gap=gap, total_upward_crossings=upward_crossings(t, state[:, 0]),
                    second_window_incremental_positive_q_area=float(incremental_area),
                    incremental_area_over_isolated=float(incremental_area/single_area),
                    second_window_max_x=float(state[window, 0].max()),
                    final_distance_to_rest=float(np.linalg.norm(state[-1]-initial)))
        data.append(item)
        if gap in [1., 4., 16., 32.]:
            trajectories[str(gap)] = state[:, 0]
    return dict(protocol="Two equal unit Gaussian pulses, width .5, first center 10; compare with single-pulse counterfactual; integrate both numerator and denominator over matched 14-unit windows starting at pulse center",
                isolated_positive_q_area=float(single_area), runs=data,
                interpretation="Merged responses and relative recovery can be measured; no hard absolute refractory state is implemented"), (t, single[:, 0], trajectories)


def sustained_input():
    initial = equilibria(-.2, P)[0]
    rows, trajectories = [], {}
    for current in [.3, .7, 1., 2., 4.]:
        fn = lambda t, current=current: -.2 if t < 10 else current
        t, state = reference(initial, P, ZERO, fn, 150., sample=.05)
        q = gates(state[:, 0])[0]
        early = (t>=10) & (t<40)
        late = t>=100
        idx, _ = find_peaks(q, prominence=.02)
        peak_times = t[idx]
        peak_times = peak_times[peak_times>10]
        intervals = np.diff(peak_times)
        late_peak_times = peak_times[peak_times>100]
        late_intervals = np.diff(late_peak_times)
        item = dict(current=current, **response_summary(t, state, 100.),
                    early_max_q=float(q[early].max()), late_mean_q=float(q[late].mean()),
                    late_mean_over_early_max=float(q[late].mean()/q[early].max()),
                    first_three_intervals=intervals[:3].tolist(),
                    last_three_intervals=intervals[-3:].tolist(),
                    late_interval_cv=float(late_intervals.std()/late_intervals.mean()) if len(late_intervals)>1 else None)
        rows.append(item)
        if item["classification"] == "transient_or_unresolved":
            tx, sx = reference(state[-1], P, ZERO, lambda t, i=current: i, 350., sample=.1)
            item["targeted_extension"] = dict(total_time=500., **response_summary(tx+150, sx, 450.))
        if current in [.3, 1., 4.]:
            trajectories[str(current)] = q
    return dict(protocol="Step from -0.2 to constant current at t=10; retain transients and late behavior",
                runs=rows, limitation="A plateau or tonic periodic response is not evidence for indefinite spike-frequency adaptation"), (t, trajectories)


def coupled_units():
    rng = np.random.default_rng(20261029)
    n = 8
    _, orbit = reference(np.array([.1, 3.]), P, ZERO, lambda t: 1., 100., sample=.05)
    phase_idx = np.rint((80+np.arange(n)*10.775/n)/.05).astype(int)
    initial = np.concatenate((orbit[phase_idx, 0], orbit[phase_idx, 1]))
    ring = np.roll(np.eye(n), 1, axis=1)
    mixed = rng.normal(size=(n, n))
    mixed = mixed/np.sum(np.abs(mixed), axis=1, keepdims=True)*4.
    setups = [("uncoupled", np.zeros((n, n)), np.ones(n)),
              ("diffusive_ring_0.25", .25*(ring-np.eye(n)), np.ones(n)),
              ("diffusive_ring_1", ring-np.eye(n), np.ones(n)),
              ("diffusive_ring_4", 4*(ring-np.eye(n)), np.ones(n)),
              ("excitatory_ring_4", 4*ring, np.ones(n)),
              ("mixed_signed_row_l1_4", mixed, np.ones(n)),
              ("heterogeneous_diffusive_ring", 2*(ring-np.eye(n)), rng.uniform(.85, 1.15, n))]
    rows, tracks = [], {}
    perturbation = rng.normal(size=2*n)
    perturbation *= 1e-6/np.linalg.norm(perturbation)
    for name, w, current in setups:
        t, state = reference(initial, P, w, lambda t, u=current: u, 160., sample=.1)
        _, nearby = reference(initial+perturbation, P, w, lambda t, u=current: u, 160., sample=.1)
        q = gates(state[:, :n])[0]
        late = t>=110
        active = q[late].std(axis=0)>1e-6
        correlation = np.corrcoef(q[late, :][:, active].T) if np.sum(active)>1 else None
        offdiag = correlation[~np.eye(len(correlation), dtype=bool)] if correlation is not None else None
        bound = bounds(initial, P, w, np.abs(current))
        gain = np.linalg.norm(nearby-state, axis=1)/np.linalg.norm(perturbation)
        item = dict(name=name, units=n, row_absolute_sums=np.sum(np.abs(w), axis=1).tolist(),
                    current=current.tolist(), maximum_bound_fraction=float(np.max(np.abs(state)/bound)),
                    late_mean_between_unit_std=float(np.std(q[late], axis=1).mean()),
                    late_mean_within_unit_std=float(np.std(q[late], axis=0).mean()),
                    late_mean_offdiagonal_correlation=float(offdiag.mean()) if offdiag is not None else None,
                    finite_perturbation_max_gain=float(gain.max()),
                    finite_perturbation_final_gain=float(gain[-1]),
                    bounded_check_passed=bool(np.all(np.isfinite(state)) and np.max(np.abs(state)/bound)<=1+1e-8))
        rows.append(item)
        if name in ["uncoupled", "diffusive_ring_1", "excitatory_ring_4"]:
            tracks[name] = q
    return dict(seed=20261029, initial="Eight phases on the isolated periodic orbit",
                coupling="W @ (q(x)-0.5); diffusion uses W=k(P-I)",
                perturbation_note="Finite 1e-6 perturbation, not a proof of asymptotic contraction",
                runs=rows, all_bounds_passed=all(x["bounded_check_passed"] for x in rows)), (t, tracks)


def numerical_accuracy():
    initial = equilibria(-.2, P)[0]
    fn = lambda t: -.2+np.exp(-.5*((t-10)/.5)**2)
    tr, ref = reference(initial, P, ZERO, fn, 40., sample=.005, tight=True)
    rows = []
    for dtype in [np.float64, np.float32]:
        for method in ["euler", "exponential", "rk4"]:
            previous = None
            for dt in [.2, .1, .05, .025]:
                t, state = fixed_step(initial, P, ZERO, fn, 40., dt, method, dtype)
                target = ref[np.rint(t/.005).astype(int)]
                error = float(np.max(np.abs(state-target)))
                item = dict(dtype=np.dtype(dtype).name, method=method, dt=dt,
                            max_abs_state_error=error,
                            empirical_halving_order=float(np.log2(previous/error)) if previous else None,
                            actual_trajectory_dtype=str(state.dtype),
                            final_state_error=float(np.linalg.norm(state[-1]-target[-1])))
                rows.append(item)
                previous = error
    large_step = []
    stress_initial = np.array([.1, 3.])
    limit = bounds(stress_initial, P, ZERO, 1.)
    for dt in [1., 2., 4.]:
        for method in ["euler", "exponential"]:
            t, state = fixed_step(stress_initial, P, ZERO, lambda t: 1., 80., dt, method)
            large_step.append(dict(dt=dt, method=method, maximum_bound_fraction=float(np.max(np.abs(state)/limit)),
                                   max_abs_state=float(np.abs(state).max()), all_finite=bool(np.all(np.isfinite(state)))))
    return dict(reference="DOP853 rtol=1e-11 atol=1e-13 max_step=.025, sample=.005",
                runs=rows, large_step_stress=large_step,
                stress_protocol="Constant I=1, initial (.1,3), duration80; avoids missing a narrow pulse on a coarse grid",
                exponential_note="Frozen forcing exponential Euler: invariant bounds do not mean accurate dynamics at large dt")


def tangent_counterexample():
    stable = equilibria(-.2, P)[0]
    unstable = np.array([0., 3.])
    rows = []
    for name, state in [("stable_rest_I_minus_0.2", stable), ("unstable_equilibrium_I_1", unstable)]:
        j = jacobian(state, P, ZERO)
        rows.append(dict(name=name, state=state.tolist(), jacobian=j.tolist(),
                         eigenvalues=[str(x) for x in np.linalg.eigvals(j)],
                         tangent_norms={str(t): float(np.linalg.norm(expm(j*t), 2)) for t in [1, 10, 50, 100]}))
    return dict(interpretation="Exact tangent flow at equilibria proves state boundedness does not bound long-horizon sensitivities",
                runs=rows)


def certified_stable_variant():
    p = Parameters(leak=6.)
    n = 8
    w = .25*(np.roll(np.eye(n), 1, axis=1)-np.eye(n))
    certificate = contraction_certificate(p, w, .3)
    rng = np.random.default_rng(708)
    initial = rng.uniform(-2, 2, 2*n)
    other = initial+rng.normal(size=2*n)
    t, first = reference(initial, p, w, lambda t: np.ones(n), 100., sample=.1)
    _, second = reference(other, p, w, lambda t: np.ones(n), 100., sample=.1)
    scale = np.concatenate((np.ones(n), np.full(n, certificate["weight"])))
    distance = np.max(np.abs(first-second)*scale, axis=1)
    envelope = distance[0]*np.exp(-certificate["contraction_rate"]*t)
    return dict(parameters=p.__dict__, certificate=certificate,
                initial_distance=float(distance[0]), final_distance=float(distance[-1]),
                maximum_distance_over_certified_envelope=float(np.max(distance/envelope)),
                passed=bool(certificate["certified"] and np.all(distance <= envelope+1e-9)),
                tradeoff="This globally contracting regime cannot preserve autonomous tonic oscillations under constant input; representation quality is untested")


def create_figure(paired, sustained, coupled, accuracy):
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.3), constrained_layout=True)
    t, single, tracks = paired
    ax = axes[0, 0]
    ax.plot(t, single, color="black", ls="--", label="Single pulse")
    for name in ["1.0", "4.0", "16.0"]:
        ax.plot(t, tracks[name], label=f"Gap {name}")
    ax.axhline(0, color="grey", ls=":")
    ax.set(xlim=(5, 45), title="Paired pulses: relative recovery", xlabel="Time", ylabel="Danger coordinate x")
    ax.legend(fontsize=8)
    t, tracks = sustained
    ax = axes[0, 1]
    for name, q in tracks.items():
        ax.plot(t, q, label=f"I = {name}")
    ax.set(title="Sustained input: tonic / plateau responses", xlabel="Time", ylabel="Put activation q")
    ax.legend(fontsize=8)
    ax = axes[0, 2]
    for method in ["euler", "exponential", "rk4"]:
        selected = [r for r in accuracy["runs"] if r["dtype"]=="float64" and r["method"]==method]
        ax.loglog([r["dt"] for r in selected], [r["max_abs_state_error"] for r in selected], "o-", label=method)
    ax.set(title="Step refinement against DOP853", xlabel="Step size", ylabel="Maximum state error")
    ax.legend(fontsize=8)
    t, tracks = coupled
    for ax, name in zip(axes[1], ["uncoupled", "diffusive_ring_1", "excitatory_ring_4"]):
        mask=t>=110
        ax.plot(t[mask], tracks[name][mask], lw=.9, alpha=.8)
        ax.set(title=name.replace("_", " "), xlabel="Time", ylabel="Eight activations q")
    for ax in axes.flat:
        ax.grid(alpha=.2)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("HCSN dynamics validation: measurements and explicit failure cases", fontsize=16)
    fig.savefig(HERE/"dynamics_validation.png", dpi=160)
    plt.close(fig)


def main():
    started = time.perf_counter()
    results = dict(scope="Dynamical validity and gradient checks, not representation-learning or energy benchmarks",
                   environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                    platform=platform.platform(), openblas_threads=os.environ.get("OPENBLAS_NUM_THREADS")),
                   source_hashes={name: hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                                  for name in ["model.py", "gradient_check.py", "run_validation.py"]})
    results["parameter_scan"] = scan_parameters()
    print("parameter_scan", results["parameter_scan"]["class_counts"], flush=True)
    results["paired_pulses"], paired = paired_pulses()
    print("paired_pulses complete", flush=True)
    results["sustained_input"], sustained = sustained_input()
    results["coupled_units"], coupled = coupled_units()
    print("coupled_units complete", flush=True)
    results["numerical_accuracy"] = numerical_accuracy()
    results["tangent_counterexample"] = tangent_counterexample()
    results["certified_stable_variant"] = certified_stable_variant()
    results["gradients"] = run_checks()
    results["wall_seconds"] = time.perf_counter()-started
    results["validation_passed"] = (results["parameter_scan"]["all_bounds_passed"]
                                     and results["coupled_units"]["all_bounds_passed"]
                                     and results["gradients"]["all_passed"]
                                     and results["certified_stable_variant"]["passed"])
    (HERE/"dynamics_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    create_figure(paired, sustained, coupled, results["numerical_accuracy"])
    print(json.dumps(dict(validation_passed=results["validation_passed"], wall_seconds=results["wall_seconds"],
                         worst_gradient_error=max(r["max_absolute_gradient_error"] for r in results["gradients"]["runs"])), indent=2))
    if not results["validation_passed"]:
        raise SystemExit("One or more explicit validation checks failed; see dynamics_results.json")


if __name__ == "__main__":
    main()
