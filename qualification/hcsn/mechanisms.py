"""Finite-horizon mechanism probes, not bifurcation or global-optimality claims."""

from dataclasses import asdict, replace
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import numpy as np
import scipy
from scipy.special import ndtr
from .population import Population, PopulationConfig


def simulate(config, drives, coupling_strength=0.0):
    """drives shape (time, population); coupling exchanges prior-step rates."""
    model = Population(config)
    state = model.initial_state(drives.shape[1:])
    last_rate = np.zeros(drives.shape[1:])
    records = {k: [] for k in ("rate", "recovery", "escaped", "mass_error")}
    for drive in drives:
        coupling = coupling_strength * last_rate[::-1] if coupling_strength else 0.0
        step = model.step(state, drive, coupling)
        state, last_rate = step.state, step.rate
        for key, value in (("rate", last_rate), ("recovery", state.recovery),
                           ("escaped", state.escaped), ("mass_error", state.total_mass()-1)):
            records[key].append(np.asarray(value).copy())
    return {k: np.array(v) for k, v in records.items()}


def rate_pair_statistics(rates, dt, max_lag_steps, *, atol=1e-10, rtol=1e-6):
    """Descriptive overlap-centered Pearson correlations, never significance tests.

    Positive lag k correlates unit 0 at t with unit 1 at t+k: unit 0 leads.
    Near-constant tails are unidentified, not reported as zero correlation.
    """
    rates = np.asarray(rates, dtype=np.float64)
    if rates.ndim != 2 or rates.shape[1] != 2 or len(rates) < 3:
        raise ValueError("rates must have shape (at least 3 time samples, 2)")
    if not isinstance(max_lag_steps, int) or not 0 <= max_lag_steps <= len(rates)-3:
        raise ValueError("lag range must retain at least three overlapping samples")
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("dt must be finite and positive")
    finite = bool(np.isfinite(rates).all())
    result = {"samples": len(rates), "all_finite": finite, "std_ddof": 0,
              "mean_rate": None, "std_rate": None, "peak_rate": None,
              "peak_to_peak_rate": None, "near_constant_std_threshold": None,
              "zero_lag_correlation": None, "zero_lag_missing_reason": None,
              "max_cross_correlation": None, "max_cross_correlation_lag_steps": None,
              "max_cross_correlation_lag_time": None, "max_cross_correlation_overlap": None,
              "max_absolute_cross_correlation": None, "max_absolute_cross_correlation_lag_steps": None,
              "cross_correlation_missing_reason": None}
    if not finite:
        result.update(zero_lag_missing_reason="nonfinite_rate_series",
                      cross_correlation_missing_reason="nonfinite_rate_series")
        return result
    mean, std = rates.mean(0), rates.std(0, ddof=0)
    threshold = atol + rtol*np.maximum(1., np.max(np.abs(rates), axis=0))
    result.update(mean_rate=mean.tolist(), std_rate=std.tolist(),
                  peak_rate=rates.max(0).tolist(), peak_to_peak_rate=np.ptp(rates, axis=0).tolist(),
                  near_constant_std_threshold=threshold.tolist())
    if np.any(std <= threshold):
        reason = "near_constant_series_" + "_".join(map(str, np.flatnonzero(std <= threshold)))
        result.update(zero_lag_missing_reason=reason, cross_correlation_missing_reason=reason)
        return result
    candidates = []
    for lag in range(-max_lag_steps, max_lag_steps+1):
        if lag > 0:
            pair = np.column_stack((rates[:-lag, 0], rates[lag:, 1]))
        elif lag < 0:
            pair = np.column_stack((rates[-lag:, 0], rates[:lag, 1]))
        else:
            pair = rates
        centered = pair - pair.mean(0)
        norms = np.linalg.norm(centered, axis=0)
        if np.any(norms/np.sqrt(len(pair)) <= threshold):
            continue
        correlation = float(np.clip(np.dot(centered[:, 0]/norms[0],
                                            centered[:, 1]/norms[1]), -1., 1.))
        candidates.append((correlation, lag, len(pair)))
        if lag == 0:
            result["zero_lag_correlation"] = correlation
    if result["zero_lag_correlation"] is None:
        result["zero_lag_missing_reason"] = "near_constant_zero_lag_overlap"
    if not candidates:
        result["cross_correlation_missing_reason"] = "near_constant_all_lag_overlaps"
        return result
    best = max(candidates, key=lambda item: (item[0], -abs(item[1]), -item[1]))
    absolute = max(candidates, key=lambda item: (abs(item[0]), -abs(item[1]), -item[1]))
    result.update(max_cross_correlation=best[0], max_cross_correlation_lag_steps=best[1],
                  max_cross_correlation_lag_time=best[1]*dt, max_cross_correlation_overlap=best[2],
                  max_absolute_cross_correlation=absolute[0],
                  max_absolute_cross_correlation_lag_steps=absolute[1])
    return result


