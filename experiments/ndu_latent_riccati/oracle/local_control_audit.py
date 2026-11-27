"""Independent affine-QP, Jacobian and through-rollout gradient checks."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from control import Flow, affine_lqr, joint_dynamics, quadratic_cost, riccati_action, rollout


def condensed(F, G, b, Q, q, R, H, h, x0, steps):
    """Solve all controls together by eliminating states, without backward DP."""
    n, m = G.shape
    E = np.zeros(((steps + 1) * n, n))
    D = np.zeros(((steps + 1) * n, steps * m))
    c = np.zeros((steps + 1) * n)
    E[:n] = np.eye(n)
    for k in range(steps):
        src, dst = slice(k * n, (k + 1) * n), slice((k + 1) * n, (k + 2) * n)
        E[dst], D[dst], c[dst] = F @ E[src], F @ D[src], F @ c[src] + b
        D[dst, k * m:(k + 1) * m] += G
    W = np.zeros(((steps + 1) * n, (steps + 1) * n))
    linear = np.r_[np.tile(q, steps), h]
    for k in range(steps + 1):
        sl = slice(k * n, (k + 1) * n)
        W[sl, sl] = Q if k < steps else H
    RR = np.kron(np.eye(steps), R)
    base = E @ x0 + c
    Hess = D.T @ W @ D + RR
    rhs = D.T @ (W @ base + linear)
    U = np.linalg.solve(Hess, -rhs)
    X = base + D @ U
    M = E.T @ W @ D
    S = E.T @ W @ E - M @ np.linalg.solve(Hess, M.T)
    s = E.T @ (W @ c + linear) - M @ np.linalg.solve(Hess, D.T @ (W @ c + linear))
    gradient = E.T @ (W @ X + linear)
    return U[:m], S, s, gradient, np.max(np.abs(Hess @ U + rhs))


def affine_cases(rng):
    rows = []
    for n, m, steps in ((4, 2, 1), (4, 2, 4), (13, 13, 2), (13, 13, 4), (13, 13, 8)):
        batch = 3
        Fs, Gs, bs, Qs, qs, Rs, Hs, hs, xs = [[] for _ in range(9)]
        for _ in range(batch):
            F = np.eye(n) + .05 * rng.normal(size=(n, n))
            G = .12 * rng.normal(size=(n, m))
            L, Lh, Lr = (rng.normal(size=shape) for shape in ((n, n), (n, n), (m, m)))
            values = (F, G, .2 * rng.normal(size=n), .1 * (L.T @ L + np.eye(n)),
                      rng.normal(size=n), .1 * (Lr.T @ Lr + np.eye(m)),
                      .2 * (Lh.T @ Lh + np.eye(n)), rng.normal(size=n), rng.normal(size=n))
            for container, value in zip((Fs, Gs, bs, Qs, qs, Rs, Hs, hs, xs), values):
                container.append(value)
        tensors = [torch.tensor(np.stack(a), dtype=torch.float64) for a in (Fs, Gs, bs, Qs, qs, Rs, Hs, hs)]
        K, k, S, s = affine_lqr(*tensors, steps=steps)
        errors = []
        for j in range(batch):
            reference = condensed(Fs[j], Gs[j], bs[j], Qs[j], qs[j], Rs[j], Hs[j], hs[j], xs[j], steps)
            u, Sr, sr, grad, stationarity = reference
            actual = -(K[j].detach().numpy() @ xs[j] + k[j].detach().numpy())
            errors.append({"first_action": float(np.max(np.abs(actual - u))),
                           "S": float(np.max(np.abs(S[j].detach().numpy() - Sr))),
                           "s": float(np.max(np.abs(s[j].detach().numpy() - sr))),
                           "value_gradient": float(np.max(np.abs(S[j].detach().numpy() @ xs[j] + s[j].detach().numpy() - grad))),
                           "qp_stationarity": float(stationarity)})
        rows.append({"state_dimension": n, "control_dimension": m, "steps": steps, "batch": batch,
                     "max_abs_errors": {key: max(e[key] for e in errors) for key in errors[0]}})
    return rows


def model_checks(flow, x, context, target):
    t = .25
    _, J = flow(x[:, :7], t, context, jacobian=True)
    _, A = joint_dynamics(flow, x, t, context, target, need_jacobian=True)
    Q, q = quadratic_cost(x, target)
    rows = []
    for i in range(len(x)):
        ctx, tgt = context[i:i+1], target[i:i+1]
        xv = x[i].detach().requires_grad_(True)
        jf = torch.autograd.functional.jacobian(lambda z: flow(z[None], t, ctx)[0], xv[:7])
        ja = torch.autograd.functional.jacobian(lambda y: joint_dynamics(flow, y[None], t, ctx, tgt)[0], xv)

        def residual(y):
            return torch.exp(.25 * torch.tanh(y[7:])) * (y[:6] - tgt[0])

        def true_cost(y):
            return .5 * residual(y).square().sum() + .025 * y[7:].square().sum()

        grad = torch.autograd.grad(true_cost(xv), xv)[0]
        jr = torch.autograd.functional.jacobian(residual, xv)
        gn = jr.T @ jr + torch.diag(xv.new_tensor([0.] * 7 + [.05] * 6))
        hess = torch.autograd.functional.hessian(true_cost, xv)
        rows.append({"flow_jacobian_max_abs": float((jf - J[i]).abs().max()),
                     "joint_jacobian_max_abs": float((ja - A[i]).abs().max()),
                     "preference_jacobian_max_abs": float((ja[:, 7:] - A[i, :, 7:]).abs().max()),
                     "GN_hessian_max_abs": float((gn - Q[i]).abs().max()),
                     "state_cost_gradient_max_abs": float((grad - (Q[i] @ xv + q[i])).abs().max()),
                     "GN_min_eigenvalue": float(torch.linalg.eigvalsh(Q[i]).min()),
                     "true_hessian_minus_GN_norm": float((hess - gn).norm())})
    return rows


def action_qp_checks(flow, x, context, target):
    rows = []
    for arm in ("ndu", "fixed_valuation_mpc"):
        for t, dt in ((0., .125), (.875, .125), (.5, 1 / 6)):
            actual, diagnostics = riccati_action(flow, x, t, context, target, dt, arm=arm)
            for i in range(len(x)):
                xv = x[i].detach().requires_grad_(True)
                ctx, tgt = context[i:i+1], target[i:i+1]
                # Dynamics are taken from forward(), Jacobians by independent AD.
                drift = joint_dynamics(flow, xv[None], t, ctx, tgt)[0]
                jac = torch.autograd.functional.jacobian(lambda y: joint_dynamics(flow, y[None], t, ctx, tgt)[0], xv)

                def residual(y):
                    return torch.exp(.25 * torch.tanh(y[7:])) * (y[:6] - tgt[0])

                jr = torch.autograd.functional.jacobian(residual, xv)
                gn = jr.T @ jr + torch.diag(xv.new_tensor([0.] * 7 + [.05] * 6))
                state_cost = .5 * residual(xv).square().sum() + .025 * xv[7:].square().sum()
                grad = torch.autograd.grad(state_cost, xv)[0]
                linear = grad - gn @ xv
                actuator = np.ones(13)
                actuator[6] = 0
                if arm == "fixed_valuation_mpc":
                    actuator[7:] = 0
                F = np.eye(13) + dt * jac.detach().numpy()
                b = dt * (drift - jac @ xv).detach().numpy()
                G = dt * np.diag(actuator)
                qnp, lnp = gn.detach().numpy(), linear.detach().numpy()
                R = dt * np.diag([.25] * 7 + [.1] * 6)
                steps = min(4, max(1, round((1-t) / dt)))
                u, S, s, _, residual_qp = condensed(F, G, b, dt*qnp, dt*lnp, R, 2*qnp, 2*lnp,
                                                    xv.detach().numpy(), steps)
                rows.append({"arm": arm, "t": t, "dt": dt, "steps": steps,
                             "action_max_abs": float(np.max(np.abs(actual[i].detach().numpy() - u))),
                             "S_max_abs": float(np.max(np.abs(diagnostics["S"][i].detach().numpy() - S))),
                             "s_max_abs": float(np.max(np.abs(diagnostics["s"][i].detach().numpy() - s))),
                             "qp_stationarity": float(residual_qp)})
    return rows


def rollout_gradient_checks(flow, context, target, noise):
    def loss():
        result = rollout(flow, context, target, noise, steps=4, arm="ndu", lookahead=3)
        weights = noise.new_tensor([1., 2., 3., 1., 2., 1., .2])
        return (result["state"].square() * weights).mean() + .3 * result["effort"].mean() + .1 * result["p"].square().mean()

    flow.zero_grad(set_to_none=True)
    value = loss()
    value.backward()
    rows = []
    eps = 1e-5
    for name, param, index in (("flow.l1.weight[1,2]", flow.l1.weight, (1, 2)),
                                ("flow.l2.weight[5,4]", flow.l2.weight, (5, 4)),
                                ("flow.l3.weight[0,0]", flow.l3.weight, (0, 0))):
        automatic = param.grad[index].item()
        original = param[index].item()
        with torch.no_grad():
            param[index] = original + eps
            plus = loss().item()
            param[index] = original - eps
            minus = loss().item()
            param[index] = original
        finite = (plus-minus) / (2*eps)
        rows.append({"parameter": name, "autograd": automatic, "finite_difference": finite,
                     "abs_error": abs(automatic-finite), "relative_error": abs(automatic-finite)/max(1e-7, abs(finite))})
    return {"outer_loss": value.item(), "steps": 4, "lookahead": 3, "difference_step": eps, "parameters": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    start = time.perf_counter()
    torch.set_num_threads(1)
    torch.manual_seed(82431)
    rng = np.random.default_rng(82431)
    flow = Flow().double()
    x = torch.randn(3, 13, dtype=torch.float64)
    context = torch.randn(3, 32, dtype=torch.float64)
    target = torch.randn(3, 6, dtype=torch.float64)
    affine = affine_cases(rng)
    models = model_checks(flow, x, context, target)
    actions = action_qp_checks(flow, x, context, target)
    gradients = rollout_gradient_checks(flow, context, target, x[:, :7])
    fixed = rollout(flow, context, target, x[:, :7], steps=8, arm="fixed_valuation_mpc", return_trace=True)
    frozen_p_max = fixed["trace"][:, :, 7:].abs().max().item()
    gates = {
        "affine_QP_action_curvature_linear_and_gradient": max(v for row in affine for v in row["max_abs_errors"].values()) < 1e-9,
        "analytic_flow_and_joint_Jacobians": max(row[key] for row in models for key in ("flow_jacobian_max_abs", "joint_jacobian_max_abs", "preference_jacobian_max_abs")) < 1e-10,
        "GN_and_true_first_derivative": max(row[key] for row in models for key in ("GN_hessian_max_abs", "state_cost_gradient_max_abs")) < 1e-10,
        "GN_PSD": min(row["GN_min_eigenvalue"] for row in models) > -1e-10,
        "local_actions_match_independent_QP": max(row[key] for row in actions for key in ("action_max_abs", "S_max_abs", "s_max_abs", "qp_stationarity")) < 1e-9,
        "through_nonlinear_rollout_gradient": max(row["relative_error"] for row in gradients["parameters"]) < 1e-5,
        "fixed_p_stays_zero_from_zero_initial_state": frozen_p_max == 0.,
    }
    result = {"schema": "ndu-local-control-independent-audit-v1", "finished_utc": datetime.now(timezone.utc).isoformat(),
              "execution_tier": "local-preflight", "runtime_seconds": time.perf_counter()-start,
              "runtime": {"python": sys.version, "executable": sys.executable, "numpy": np.__version__, "torch": torch.__version__},
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"control.py", Path(__file__))},
              "affine_QP_cases": affine, "model_differential_checks": models, "local_action_QP_checks": actions,
              "through_rollout_gradients": gradients, "fixed_p_max_abs": frozen_p_max,
              "gates": gates, "all_numerical_gates_passed": all(gates.values()),
              "scope": "Independent local algebra/differential audit only; no global nonlinear optimality or efficacy claim",
              "observations": ["Returned S,s describe the initial local value; first control uses the next value through K,k.",
                               "GN curvature matches J'J plus regularization and the exact first derivative, but is not the true nonlinear Hessian.",
                               "Linearization coefficients and time are frozen across each lookahead; receding-horizon replanning is approximate.",
                               "A fixed number of lookahead steps implies different physical horizons at different discretization step counts.",
                               "Fixed valuation suppresses adjustment; p remains exactly zero here because it starts at zero."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "gates": gates, "gradient_checks": gradients, "runtime_seconds": result["runtime_seconds"]}, indent=2))
    if not all(gates.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
