"""Multi-unit, irregular-step reverse mode checks against finite differences."""

import numpy as np

from model import Parameters, gates, jacobian, rhs


def unpack(theta, n):
    p = Parameters(leak=theta[0], call_gain=theta[1], regen_gain=theta[2],
                   recovery_gain=theta[3], recovery_time=theta[4])
    return p, theta[5], theta[6:].reshape(n, n)


def forward(theta, initial, times, target, input_vector):
    n = len(initial)//2
    p, amplitude, w = unpack(theta, n)
    states = np.empty((len(times), 2*n))
    states[0] = initial
    env = np.exp(-.5*((times-3)/.6)**2)
    for k, dt in enumerate(np.diff(times)):
        inp = lambda _t, index=k: -.2+amplitude*env[index]*input_vector
        states[k+1] = states[k]+dt*rhs(times[k], states[k], p, w, inp)
    q = gates(states[:, :n])[0]
    loss = .5*np.mean((q-target)**2)
    return float(loss), states, env


def reverse(theta, initial, times, target, input_vector):
    n = len(initial)//2
    p, amplitude, w = unpack(theta, n)
    loss, states, env = forward(theta, initial, times, target, input_vector)
    q, _, dq, _ = gates(states[:, :n])
    direct = (q-target)*dq/q.size
    adj = np.concatenate((direct[-1], np.zeros(n)))
    grad = np.zeros_like(theta)
    for k in range(len(times)-2, -1, -1):
        dt = times[k+1]-times[k]
        x, y = states[k, :n], states[k, n:]
        qk, ak, _, _ = gates(x)
        ax, ay = adj[:n], adj[n:]
        grad[0] += dt*np.dot(ax, -x)
        grad[1] += dt*np.dot(ax, ak)
        grad[2] += dt*np.dot(ax, qk)
        grad[3] += dt*np.dot(ay, qk)/p.recovery_time
        grad[4] += dt*np.dot(ay, -(p.recovery_gain*qk-y))/p.recovery_time**2
        grad[5] += dt*np.dot(ax, env[k]*input_vector)
        grad[6:] += (dt*ax[:, None]*(qk-.5)[None, :]).ravel()
        adj = (np.eye(2*n)+dt*jacobian(states[k], p, w)).T@adj
        adj[:n] += direct[k]
    return loss, grad


def run_checks(seeds=(101, 202, 303, 404, 505)):
    result = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        n, steps = 4, 350
        times = np.concatenate(([0.], np.cumsum(rng.uniform(.02, .04, steps))))
        initial = np.concatenate((rng.normal(-.6, .15, n), rng.normal(1.65, .1, n)))
        vector = rng.uniform(.5, 1.5, n)
        target = .3+.3*np.exp(-.5*((times[:, None]-5)/1.5)**2)*rng.uniform(.8, 1.2, (1, n))
        theta = np.concatenate(([1., 1., 4., 6., 5., .9], rng.normal(0, .2, n*n)))
        loss, analytical = reverse(theta, initial, times, target, vector)
        finite = np.empty_like(theta)
        for j in range(len(theta)):
            eps = 1e-5*max(abs(theta[j]), 1.)
            shift = np.zeros_like(theta)
            shift[j] = eps
            finite[j] = (forward(theta+shift, initial, times, target, vector)[0]
                         -forward(theta-shift, initial, times, target, vector)[0])/(2*eps)
        absolute = np.abs(analytical-finite)
        relative = absolute/np.maximum(np.maximum(np.abs(analytical), np.abs(finite)), 1e-8)
        states = forward(theta, initial, times, target, vector)[1]
        p, _, w = unpack(theta, n)
        check_state = states[100]
        numeric_jacobian = np.empty((2*n, 2*n))
        for j in range(2*n):
            shift = np.zeros(2*n)
            shift[j] = 1e-6
            numeric_jacobian[:, j] = (rhs(0, check_state+shift, p, w, lambda t: 0.)
                                      -rhs(0, check_state-shift, p, w, lambda t: 0.))/(2e-6)
        jac_error = float(np.max(np.abs(jacobian(check_state, p, w)-numeric_jacobian)))
        item = dict(seed=seed, units=n, steps=steps, parameters=len(theta), loss=loss,
                    time_step_range=[float(np.diff(times).min()), float(np.diff(times).max())],
                    max_absolute_gradient_error=float(absolute.max()),
                    max_relative_gradient_error=float(relative.max()),
                    maximum_jacobian_absolute_error=jac_error,
                    analytic_gradient=analytical.tolist(), finite_difference_gradient=finite.tolist(),
                    passed=bool(absolute.max() < 1e-7 and jac_error < 1e-7))
        result.append(item)
    return {"method": "Exact reverse mode of a specified irregular-step Euler recurrence",
            "scope": "Initial states, input timing and targets fixed independently of differentiated parameters",
            "not_tested": ["gradient correctness of an adaptive ODE solver", "training quality", "long-horizon gradient stability"],
            "runs": result, "all_passed": all(x["passed"] for x in result)}


if __name__ == "__main__":
    import json
    print(json.dumps(run_checks(), indent=2))
