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
    checks = {
        "quiet_rate_below_1e-8": rest_max < 1e-8,
        "pulse_peak_above_1": min(peak_a,peak_b) > 1.,
        "repeat_peak_relative_error_below_1_percent": abs(peak_a-peak_b)/peak_a < .01,
        "late_quiet_rate_below_1e-8": return_max < 1e-8,
        "no_event_before_refractory_release": max(refractory_rates) == 0.,
        "sustained_finite_nonzero_rate": bool(np.all(np.isfinite(sustained["rate"])) and sustained["rate"][-100:].mean() > .01),
        "mass_error_below_1e-10": mass_error < 1e-10,
        "tested_coupling_finite_and_mass_conserving": bool(np.isfinite(pair_rate).all() and np.max(np.abs(coupled["mass_error"])) < 1e-10),
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
                    "interpretation":"bounded tested response; synchrony and bifurcation require parameter sweeps"},
        "mass":{"maximum_absolute_conservation_error":mass_error,
                "maximum_escaped_mass":max(float(t["escaped"].max()) for t in (traces,sustained,coupled))},
        "joint_grid_time_refinement":refinements,
        "refinement_scope":"constant Brownian drift, refractory longer than observation; independent first-event CDF target",
        "limits":["Fixed boundary only; time-varying drift is frozen during each step.",
                  "Refractory length is rounded up to a multiple of dt; reset occurs at step end.",
                  "Escaped upper-grid mass stays in a cemetery account; excessive escape invalidates a run.",
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
