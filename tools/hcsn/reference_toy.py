"""Reproducible HCSN feasibility laboratory.

This is a newly constructed toy model inspired by optimal stopping, NOT a
reproduction of the full He--Xiong rollover model and NOT a trained network.
Dependencies: Python >=3.10, NumPy, SciPy, Matplotlib. No network access needed.
Run: python hcsn_lab.py
"""
import json
import math
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir())/"hcsn_matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from scipy.signal import find_peaks

OUT = Path.cwd()


def negative_root(rho, mu, sigma):
    """Negative root of .5*sigma^2*b*(b-1)+mu*b-rho=0."""
    t = mu - 0.5 * sigma**2
    s = math.sqrt(t*t + 2*rho*sigma**2)
    return -2*rho/(s-t) if t <= 0 else (-t-s)/sigma**2


def coefficients(a, cost, rho, mu, sigma):
    assert a > 0 and cost > 0 and sigma > 0 and rho > max(mu, 0)
    beta = negative_root(rho, mu, sigma)
    aa, bb = a/(rho-mu), cost/rho
    boundary = (bb/aa)*beta/(beta-1)
    return aa, bb, beta, boundary


def operators(v, a=0.5, cost=1., rho=1., mu=0., sigma=1.):
    """Return C, abandonment put Pi, discounted first-hit Q and V-derivatives.

    C=0 and Pi=B-A*V in the stopping region. Q=1 there, so Q is NOT C1.
    Normalized C is evaluated with a boundary series to avoid cancellation.
    """
    aa, bb, beta, boundary = coefficients(a, cost, rho, mu, sigma)
    v = np.asarray(v, dtype=float)
    assert np.all(v > 0)
    z = v/boundary
    m = np.log(z)
    safe = z > 1
    pi = bb-aa*v
    pi = np.where(safe, bb*np.exp(beta*np.maximum(m, 0))/(1-beta), pi)
    c = np.zeros_like(v)
    # Only the continuation branch is evaluated; it has a second-order zero.
    mm = m[safe]
    cc = (-beta*np.expm1(mm) + np.expm1(beta*mm))/(1-beta)
    near = np.abs(mm) < 1e-4
    if np.any(near):
        ss = np.zeros(np.count_nonzero(near))
        for n in range(2, 9):
            ss += (-beta+beta**n)*mm[near]**n/math.factorial(n)/(1-beta)
        cc[near] = ss
    c[safe] = bb*cc
    dc = np.where(safe, aa+beta*pi/v, 0.)
    dpi = np.where(safe, beta*pi/v, -aa)
    ddc = np.where(safe, beta*(beta-1)*pi/v**2, 0.)
    qhit = np.exp(beta*np.maximum(m, 0))
    dqhit = np.where(safe, beta*qhit/v, 0.)
    return dict(C=c, Pi=pi, Q=qhit, dC=dc, dPi=dpi, ddC=ddc,
                dQ=dqhit, boundary=boundary, beta=beta, A=aa, B=bb)


def gate(x):
    """beta=-1, b=B=1, x=log(b/V).

    p = Pi/B; a = C/(B+C). Both are C1, not C2 at x=0.
    Return p, a, dp/dx, da/dx using overflow-safe exponentials.
    """
    x = np.asarray(x)
    e = np.exp(-np.abs(x))
    p = np.where(x < 0, .5*e, 1-.5*e)
    dp = .5*e
    sech = 2*e/(1+e*e)
    restoring = np.where(x < 0, 1-sech, 0.)
    da = np.where(x < 0, sech*np.tanh(x), 0.)
    return p, restoring, dp, da


G, H, TAU = 4., 6., 5.


def rhs(t, state, input_fn, g=G, h=H, tau=TAU):
    x, y = state
    p, restoring, _, _ = gate(x)
    return [-x+restoring+g*p-y+input_fn(t), (h*p-y)/tau]


def rest_state(current):
    x = brentq(lambda xx: -xx+gate(xx)[1]+(G-H)*gate(xx)[0]+current,
               -20, 20, xtol=1e-14)
    return np.array([x, H*gate(x)[0]])


def integrate(input_fn, start, duration, step=.02, tight=False):
    tt = np.linspace(0, duration, round(duration/step)+1)
    sol = solve_ivp(lambda t, s: rhs(t, s, input_fn), (0., duration), start,
                    t_eval=tt, rtol=1e-11 if tight else 1e-9,
                    atol=1e-13 if tight else 1e-11,
                    max_step=.02 if tight else .08)
    if not sol.success:
        raise RuntimeError(sol.message)
    return sol.t, sol.y


