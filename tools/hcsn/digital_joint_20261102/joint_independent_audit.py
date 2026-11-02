"""Pre-fit mathematical and finite-task reference audits for the joint study.

This counterexample concerns a stipulated true decoder law. It never opens
FullHX packets and does not estimate that model's actual accuracy.
"""
import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from ..digital_read_before_20261031 import task


def public_counterexample():
    return dict(schema="digital-read-before-public-v1", id="fitted-law-counterexample",
                deadline=6, initial_budget=3, duration=[1.5]*6,
                reliability=[.55]*6, read_price=[.01]+[.18]*5, read_delay=[1]*6,
                latency_price=.04, repair_price=.05, failure_probability=.16,
                packets=[f"packet_{i}.json" for i in range(6)], packet_sha256=["0"*64]*6)


def exact_policy_value(public, policy_confusion, true_confusion):
    """Evaluate the fitted-DP policy using the true law and complete successors."""
    policy_oracle = task.Oracle(public, policy_confusion)
    true_confusion = np.asarray(true_confusion)
    @lru_cache(None)
    def value(key):
        state = policy_oracle._state(key)
        action = int(np.argmax(policy_oracle.q(state)))
        p = task.posterior(public, state, true_confusion)
        if action in (0, 4, 5):
            return 0. if action == 0 else (1-2*p if action == 4 else 2*p-1)
        source = task.due_request(public, state, action)
        outcomes = [(1., None)]
        if source is not None:
            reliability, failure = public["reliability"][source], public["failure_probability"]
            law = reliability*true_confusion+(1-reliability)*true_confusion[::-1]
            predictive = (1-p)*law[0]+p*law[1]
            outcomes = [(failure, dict(failure=True))]
            outcomes += [((1-failure)*predictive[y], dict(observation=y)) for y in (0, 1)]
        result = 0.
        for probability, outcome in outcomes:
            after = task.successor(public, state, action, outcome)
            result += probability*(value(policy_oracle.key(after))-(after["charges"]-state["charges"]))
        return float(result)
    return value(policy_oracle.key(task.initial(public)))


def fitted_law_counterexample():
    public = public_counterexample()
    true_accuracy, fitted_accuracy = .85, 31.5/33
    true_confusion = [[true_accuracy, 1-true_accuracy], [1-true_accuracy, true_accuracy]]
    fitted_confusion = [[fitted_accuracy, 1-fitted_accuracy], [1-fitted_accuracy, fitted_accuracy]]
    state = task.initial(public)
    q_true = task.Oracle(public, true_confusion).q(state)
    q_fitted = task.Oracle(public, fitted_confusion).q(state)
    fitted_policy_true_value = exact_policy_value(public, fitted_confusion, true_confusion)
    true_policy_value = exact_policy_value(public, true_confusion, true_confusion)
    assert int(np.argmax(q_fitted)) == 2 and int(np.argmax(q_true)) == 0
    assert abs(q_fitted[2]-.0063636363636364) < 1e-12
    assert abs(q_true[2]+.0112) < 1e-12
    assert abs(fitted_policy_true_value+.0112) < 1e-12
    assert true_policy_value == 0.
    probability = (math.comb(32, 31)*true_accuracy**31*(1-true_accuracy))**2
    return dict(public=public, stipulated_true_confusion=true_confusion,
                stipulated_calibration_correct_counts=[31, 31], calibration_row_counts=[32, 32],
                fitted_confusion=fitted_confusion, calibration_event_probability=probability,
                fitted_q_initial=[float(x) if legal else None for x, legal in zip(q_fitted, task.legal(public, state))],
                true_q_initial=[float(x) if legal else None for x, legal in zip(q_true, task.legal(public, state))],
                fitted_policy_value_under_true_law=fitted_policy_true_value,
                correct_law_optimal_value=true_policy_value, ordinary_stop_value=0.,
                passed=True, actual_fullhx_accuracy_measured=False, new_confirmation_worlds=0)


