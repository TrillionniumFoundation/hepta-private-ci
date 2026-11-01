"""Independent simplified continuous C1 dynamics; not the frozen financial kernel."""
import cmath
import gzip
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
B, ALPHA, K, BETA, D = 1.0, 1.7, 0.1, 0.1, 0.1
VSTAR, XSTAR = 2.0, math.log(2.0)
T, WARM = 800.0, 400.0
STEPS = (0.04, 0.02, 0.01, 0.005)
GAMMAS = (0.2, 0.8)

def observables(x):
    if x <= 0.0:
        return 0.0, 1.0
    f = math.exp(-ALPHA * x)
    survival = -math.expm1(-ALPHA * x)
    return math.expm1(x) - survival / ALPHA, f * (2.0 - f)

ESTAR, RSTAR = observables(XSTAR)
ISTAR = K * ESTAR - D * RSTAR
FSTAR = math.exp(-ALPHA * XSTAR)
EX = math.exp(XSTAR) - FSTAR
RX = -2.0 * ALPHA * FSTAR * (1.0 - FSTAR)
GC = (K * EX + BETA) / (-RX)
DET = BETA * (K * EX - D * RX)

def rhs(x, a, gamma):
    e, r = observables(x)
    return ISTAR - K * e - gamma * r + a, BETA * ((gamma + D) * r - a)

def rk4(gamma, h):
    n = round(T / h)
    states = np.empty((n + 1, 2), dtype=np.float64)
    x, a = XSTAR + 0.05, (gamma + D) * RSTAR
    states[0] = x, a
    for i in range(n):
        u1, v1 = rhs(x, a, gamma)
        u2, v2 = rhs(x + h * u1 / 2, a + h * v1 / 2, gamma)
        u3, v3 = rhs(x + h * u2 / 2, a + h * v2 / 2, gamma)
        u4, v4 = rhs(x + h * u3, a + h * v3, gamma)
        x += h * (u1 + 2 * u2 + 2 * u3 + u4) / 6
        a += h * (v1 + 2 * v2 + 2 * v3 + v4) / 6
        if not (math.isfinite(x) and math.isfinite(a)):
            raise RuntimeError(f"Nonfinite trajectory at gamma={gamma}, h={h}, step={i}")
        states[i + 1] = x, a
    return states

def risk_array(x):
    out = np.ones_like(x)
    positive = x > 0
    f = np.exp(-ALPHA * x[positive])
    out[positive] = f * (2 - f)
    return out

def crossings(states, h):
    x = states[:, 0]
    events = []
    down = (x[:-1] > 0) & (x[1:] <= 0)
    up = (x[:-1] <= 0) & (x[1:] > 0)
    for i in np.flatnonzero(down | up):
        at = h * (i + (-x[i]) / (x[i + 1] - x[i]))
        events.append({"time": float(at), "direction": "enter_default" if down[i] else "exit_default"})
    return events

def statistics(states, h, gamma):
    tail = states[round(WARM / h):]
    r = risk_array(tail[:, 0])
    events = crossings(states, h)
    periods = []
    widths = []
    last_start = None
    for event in events:
        if event["direction"] == "enter_default":
            if last_start is not None and last_start >= WARM:
                periods.append(event["time"] - last_start)
            last_start = event["time"]
        elif last_start is not None and last_start >= WARM:
            widths.append(event["time"] - last_start)
    starts = [e["time"] for e in events if e["direction"] == "enter_default" and e["time"] >= WARM]
    r_tail_min, r_tail_max = float(np.min(r)), float(np.max(r))
    return {
        "h": h, "steps": len(states) - 1,
        "initial_state": states[0].tolist(),
        "end_state": states[-1].tolist(),
        "end_distance_from_equilibrium": float(np.linalg.norm(states[-1] - [XSTAR, (gamma + D) * RSTAR])),
        "tail_x_range": [float(np.min(tail[:, 0])), float(np.max(tail[:, 0]))],
        "tail_a_range": [float(np.min(tail[:, 1])), float(np.max(tail[:, 1]))],
        "tail_risk_range": [r_tail_min, r_tail_max],
        "tail_default_fraction_sampled": float(np.mean(tail[:, 0] <= 0)),
        "tail_enter_default_count": len(starts),
        "tail_complete_plateau_count": len(widths),
        "periods": periods,
        "mean_period": float(np.mean(periods)) if periods else None,
        "period_std": float(np.std(periods)) if periods else None,
        "plateau_widths": widths,
        "mean_plateau_width": float(np.mean(widths)) if widths else None,
        "all_boundary_crossings": events,
        "threshold_based_readout_only": True,
        "threshold_or_reset_in_integrator": False,
    }