def coupling_scan(config, *, strengths=(0., .08, .3, .8), seed=20261105,
                  steps=800, tail_steps=400, max_lag_steps=50):
    """Heterogeneous two-unit scan with shared draws across coupling strengths."""
    if not (3 <= tail_steps <= steps and 0 <= max_lag_steps <= tail_steps-3):
        raise ValueError("Invalid observation window or lag range")
    if not strengths or not all(np.isfinite(s) and s >= 0 for s in strengths):
        raise ValueError("Coupling strengths must be finite and nonnegative")
    configs = (config, replace(config, sigma=1.15*config.sigma,
                              rest_margin=1.1*config.rest_margin, reset_margin=1.1*config.reset_margin))
    tonic, noise_std = np.array([3.8, 4.0]), .04
    rng = np.random.default_rng(seed)
    drives = tonic + rng.normal(0., noise_std, (steps, 2))
    delayed_steps = min(round(.4/config.dt), steps)
    drives[:delayed_steps, 1] = 0.
    records = []
    for strength in strengths:
        models = [Population(c) for c in configs]
        states = [model.initial_state() for model in models]
        previous = np.zeros(2)
        rates, masses, escaped = [], [], []
        for drive in drives:
            # Both outputs use the same previous-step rates, so the coupling
            # update order does not give either unit a same-step advantage.
            outputs = [models[i].step(states[i], drive[i], strength*previous[1-i]) for i in range(2)]
            states = [output.state for output in outputs]
            previous = np.array([float(output.rate) for output in outputs])
            rates.append(previous)
            masses.append([float(state.total_mass()-1) for state in states])
            escaped.append([float(state.escaped) for state in states])
        rates, masses, escaped = np.asarray(rates), np.asarray(masses), np.asarray(escaped)
        finite = bool(all(np.isfinite(v).all() for v in (rates, masses, escaped)))
        max_mass_error = float(np.abs(masses).max()) if finite else None
        max_escape = float(escaped.max()) if finite else None
        tail = rate_pair_statistics(rates[-tail_steps:], config.dt, max_lag_steps)
        records.append({"strength": float(strength), "all_finite": finite,
                        "numerically_valid": bool(finite and max_mass_error < 1e-10 and max_escape < 1e-6),
                        "maximum_absolute_mass_error": max_mass_error,
                        "maximum_escaped_mass": max_escape,
                        "maximum_rate_entire_run": rates.max(0).tolist() if finite else None,
                        "tail": tail,
                        "rate_trace_sha256": hashlib.sha256(rates.tobytes()).hexdigest()})
    return {"status": "observational", "seed": seed, "steps": steps, "dt": config.dt, "duration": steps*config.dt,
            "tail_steps": tail_steps, "tail_time_interval": [(steps-tail_steps)*config.dt, steps*config.dt],
            "tail_time_convention": "rates are interval averages; tail covers (start, end]",
            "max_lag_steps": max_lag_steps, "max_lag_time": max_lag_steps*config.dt,
            "lag_convention": "positive k compares rate_0[t] with rate_1[t+k]; unit 0 leads unit 1",
            "initial_condition": {"active": "linear centre deposition at each unit's rest_margin",
                                  "refractory_mass": [0., 0.], "recovery": [0., 0.], "escaped_mass": [0., 0.]},
            "unit_configs": [asdict(c) for c in configs], "tonic_drives": tonic.tolist(),
            "drive_perturbation": {"distribution": "independent Gaussian draws across units and steps",
                                   "standard_deviation": noise_std, "same_draws_across_strengths": True,
                                   "unit_1_zero_drive_initial_steps": delayed_steps,
                                   "drive_sha256": hashlib.sha256(drives.tobytes()).hexdigest()},
            "coupling_rule": "drive_i += strength * rate_other from the preceding step",
            "finite_rate_cap_from_one_event_per_step": 1/config.dt,
            "records": records,
            "interpretation": "Descriptive finite-horizon correlations and amplitude observations, not a test of global stability or a phase transition. A finite rate is also constrained by the time grid and does not rule out harmful synchrony. Correlations describe population-rate cofluctuation, not paired microscopic spike coincidence. Maximum cross correlation selects over lags and can select periodic aliases; the maximizing lag is not a causal conduction delay. No significance claim is attached, and synchrony is not a pass/fail gate."}