def discrete_loss_and_gradient(params, dt=.01, steps=1800):
    """Manual exact reverse-mode BPTT for this explicitly defined Euler model.

    params = (regenerative_gain, recovery_gain, input_pulse_amplitude).
    Initial state and target are fixed and independent of these parameters.
    This checks differentiability, not task learning or model quality.
    """
    g, h, amplitude = params
    tt = np.arange(steps+1)*dt
    state = np.zeros((steps+1, 2))
    state[0] = rest_state(-.2)
    envelope = np.exp(-.5*((tt-4)/.5)**2)
    for k in range(steps):
        x, y = state[k]
        p, restoring, _, _ = gate(x)
        state[k+1] = state[k] + dt*np.array([
            -x+restoring+g*p-y-.2+amplitude*envelope[k],
            (h*p-y)/TAU])
    p, _, dp, _ = gate(state[:, 0])
    target = .3+.4*np.exp(-.5*((tt-6)/1.5)**2)
    err = p-target
    loss = .5*np.mean(err**2)
    direct = err*dp/(steps+1)
    adj = np.array([direct[-1], 0.])
    grad = np.zeros(3)
    for k in range(steps-1, -1, -1):
        x, y = state[k]
        pk, ak, dpk, dak = gate(x)
        dparam = np.array([[dt*pk, 0., dt*envelope[k]],
                           [0., dt*pk/TAU, 0.]])
        grad += adj @ dparam
        jac = np.array([[1+dt*(-1+dak+g*dpk), -dt],
                        [dt*h*dpk/TAU, 1-dt/TAU]])
        adj = jac.T @ adj + np.array([direct[k], 0.])
    return float(loss), grad