def linearization(gamma):
    jac = np.array([[-K * EX - gamma * RX, 1.0],
                    [BETA * (gamma + D) * RX, -BETA]])
    trace = -K * EX - gamma * RX - BETA
    root = cmath.sqrt(trace * trace - 4 * DET)
    eigen = [(trace + root) / 2, (trace - root) / 2]
    eps = 1e-6
    center = np.array([XSTAR, (gamma + D) * RSTAR])
    fd = np.column_stack([(np.array(rhs(*(center + np.eye(2)[j] * eps), gamma))
                           - np.array(rhs(*(center - np.eye(2)[j] * eps), gamma))) / (2 * eps)
                          for j in range(2)])
    return {"jacobian": jac.tolist(), "trace": trace, "determinant": DET,
            "eigenvalues": [{"real": z.real, "imag": z.imag} for z in eigen],
            "fd_jacobian_max_abs_error": float(np.max(np.abs(jac - fd)))}

def main():
    started = time.perf_counter()
    output = {
        "schema": "hcsn.simplified-c1-value-dynamics-probe.v1",
        "candidate_only": True,
        "parameters": {"b": B, "alpha": ALPHA, "k": K, "beta": BETA, "d": D, "Vstar": VSTAR,
                       "xstar": XSTAR, "Fstar": FSTAR, "Estar": ESTAR, "Rstar": RSTAR,
                       "I": ISTAR, "E_x_at_star": EX, "R_x_at_star": RX},
        "plan": {"duration": T, "tail_start": WARM, "steps": list(STEPS),
                 "gammas": list(GAMMAS), "initial_x_offset": 0.05, "initial_a": "(gamma+d)*Rstar",
                 "integrator": "classical fixed-step RK4, float64; no event stepping, clipping, threshold trigger or reset",
                 "plotting_trace_spacing": 0.1},
        "linear_crossing": {"gamma_c": GC, "determinant_at_gamma_c": DET,
                            "trace_derivative_wrt_gamma": -RX,
                            "eigen_real_derivative_wrt_gamma_at_crossing": -RX / 2,
                            "strict_hopf_theorem_proved": False},
        "runs": {},
        "scope": {
            "same_frozen_financial_candidate": False, "changed_existing_kernel_or_gate": False,
            "original_HeXiong_rollover_operator": False,
            "ODE_rhs_uses_observable_values_not_potential_derivatives": True,
            "global_C1_vector_field_for_fixed_positive_parameters": True,
            "recurrent_observable_pulses_are_not_discrete_0_1_spikes": True,
            "network_training_or_quality_test": False, "performance_or_energy_comparison": False,
            "periodic_orbit_existence_or_stability_theorem": False,
            "only_one_initial_condition_per_gamma": True,
            "boundary_crossings_are_postprocessing_only": True,
        },
    }
    finest = {}
    trace = {"time": np.arange(round(T / 0.1) + 1, dtype=float) * 0.1}
    for gamma in GAMMAS:
        trajectories = {h: rk4(gamma, h) for h in STEPS}
        data = {"linearization": linearization(gamma),
                "step_statistics": [statistics(trajectories[h], h, gamma) for h in STEPS],
                "successive_refinement": []}
        for h, half in zip(STEPS[:-1], STEPS[1:]):
            delta = np.abs(trajectories[h] - trajectories[half][::2])
            data["successive_refinement"].append({
                "coarse_h": h, "fine_h": half,
                "max_abs_x_difference": float(np.max(delta[:, 0])),
                "max_abs_a_difference": float(np.max(delta[:, 1])),
                "max_abs_risk_difference": float(np.max(np.abs(
                    risk_array(trajectories[h][:, 0]) - risk_array(trajectories[half][::2, 0])))),
            })
        output["runs"][str(gamma)] = data
        fine = trajectories[STEPS[-1]]
        finest[gamma] = fine
        sampled = fine[::round(0.1 / STEPS[-1])]
        trace[f"x_gamma_{gamma}"] = sampled[:, 0]
        trace[f"a_gamma_{gamma}"] = sampled[:, 1]
        trace[f"R_gamma_{gamma}"] = risk_array(sampled[:, 0])
    output["elapsed_integrations_and_analysis_seconds_not_a_benchmark"] = time.perf_counter() - started
    np.savez_compressed(OUT / "CONTINUOUS_TRAJECTORIES.npz", **trace)
    (OUT / "RESULTS.json").write_text(json.dumps(output, indent=2, allow_nan=False) + "\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(2, 2, figsize=(12, 7.7), constrained_layout=True)
    colors = {0.2: "#2166ac", 0.8: "#b2182b"}
    ts = trace["time"]
    for gamma in GAMMAS:
        ax[0, 0].plot(ts, trace[f"x_gamma_{gamma}"], color=colors[gamma], label=fr"$\gamma={gamma}$")
    ax[0, 0].axhline(0, color="black", lw=0.8, ls=":")
    ax[0, 0].axhline(XSTAR, color="gray", lw=0.8, ls="--")
    ax[0, 0].set(xlim=(0, 200), xlabel="Time (arbitrary units)", ylabel=r"$x=\log(V/b)$",
                 title="A. Stable equilibrium versus sustained excursion")
    ax[0, 0].legend(loc="lower left")
    for gamma in GAMMAS:
        ax[0, 1].plot(ts, trace[f"R_gamma_{gamma}"], color=colors[gamma], label=fr"$\gamma={gamma}$")
    ax[0, 1].set(xlim=(600, 800), ylim=(-0.02, 1.05), xlabel="Time (arbitrary units)",
                 ylabel=r"Continuous risk observable $R$", title="B. Repeated smooth pulses with saturated plateaus")
    for gamma in GAMMAS:
        keep = ts >= WARM if gamma == 0.8 else ts <= 200
        ax[1, 0].plot(trace[f"x_gamma_{gamma}"][keep], trace[f"a_gamma_{gamma}"][keep],
                      color=colors[gamma], label=fr"$\gamma={gamma}$")
        ax[1, 0].plot(XSTAR, (gamma + D) * RSTAR, "o", color=colors[gamma], ms=5)
    ax[1, 0].axvline(0, color="black", lw=0.8, ls=":")
    ax[1, 0].set(xlabel=r"$x$", ylabel=r"Restoring state $a$",
                 title="C. Phase portrait; boundary crossing has no reset")
    for gamma in GAMMAS:
        rows = output["runs"][str(gamma)]["successive_refinement"]
        ax[1, 1].loglog([r["coarse_h"] for r in rows],
                        [r["max_abs_x_difference"] for r in rows], "o-", color=colors[gamma],
                        label=fr"$\gamma={gamma}$")
    ax[1, 1].set(xlabel=r"Coarse step $h$ (compared with $h/2$)",
                 ylabel=r"$\max_{0\leq t\leq 800}|x_h-x_{h/2}|$",
                 title="D. Actual fixed-step convergence")
    ax[1, 1].legend()
    for panel in ax.flat:
        panel.grid(alpha=0.18)
    fig.suptitle("Simplified C1 value-field candidate — separate from the frozen financial kernel", fontsize=13)
    fig.savefig(OUT / "DYNAMICS.png", dpi=160)
    fig.savefig(OUT / "DYNAMICS.pdf")
    plt.close(fig)
    paths = ["dynamics_probe.py", "PLAN.json", "RESULTS.json", "CONTINUOUS_TRAJECTORIES.npz",
             "DYNAMICS.png", "DYNAMICS.pdf"]
    manifest = {"schema": "hcsn.simplified-c1-value-dynamics-files.v1", "files": [
        {"path": name, "bytes": (OUT/name).stat().st_size,
         "sha256": hashlib.sha256((OUT/name).read_bytes()).hexdigest()} for name in paths]}
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"results": str(OUT / "RESULTS.json"),
                      "gamma_c": GC, "runtime_seconds": output["elapsed_integrations_and_analysis_seconds_not_a_benchmark"],
                      "runs": {key: {"linearization": value["linearization"],
                                      "finest": value["step_statistics"][-1],
                                      "refinement": value["successive_refinement"]}
                               for key, value in output["runs"].items()}}, indent=2))

if __name__ == "__main__":
    main()