def run_mechanisms():
    started = time.perf_counter()
    cfg = PopulationConfig()
    drives = np.zeros((420, 1))
    drives[50:75] = drives[250:275] = 4.5
    traces = simulate(cfg, drives)
    rates = traces["rate"][:, 0]
    peak_a, peak_b = float(rates[50:100].max()), float(rates[250:300].max())
    rest_max, return_max = float(rates[:50].max()), float(rates[-50:].max())
    sustained = simulate(cfg, np.full((600, 1), 3.8))
    no_recovery = simulate(replace(cfg, recovery_strength=0.), np.full((600, 1), 3.8))
    no_refractory = simulate(replace(cfg, refractory=0.), np.full((600, 1), 3.8))
    pair_drive = np.full((600, 2), 3.8)
    pair_drive[0:20, 1] = 0.
    coupled = simulate(cfg, pair_drive, coupling_strength=.08)
    uncoupled = simulate(cfg, pair_drive)
    pair_rate = coupled["rate"]
    scan = coupling_scan(cfg)

    # Start entirely refractory to isolate exact queue timing from spread in
    # firing times. Release is after propagation, so no early event is possible.
    model = Population(cfg)
    state = model.initial_state()
    from .population import PopulationState
    queue = np.zeros(cfg.refractory_steps)
    queue[-1] = 1.0
    state = PopulationState(np.zeros(cfg.bins), queue, np.array(0.), np.array(0.))
    refractory_rates = []
    for _ in range(cfg.refractory_steps):
        out = model.step(state, drive=100.)
        state = out.state
        refractory_rates.append(float(out.rate))

    # Projection convergence requires dx^2 / dt -> 0. Merely decreasing dt at a
    # fixed grid can increase centre-projection diffusion and is not advertised
    # as convergence. Constant-drift absorption has an independent exact target.
    x, mu, sigma, horizon = .45, -.25, .35, 1.2
    scale = sigma*np.sqrt(horizon)
    exact = float(ndtr((-x-mu*horizon)/scale)+np.exp(-2*mu*x/sigma**2)*ndtr((-x+mu*horizon)/scale))
    refinements = []
    for bins, dt in ((48, .04), (96, .02), (192, .01)):
        c = PopulationConfig(bins=bins, x_max=2.4, dt=dt, sigma=sigma,
                             rest_margin=x, reset_margin=x, leak=0., base_drift=mu,
                             refractory=2., recovery_strength=0.)
        obs = simulate(c, np.zeros((round(horizon/dt), 1)))
        empirical = float(obs["rate"].sum()*dt)
        refinements.append({"bins":bins,"dt":dt,"dx_squared_over_dt":(c.x_max/bins)**2/dt,
                            "absorbed_mass":empirical,"exact_absorbed_mass":exact,
                            "absolute_error":abs(empirical-exact)})
    mass_error = max(float(np.abs(t["mass_error"]).max()) for t in
                     (traces, sustained, no_recovery, no_refractory, coupled, uncoupled))
    mass_error = max([mass_error] + [row["maximum_absolute_mass_error"] for row in scan["records"]
                                   if row["maximum_absolute_mass_error"] is not None])
    checks = {
        "quiet_rate_below_1e-8": rest_max < 1e-8,
        "pulse_peak_above_1": min(peak_a,peak_b) > 1.,
        "repeat_peak_relative_error_below_1_percent": abs(peak_a-peak_b)/peak_a < .01,
        "late_quiet_rate_below_1e-8": return_max < 1e-8,
        "no_event_before_refractory_release": max(refractory_rates) == 0.,
        "sustained_finite_nonzero_rate": bool(np.all(np.isfinite(sustained["rate"])) and sustained["rate"][-100:].mean() > .01),
        "mass_error_below_1e-10": mass_error < 1e-10,
        "tested_coupling_finite_and_mass_conserving": bool(np.isfinite(pair_rate).all() and np.max(np.abs(coupled["mass_error"])) < 1e-10),
        "coupling_scan_numerically_valid": all(row["numerically_valid"] for row in scan["records"]),
        "joint_refinement_error_decreases": refinements[2]["absolute_error"] < refinements[1]["absolute_error"] < refinements[0]["absolute_error"],
    }
    paths = [Path(__file__), Path(__file__).with_name("population.py")]
    return {
        "schema":"hcsn-population-mechanisms-v1", "status":"passed" if all(checks.values()) else "failed",
        "scope":"deterministic population-law finite-horizon probes; no trained-model quality claim",
        "source_files_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "runtime":{"python":sys.version.split()[0],"numpy":np.__version__,"scipy":scipy.__version__,"platform":platform.platform()},
        "config":asdict(cfg),"effective_refractory":cfg.effective_refractory,
        "resting":{"duration":1.,"maximum_rate":rest_max,"noise_is_nonzero":True},
        "repeated_pulses":{"peak_rates":[peak_a,peak_b],"relative_peak_difference":abs(peak_a-peak_b)/peak_a,
                           "late_rate_maximum":return_max,"final_recovery":float(traces["recovery"][-1,0])},
        "refractory":{"steps":cfg.refractory_steps,"maximum_rate_before_release":max(refractory_rates),
                      "timing":"event at interval n end; release at n+m end; next possible flux in interval n+m+1"},
        "sustained":{"duration":600*cfg.dt,"last_window_mean_rate":float(sustained["rate"][-100:].mean()),
                     "last_window_peak_to_peak":float(np.ptp(sustained["rate"][-100:])),
                     "without_recovery_mean_rate":float(no_recovery["rate"][-100:].mean()),
                     "without_refractory_mean_rate":float(no_refractory["rate"][-100:].mean())},
        "coupling":{"strength":.08,"maximum_rate":float(pair_rate.max()),
                    "tail_mean_rate":pair_rate[-100:].mean(0).tolist(),
                    "uncoupled_tail_mean_rate":uncoupled["rate"][-100:].mean(0).tolist(),
                    "transient_rate_correlation":float(np.corrcoef(pair_rate[:200].T)[0,1]),
                    "interpretation":"legacy single-strength homogeneous probe; heterogeneous lagged correlations are reported in coupling_scan"},
        "coupling_scan":scan,
        "mass":{"maximum_absolute_conservation_error":mass_error,
                "maximum_escaped_mass":max([float(t["escaped"].max()) for t in (traces,sustained,coupled)] +
                                           [row["maximum_escaped_mass"] for row in scan["records"]
                                            if row["maximum_escaped_mass"] is not None])},
        "joint_grid_time_refinement":refinements,
        "refinement_scope":"constant Brownian drift, refractory longer than observation; independent first-event CDF target",
        "limits":["Fixed boundary only; time-varying drift is frozen during each step.",
                  "Refractory length is rounded up to a multiple of dt; reset occurs at step end.",
                  "Escaped upper-grid mass stays in a cemetery account; excessive escape invalidates a run.",
                  "Coupling correlations are descriptive finite-window statistics, not a no-synchrony guarantee or bifurcation test.",
                  "A finite-horizon pass is not proof of global stability, phase transition, bifurcation or task superiority."],
        "checks":checks,"elapsed_seconds":time.perf_counter()-started,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_mechanisms()
    encoded = json.dumps(report, indent=2, allow_nan=False)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded)
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