def kernel_audit():
    """Audit the actual finite kernel; this does not qualify a continuum derivative."""
    import torch
    from scipy.integrate import quad
    from scipy.linalg import expm
    from .joint_kernel import DifferentiableRenewalCell, generator_from_physical
    torch.set_num_threads(1)
    raw = np.array([.2, -.3, .25, -.15, .4, -.3, .2, -.25])
    contexts = [(.17, 1., .85), (.38, -1., .65), (0., 0., .5), (.26, 1., .95), (.8, -1., .55)]
    def objective(cell):
        mass = cell.initial()
        for duration, symbol, reliability in contexts:
            mass = cell.advance_distribution(mass, duration, symbol, reliability)
        feature = mass @ cell.features(1., .85)
        weight = torch.linspace(-.6, .8, 12, dtype=torch.float64)
        return (feature @ weight).square()+.3*cell.expected_events(mass, .7, -1., .65)
    cell = DifferentiableRenewalCell(raw)
    loss = objective(cell)
    gradient = torch.autograd.grad(loss, cell.raw)[0].detach().numpy()
    finite_difference = []
    for coordinate in range(8):
        plus, minus = raw.copy(), raw.copy()
        plus[coordinate] += 1e-5
        minus[coordinate] -= 1e-5
        finite_difference.append((objective(DifferentiableRenewalCell(plus)).item()-objective(DifferentiableRenewalCell(minus)).item())/2e-5)
    gradient_error = float(np.max(np.abs(gradient-finite_difference)))
    assert gradient_error < 3e-7 and np.min(np.abs(gradient)) > 1e-7
    physical = cell.law(1., .85)
    numeric = {key: float(value.detach()) for key, value in physical.items()}
    n = cell.n_grid
    boundary, diffusion, drift = (numeric[key] for key in ("boundary", "diffusion", "drift"))
    spacing = 2*boundary/(n+1)
    right = diffusion**2/(2*spacing**2)+drift/(2*spacing)
    left = diffusion**2/(2*spacing**2)-drift/(2*spacing)
    q = np.zeros((n+2, n+2))
    for i in range(n):
        q[i, i] = -right-left
        q[i, i+1 if i < n-1 else n+1] += right
        q[i, i-1 if i else n] += left
    u = np.linspace(-1, 1, n+2)[1:-1]
    edges = np.r_[-1., (u[:-1]+u[1:])/2, 1.]
    for row, reset in ((n, "reset_minus"), (n+1, "reset_plus")):
        mean, sd = numeric[reset]/boundary, numeric["reset_sd"]/boundary
        def density(x):
            return math.exp(-.5*((x-mean)/sd)**2)/(sd*math.sqrt(2*math.pi))
        denominator = quad(density, -1., 1., epsabs=1e-14, epsrel=1e-13)[0]
        q[row, :n] = numeric["recovery_rate"]*np.array([quad(density, a, b, epsabs=1e-14, epsrel=1e-13)[0]/denominator for a, b in zip(edges[:-1], edges[1:])])
        q[row, row] = -numeric["recovery_rate"]
    generator_error = float(np.max(abs(q-cell.generator(1., .85).detach().numpy())))
    transition_error = max(float(np.max(abs(expm(duration*q)-cell.transition(duration, 1., .85).detach().numpy()))) for duration in (0., .03, .7, 1.9))
    whole, split = cell.transition(1.1, 1., .85), cell.transition(.4, 1., .85) @ cell.transition(.7, 1., .85)
    reward = torch.linspace(-1., 1., n+2, dtype=torch.float64)
    gwhole = torch.autograd.grad((cell.initial() @ whole @ reward).square(), cell.raw, retain_graph=True)[0]
    gsplit = torch.autograd.grad((cell.initial() @ split @ reward).square(), cell.raw)[0]
    semigroup_error = float((whole-split).abs().max().detach())
    semigroup_gradient_error = float((gwhole-gsplit).abs().max())
    scale = 1.01
    scaled = {key: value*scale if key in ("boundary", "diffusion", "drift", "reset_plus", "reset_minus", "reset_sd") else value for key, value in physical.items()}
    gauge_error = float((generator_from_physical(physical)-generator_from_physical(scaled)).abs().max().detach())
    mass_defect = float((whole.sum(-1)-1).abs().max().detach())
    ordinary = DifferentiableRenewalCell(raw, mode="ordinary", learn_boundary=False)
    ordinary_gradient = torch.autograd.grad(objective(ordinary), ordinary.raw)[0].detach().numpy()
    assert np.max(abs(ordinary_gradient[[0, 4, 5, 6, 7]])) == 0.
    assert max(generator_error, transition_error, semigroup_error, semigroup_gradient_error, gauge_error, mass_defect) < 1e-10
    return dict(passed=True, raw_gradient=gradient.tolist(), finite_difference=finite_difference,
                max_raw_gradient_error=gradient_error, max_generator_quadrature_error=generator_error,
                max_scipy_transition_error=transition_error, semigroup_error=semigroup_error,
                semigroup_gradient_error=semigroup_gradient_error, scale_gauge_generator_error=gauge_error,
                mass_defect=mass_defect, ordinary_fixed_boundary_inactive_coordinates=[0, 4, 5, 6, 7],
                scope="Finite CTMC long-prefix/readout/count gradients and independent quadrature/expm; no Brownian continuum or task-benefit qualification")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kernel", action="store_true")
    args = parser.parse_args()
    result = dict(schema="joint-pre-fit-independent-audit-v1", fitted_law_counterexample=fitted_law_counterexample(),
                  source_sha256={Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                 for p in (task.__file__, __file__)},
                  scope="Mathematical counterexample and archived task semantics; no new model efficacy inference")
    if args.kernel:
        from . import joint_kernel
        result["kernel"] = kernel_audit()
        result["source_sha256"]["joint_kernel.py"] = hashlib.sha256(Path(joint_kernel.__file__).read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
