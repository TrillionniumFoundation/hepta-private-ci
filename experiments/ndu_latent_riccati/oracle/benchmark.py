"""Independent numerical audit of the exact joint (generation, valuation) LQ case."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy
from scipy.integrate import quad, solve_bvp, solve_ivp
from scipy.linalg import block_diag
import torch

from solver import torch_dre


def system():
    # p has neither autonomous drift nor intrinsic diffusion. nu is costly.
    A = np.array([[-.25, .1, 1.1, .15], [-.08, -.15, .2, .9],
                  [0., 0., 0., 0.], [0., 0., 0., 0.]])
    B = np.diag([.65, .55, .9, .85])
    D = np.array([[1., .2, -.55, 0.], [-.1, 1., 0., -.5],
                  [0., 0., .25, .05], [0., 0., -.05, .3]])
    Q = D.T @ D + .15 * np.eye(4)
    R = np.diag([1., 1.3, .4, .45])
    H = np.array([[3., .2, -.7, .1], [.2, 2.5, 0., -.6],
                  [-.7, 0., .8, .1], [.1, -.6, .1, .9]])
    Sigma = np.array([[.2, .04], [0., .15], [0., 0.], [0., 0.]])
    x0 = np.array([1.2, -.7, .8, -1.1])
    return A, B, Q, R, H, Sigma, x0, 2.0


def scipy_dre(A, B, Q, R, H, T):
    n = A.shape[0]
    M = B @ np.linalg.solve(R, B.T)

    def rhs(t, flat):
        S = flat.reshape(n, n)
        return -(A.T @ S + S @ A + Q - S @ M @ S).ravel()

    solution = solve_ivp(rhs, (T, 0.), H.ravel(), method="DOP853",
                         rtol=2e-12, atol=2e-13, dense_output=True)
    if not solution.success:
        raise RuntimeError(solution.message)
    return lambda t: solution.sol(t).reshape(n, n)


def expected_cost(A, B, Q, R, H, Sigma, x0, T, gain):
    # Independent forward second-moment ODE, not the backward Riccati value.
    n = len(x0)

    def rhs(t, state):
        moment = state[:-1].reshape(n, n)
        K = gain(t)
        F = A - B @ K
        dm = F @ moment + moment @ F.T + Sigma @ Sigma.T
        cost = .5 * np.trace((Q + K.T @ R @ K) @ moment)
        return np.r_[dm.ravel(), cost]

    result = solve_ivp(rhs, (0., T), np.r_[np.outer(x0, x0).ravel(), 0.],
                       method="DOP853", rtol=2e-10, atol=2e-12)
    if not result.success:
        raise RuntimeError(result.message)
    moment = result.y[:-1, -1].reshape(n, n)
    return float(result.y[-1, -1] + .5 * np.trace(H @ moment))


def independent_bvp(A, B, Q, R, H, x0, T, S):
    n = len(x0)
    M = B @ np.linalg.solve(R, B.T)

    def rhs(t, y):
        return np.vstack((A @ y[:n] - M @ y[n:], -Q @ y[:n] - A.T @ y[n:]))

    def bc(left, right):
        return np.r_[left[:n] - x0, right[n:] - H @ right[:n]]

    mesh = np.linspace(0., T, 33)
    guess = np.vstack((np.tile(x0[:, None], (1, len(mesh))), np.zeros((n, len(mesh)))))
    bvp = solve_bvp(rhs, bc, mesh, guess, tol=1e-10, max_nodes=10000)
    if not bvp.success:
        raise RuntimeError(bvp.message)
    grid = np.linspace(0., T, 501)
    paths = bvp.sol(grid)
    riccati_adjoint = np.stack([S(t) @ paths[:n, j] for j, t in enumerate(grid)], 1)
    bvp_controls = -np.linalg.solve(R, B.T @ paths[n:])
    feedback_controls = -np.linalg.solve(R, B.T @ riccati_adjoint)

    def integrand(t):
        y = bvp.sol(t)
        u = -np.linalg.solve(R, B.T @ y[n:])
        return .5 * (y[:n] @ Q @ y[:n] + u @ R @ u)

    terminal = bvp.sol(T)[:n]
    cost = quad(integrand, 0., T, epsabs=1e-11, epsrel=1e-11)[0] + .5 * terminal @ H @ terminal
    return {"method": "scipy.solve_bvp on Pontryagin boundary problem; no Riccati in solve",
            "success": bool(bvp.success), "nodes": len(bvp.x),
            "max_rms_residual": float(np.max(bvp.rms_residuals)),
            "adjoint_max_abs_error": float(np.max(np.abs(paths[n:] - riccati_adjoint))),
            "control_max_abs_error": float(np.max(np.abs(bvp_controls - feedback_controls))),
            "boundary_max_abs_error": float(np.max(np.abs(bc(paths[:, 0], paths[:, -1])))),
            "cost": float(cost), "value_error": float(abs(cost - .5 * x0 @ S(0.) @ x0))}


def condensed_qp(A, B, Q, R, H, x0, T, N):
    # Eliminate all states to form one dense quadratic program, without Riccati.
    h = T / N
    n, m = B.shape
    Ad, Bd = np.eye(n) + h * A, h * B
    F = np.zeros(((N + 1) * n, n))
    G = np.zeros(((N + 1) * n, N * m))
    F[:n] = np.eye(n)
    for k in range(N):
        F[(k + 1) * n:(k + 2) * n] = Ad @ F[k * n:(k + 1) * n]
        G[(k + 1) * n:(k + 2) * n] = Ad @ G[k * n:(k + 1) * n]
        G[(k + 1) * n:(k + 2) * n, k * m:(k + 1) * m] += Bd
    W = block_diag(*([h * Q] * N + [H]))
    RR = np.kron(np.eye(N), h * R)
    initial = F @ x0
    Hess = G.T @ W @ G + RR
    linear = G.T @ W @ initial
    U = np.linalg.solve(Hess, -linear)
    X = initial + G @ U
    cost = .5 * (X @ W @ X + U @ RR @ U)
    # Separate dynamic programming implementation is checked against this QP.
    P = H.copy()
    gains = []
    for _ in range(N):
        K = np.linalg.solve(h * R + Bd.T @ P @ Bd, Bd.T @ P @ Ad)
        P = h * Q + Ad.T @ P @ Ad - Ad.T @ P @ Bd @ K
        gains.append(K)
    x = x0.copy()
    feedback = []
    for K in reversed(gains):
        u = -K @ x
        feedback.append(u)
        x = Ad @ x + Bd @ u
    return {"steps": N, "dt": h, "condensed_cost": float(cost),
            "condensed_stationarity_max_abs": float(np.max(np.abs(Hess @ U + linear))),
            "discrete_riccati_value_error": float(abs(cost - .5 * x0 @ P @ x0)),
            "discrete_riccati_control_max_abs": float(np.max(np.abs(U - np.concatenate(feedback))))}


def gradient_check(A, B, Q, R, H, x0, T):
    tensors = [torch.tensor(x, dtype=torch.float64) for x in (A, B, Q, R, H, x0)]
    ta, tb, tq, tr, th, tx = tensors

    def loss(theta):
        # Learnable drift scale, preference-control efficiency, and valuation cost.
        ac = ta * theta[0].exp()
        bc = tb @ torch.diag(torch.stack((theta[1] * 0 + 1, theta[1] * 0 + 1,
                                         theta[1].exp(), theta[1].exp())))
        rc = tr @ torch.diag(torch.stack((theta[2] * 0 + 1, theta[2] * 0 + 1,
                                         theta[2].exp(), theta[2].exp())))
        S, K = torch_dre(ac, bc, tq, rc, th, T, 128)
        # Outer objective intentionally differs from optimized inner objective.
        x = tx
        energy = x.sum() * 0
        for k in range(128):
            u = -K[k] @ x
            energy = energy + (T / 128) * .15 * u.square().sum()
            x = x + (T / 128) * (ac @ x + bc @ u)
        return .5 * (x * torch.tensor([4., 2., .3, .3], dtype=x.dtype)) @ x + energy

    theta = torch.tensor([.07, -.11, .09], dtype=torch.float64, requires_grad=True)
    loss(theta).backward()
    automatic = theta.grad.detach().numpy().copy()
    finite = []
    step = 1e-5
    with torch.no_grad():
        for i in range(3):
            shift = torch.zeros_like(theta)
            shift[i] = step
            finite.append(float((loss(theta + shift) - loss(theta - shift)) / (2 * step)))
    finite = np.array(finite)
    return {"parameter_values": theta.detach().tolist(), "step": step,
            "autograd": automatic.tolist(), "centered_finite_difference": finite.tolist(),
            "max_abs_error": float(np.max(np.abs(automatic - finite))),
            "relative_l2_error": float(np.linalg.norm(automatic - finite) / max(1e-12, np.linalg.norm(finite))),
            "objective": "external terminal loss plus control energy after feedback rollout"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    torch.set_num_threads(1)
    A, B, Q, R, H, Sigma, x0, T = system()
    S = scipy_dre(A, B, Q, R, H, T)
    gain = lambda t: np.linalg.solve(R, B.T @ S(t))
    projection = np.linalg.pinv(Sigma.T) @ Sigma.T
    fixed_B = B.copy()
    fixed_B[:, 2:] = 0.
    fixed_S = scipy_dre(A, fixed_B, Q, R, H, T)

    def no_cross(t):
        s = S(t).copy()
        s[:2, 2:] = 0.
        s[2:, :2] = 0.
        return np.linalg.solve(R, B.T @ s)

    def low_rank(t, rank):
        eig, vec = np.linalg.eigh(S(t))
        approx = (vec[:, -rank:] * eig[-rank:]) @ vec[:, -rank:].T
        return np.linalg.solve(R, B.T @ approx)

    selectors = {"full_gradient_dense": gain,
                 "z_only_pseudoinverse": lambda t: np.linalg.solve(R, B.T @ projection @ S(t)),
                 "fixed_preference_nu_zero": lambda t: np.linalg.solve(R, fixed_B.T @ fixed_S(t)),
                 "removed_cross_blocks": no_cross}
    for rank in (1, 2, 3):
        selectors[f"rank_{rank}_projection"] = lambda t, r=rank: low_rank(t, r)
    costs = {name: expected_cost(A, B, Q, R, H, Sigma, x0, T, k)
             for name, k in selectors.items()}
    base = costs["full_gradient_dense"]
    values = []
    for noise_scale in (0., .5, 1., 2.):
        sig = Sigma * noise_scale
        analytic = .5 * x0 @ S(0.) @ x0 + .5 * quad(
            lambda t: np.trace(sig @ sig.T @ S(t)), 0., T, epsabs=1e-11)[0]
        forward = expected_cost(A, B, Q, R, H, sig, x0, T, gain)
        values.append({"sigma_scale": noise_scale, "analytic_value": float(analytic),
                       "forward_moment_cost": forward, "value_abs_error": float(abs(analytic - forward)),
                       "feedback": "same K(t) for all additive-noise scales"})
    exact = float(.5 * x0 @ S(0.) @ x0)
    mesh = [condensed_qp(A, B, Q, R, H, x0, T, n) for n in (16, 32, 64, 128, 256)]
    for row in mesh:
        row["continuous_value_abs_error"] = abs(row["condensed_cost"] - exact)
    rk4 = []
    ts = [torch.tensor(x, dtype=torch.float64) for x in (A, B, Q, R, H)]
    for n in (16, 32, 64, 128):
        estimate, _ = torch_dre(*ts, T, n)
        err = float(np.max(np.abs(estimate[0].detach().numpy() - S(0.))))
        rk4.append({"steps": n, "S0_max_abs_error": err})
    bvp = independent_bvp(A, B, Q, R, H, x0, T, S)
    gradient = gradient_check(A, B, Q, R, H, x0, T)
    gates = {
        "independent_bvp_control_and_value": bvp["control_max_abs_error"] < 1e-7 and bvp["value_error"] < 1e-8,
        "independent_condensed_qp": max(r["discrete_riccati_control_max_abs"] for r in mesh) < 1e-8,
        "continuous_mesh_converges": all(mesh[i+1]["continuous_value_abs_error"] < .65 * mesh[i]["continuous_value_abs_error"] for i in range(4)),
        "rk4_refinement_converges": rk4[-1]["S0_max_abs_error"] < 1e-7 and rk4[-1]["S0_max_abs_error"] < rk4[0]["S0_max_abs_error"] / 100,
        "solver_autograd_matches_finite_difference": gradient["relative_l2_error"] < 1e-6,
        "additive_noise_value_matches_independent_moments": max(r["value_abs_error"] for r in values) < 1e-8,
        "full_policy_no_worse_than_ablation_on_known_lq": min(costs.values()) >= base - 1e-8,
    }
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in Path(__file__).parent.glob("*.py")}
    result = {"schema": "ndu-continuous-lq-oracle-v1", "started_utc": started,
              "finished_utc": datetime.now(timezone.utc).isoformat(),
              "runtime_seconds": time.perf_counter() - start,
              "scope": "engineered exact LQ mechanism validation; not neural generation efficacy",
              "execution_tier": os.getenv("HEPTA_EXECUTION_TIER", "local-preflight"),
              "runtime": {"python": sys.version, "executable": sys.executable,
                          "numpy": np.__version__, "scipy": scipy.__version__, "torch": torch.__version__,
                          "module_locations": {"numpy": np.__file__, "scipy": scipy.__file__, "torch": torch.__file__},
                          "torch_num_threads": torch.get_num_threads(),
                          "openblas_num_threads": os.getenv("OPENBLAS_NUM_THREADS"),
                          "omp_num_threads": os.getenv("OMP_NUM_THREADS"),
                          "argv": sys.argv, "platform": platform.platform()}, "source_sha256": files,
              "system": {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in
                         zip(("A", "B", "Q", "R", "H", "Sigma", "x0", "T"), system())},
              "assumptions": {"rho": 0, "full_state_observed": True, "unconstrained_controls": True,
                              "preference_diffusion_norm": float(np.linalg.norm(Sigma[2:])),
                              "Q_min_eigenvalue": float(np.linalg.eigvalsh(Q)[0]),
                              "H_min_eigenvalue": float(np.linalg.eigvalsh(H)[0]),
                              "R_min_eigenvalue": float(np.linalg.eigvalsh(R)[0]),
                              "S0_zp_norm": float(np.linalg.norm(S(0.)[:2, 2:]))},
              "continuous_value_without_noise": exact,
              "S0": S(0.).tolist(), "initial_full_costate": (S(0.) @ x0).tolist(),
              "initial_Z": (Sigma.T @ S(0.) @ x0).tolist(),
              "initial_Z_pseudoinverse_costate": (projection @ S(0.) @ x0).tolist(),
              "ablations": {k: {"expected_cost": v, "regret": v - base, "relative_regret": (v - base) / base} for k, v in costs.items()},
              "independent_bvp": bvp, "condensed_qp_mesh": mesh,
              "differentiable_rk4_mesh": rk4, "autograd_audit": gradient,
              "risk_neutral_noise_negative_control": values, "gates": gates,
              "all_numerical_gates_passed": all(gates.values()),
              "limitations": ["A deliberately coupled known linear system establishes numerical validity, not empirical novelty.",
                              "Low-rank selectors are projections of the dense solution, not an invariant low-rank Riccati family.",
                              "Z-only receives the exact Z but loses the zero-diffusion costate; this is an information-loss diagnostic.",
                              "No nonlinear, constrained, learned-dynamics, natural-modality or large-model guarantee is claimed."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "gates": gates, "ablations": result["ablations"],
                      "runtime_seconds": result["runtime_seconds"]}, indent=2))
    if not all(gates.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