def main():
    result = {"scope": "Toy optimal-stopping operators plus a newly designed C1 ODE; no training benchmark",
              "full_he_xiong_model_reproduced": False,
              "trained_neural_network": False}
    # Verify both payoff matching and smooth pasting at the analytically known b.
    base = operators(np.array([1.]))
    result["base_parameters"] = dict(a=.5, cost=1., rho=1., mu=0., sigma=1.,
                                    beta=base["beta"], boundary=base["boundary"])
    result["boundary_values"] = {k: float(base[k][0]) for k in ["C", "Pi", "Q", "dC", "dPi"]}
    # Independent ODE residual checks across admissible parameter settings.
    rng = np.random.default_rng(20261029)
    worst_residual = 0.
    for _ in range(100):
        mu = rng.uniform(-.2, .2)
        rho = max(mu, 0)+rng.uniform(.2, 1.2)
        sigma = rng.uniform(.25, 1.5)
        a, cost = rng.uniform(.2, 2., 2)
        aa, bb, beta, boundary = coefficients(a, cost, rho, mu, sigma)
        v = boundary*np.geomspace(1.00001, 5, 30)
        op = operators(v, a, cost, rho, mu, sigma)
        residual = .5*sigma*sigma*v*v*op["ddC"]+mu*v*op["dC"]-rho*op["C"]+a*v-cost
        worst_residual = max(worst_residual, float(np.max(np.abs(residual))))
    result["continuation_ode_max_abs_residual_100_parameter_sets"] = worst_residual
    assert worst_residual < 1e-10
    # First derivative checks near, but not exactly on, the boundary.
    grid = np.array([.2, .75, .999, 1.001, 1.5, 3.])
    eps = 1e-6
    op, opplus, opminus = operators(grid), operators(grid+eps), operators(grid-eps)
    errors = {}
    for name, dname in [("C", "dC"), ("Pi", "dPi")]:
        fd = (opplus[name]-opminus[name])/(2*eps)
        errors[name] = float(np.max(np.abs(fd-op[dname])))
    result["operator_derivative_max_abs_errors"] = errors
    assert max(errors.values()) < 1e-7
    # Deterministic weak/strong pulse experiment, identical starting equilibrium.
    initial = rest_state(-.2)
    tracks = {}
    for amplitude in [.1, 1.]:
        fn = lambda t, amp=amplitude: -.2+amp*np.exp(-.5*((t-10)/.5)**2)
        t, states = integrate(fn, initial, 60.)
        tracks[amplitude] = (t, states)
        result[f"pulse_{amplitude:g}"] = dict(x_max=float(states[0].max()),
                  q_max=float(gate(states[0])[0].max()),
                  final_distance_to_rest=float(np.linalg.norm(states[:, -1]-initial)))
    result["rest_state_at_I_minus_0p2"] = initial.tolist()
    fnstrong = lambda t: -.2+np.exp(-.5*((t-10)/.5)**2)
    _, tighter = integrate(fnstrong, initial, 60., tight=True)
    convergence = float(np.max(np.abs(tighter-tracks[1.][1])))
    result["strong_pulse_solver_refinement_max_state_difference"] = convergence
    assert convergence < 1e-5
    # Sustained input: evaluate late trajectory, not just a transient.
    tc, cyc = integrate(lambda t: 1., np.array([.1, 3.]), 300.)
    mask = tc >= 200.
    pc = gate(cyc[0])[0]
    peaks, _ = find_peaks(pc[mask], prominence=.05)
    periods = np.diff(tc[mask][peaks])
    result["constant_I_1_late_response"] = dict(
        interval=[200., 300.], x_min=float(cyc[0, mask].min()),
        x_max=float(cyc[0, mask].max()), q_min=float(pc[mask].min()),
        q_max=float(pc[mask].max()), measured_peak_count=int(len(peaks)),
        mean_period=float(periods.mean()), period_sampling_resolution=.02)
    jac = np.array([[1., -1.], [.6, -.2]])
    result["I_1_equilibrium_jacobian"] = jac.tolist()
    result["I_1_equilibrium_eigenvalues"] = [str(v) for v in np.linalg.eigvals(jac)]
    # Exact gradients of the DISCRETIZED system vs central finite differences.
    params = np.array([4., 6., 1.])
    loss, grad = discrete_loss_and_gradient(params)
    numeric = np.zeros(3)
    for j in range(3):
        delta = np.zeros(3); delta[j] = 1e-5
        plus = discrete_loss_and_gradient(params+delta)[0]
        minus = discrete_loss_and_gradient(params-delta)[0]
        numeric[j] = (plus-minus)/(2e-5)
    result["bptt_check"] = dict(loss=loss, parameters=["g", "h", "pulse_amplitude"],
        analytic_gradient=grad.tolist(), finite_difference_gradient=numeric.tolist(),
        max_abs_error=float(np.max(np.abs(grad-numeric))),
        max_relative_error=float(np.max(np.abs(grad-numeric)/np.maximum(np.abs(numeric),1e-10))),
        steps=1800, dt=.01, finite_difference_epsilon=1e-5,
        note="Exact gradient of the chosen Euler recurrence, not exact integration of the ODE.")
    assert result["bptt_check"]["max_abs_error"] < 1e-7

    # Scientific illustration, with explicit units and no performance claims.
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                        "axes.spines.right": False, "figure.dpi": 150})
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 8.5), constrained_layout=True)
    colors = dict(call="#0B79B7", put="#BD4B35", risk="#7D738E")
    z = np.linspace(.08, 3., 900)
    op = operators(z)
    ax = axes[0, 0]
    ax.plot(z, op["C"], label="Continuation C / B", color=colors["call"], lw=2.3)
    ax.plot(z, op["Pi"], label="Abandonment put Pi / B", color=colors["put"], lw=2.3)
    ax.plot(z, op["Q"], "--", label="Discounted first-hit Q", color=colors["risk"], lw=1.6)
    ax.axvline(1., color="#777777", ls=":", lw=1.2)
    ax.set(xlabel="State ratio V / b", ylabel="Normalized value",
           title="A. Matched values are not default probabilities")
    ax.legend(fontsize=9)
    ax.grid(alpha=.17)
    ax = axes[0, 1]
    ax.plot(z, op["dC"], label="dC / dV", color=colors["call"], lw=2.3)
    ax.plot(z, op["dPi"], label="dPi / dV", color=colors["put"], lw=2.3)
    ax.plot(z[z<1], op["dQ"][z<1], "--", color=colors["risk"], lw=1.6)
    ax.plot(z[z>1], op["dQ"][z>1], "--", label="dQ / dV (jump at b)", color=colors["risk"], lw=1.6)
    ax.axvline(1., color="#777777", ls=":", lw=1.2)
    ax.set(xlabel="State ratio V / b", ylabel="First derivative",
           title="B. C and Pi paste smoothly; Q does not")
    ax.legend(fontsize=9)
    ax.grid(alpha=.17)
    ax = axes[1, 0]
    for amp, col in [(.1, "#4F7C8A"), (1., "#BD4B35")]:
        tt, st = tracks[amp]
        ax.plot(tt, st[0], label=f"Input pulse amplitude {amp:g}", color=col, lw=2.2)
    ax.axhline(0., color="#777777", ls=":", lw=1.2, label="Free boundary x = 0")
    ax.set(xlim=(4, 42), xlabel="Dimensionless time", ylabel="x = log(b / V)",
           title="C. Smooth evoked response and recovery")
    ax.legend(fontsize=9)
    ax.grid(alpha=.17)
    ax = axes[1, 1]
    ax.plot(cyc[0, mask], cyc[1, mask], color="#7B56A3", lw=2.2,
            label=f"Constant input I = 1; period ~{periods.mean():.2f}")
    ax.scatter([0], [3], marker="x", color="#333333", zorder=5, label="Unstable equilibrium")
    ax.axvline(0., color="#777777", ls=":", lw=1.2)
    ax.set(xlabel="x = log(b / V)", ylabel="Recovery state y",
           title="D. Two-state dynamics support continuous oscillation")
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(alpha=.17)
    fig.suptitle("HCSN feasibility toy: exact C1 operators + newly designed dynamics", fontsize=16)
    fig.savefig(OUT/"HCSN_free_boundary_lab.png", dpi=180)
    plt.close(fig)
    (OUT/"hcsn_lab_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
