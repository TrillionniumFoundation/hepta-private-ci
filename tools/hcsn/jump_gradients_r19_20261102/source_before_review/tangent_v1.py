"""Analytic active-branch Jacobian of the actual captured jump-aware solver.

No finite difference enters the derivative. The left-limit LCP and the newly
admitted right-limit max are differentiated separately. Critical ties reject
ordinary qualification; directional.py supplies critical-cone derivatives.
"""

import hashlib

import numpy as np
from scipy.linalg import solve_banded
from numpy.polynomial.legendre import leggauss

from ..continuous_task_r18_20261101 import positive_reference
from ..continuous_task_r18_20261101.task import payoff
from .coordinates import P, Nondifferentiable, differentials, interpolation


TOL = 1e-10


def left_info(solution, index):
    config, x, lag = solution["config"], solution["x"], solution["lag"]
    reward = payoff(config, x)
    left = solution["left_limits"].get(index, solution["values"][index])
    b = solution["reset_values"][index].copy()
    if index % lag == 0:
        if index == lag:
            b[:] = -np.inf
        else:
            future = solution["left_limits"][index - lag]
            f = np.array([np.interp(config["reset_x"], x, row) for row in future])
            b = np.asarray(config["content_transition"]) @ f - np.asarray(config["reset_fee"]) - config["recovery_cost"] * config["recovery"]
    obstacle = np.maximum(reward, b[:, None])
    rate, dt = config["sigma"] ** 2 / (2 * solution["dx"] ** 2), solution["dt"]
    curvature = np.c_[2 * (left[:, 1] - left[:, 0]), np.diff(left, 2, axis=1), 2 * (left[:, -2] - left[:, -1])]
    residual = left - dt * rate * curvature - solution["values"][index - 1] + dt * config["wait_cost"]
    contact = left - obstacle
    if min(contact.min(), residual.min()) < -1e-8:
        raise RuntimeError("Captured primal does not satisfy its obstacle equations")
    active = contact < TOL
    critical = active & (abs(residual) < TOL)
    obstacle_tie = active & (abs(reward - b[:, None]) < TOL)
    choice = np.where(active, np.where(reward >= b[:, None], 1, 2), 0).astype(np.int8)
    return left, b, choice, critical, obstacle_tie


def coefficients(solution):
    count, dt = len(solution["x"]), solution["dt"]
    rate = solution["config"]["sigma"] ** 2 / (2 * solution["dx"] ** 2)
    lower, upper = np.full(count - 1, -dt * rate), np.full(count - 1, -dt * rate)
    lower[-1], upper[0] = -2 * dt * rate, -2 * dt * rate
    return lower, np.full(count, 1 + 2 * dt * rate), upper


def linear_solve(solution, rhs, choices, obstacle):
    lower, diagonal, upper = coefficients(solution)
    count = len(diagonal)
    band = np.zeros((3, count))
    band[0, 1:], band[1], band[2, :-1] = upper, diagonal, lower
    active = np.flatnonzero(choices)
    band[1, active] = 1
    band[0, active[active < count - 1] + 1] = 0
    band[2, active[active > 0] - 1] = 0
    target = rhs.copy()
    target[active] = obstacle[active]
    return solve_banded((1, 1), band, target, check_finite=False)


def reset_jacobian(solution, previous, previous_jacobian, differentials):
    config, x = solution["config"], solution["x"]
    lower, weights, slopes = interpolation(x, config["reset_x"])
    f = previous[:, lower:lower + 2] @ weights
    df = np.einsum("mip,i->mp", previous_jacobian[:, lower:lower + 2], weights)
    df += (previous[:, lower:lower + 2] @ slopes)[:, None] * differentials["reset_x"][None, :]
    return np.asarray(config["content_transition"]) @ df + np.einsum("pml,l->mp", differentials["matrix"], f) - differentials["fee"].T - config["recovery"] * differentials["recovery"][None, :]


def jump(solution, raw, strict=True):
    config, d, reward = differentials(raw, solution["x"], solution["config"])
    # Reset interpolation must expose its real piecewise differentiability.
    interpolation(solution["x"], config["reset_x"])
    values, lag, dt = solution["values"], solution["lag"], solution["dt"]
    jacobian = np.zeros(values.shape + (P,))
    jacobian[0] = np.moveaxis(d["reward"], 0, -1)
    left_jacobians, branches, critical_count = {}, [], 0
    for index in range(1, len(values)):
        left, b, choices, critical, tie = left_info(solution, index)
        critical_count += int(critical.sum() + tie.sum())
        branches.append(choices.tobytes())
        db = np.zeros((2, P))
        right_db = np.zeros_like(db)
        if index >= lag:
            right_db = reset_jacobian(solution, values[index - lag], jacobian[index - lag], d)
            if index % lag:
                db = right_db
            elif index > lag:
                db = reset_jacobian(solution, solution["left_limits"][index - lag], left_jacobians[index - lag], d)
        left_gradient = np.zeros((2, len(solution["x"]), P))
        for mode in range(2):
            rhs = jacobian[index - 1, mode] - dt * d["wait"][None, :]
            curvature = np.r_[2 * (left[mode, 1] - left[mode, 0]), np.diff(left[mode], 2), 2 * (left[mode, -2] - left[mode, -1])]
            rhs[:, 0] += dt * config["sigma"] ** 2 / solution["dx"] ** 2 * curvature
            obstacle = np.where((reward[mode] >= b[mode])[:, None], d["reward"][:, mode].T, db[mode])
            left_gradient[mode] = linear_solve(solution, rhs, choices[mode], obstacle)
        if index % lag == 0:
            left_jacobians[index] = left_gradient.copy()
            right_reset = solution["reset_values"][index, :, None]
            select_reset = right_reset > left
            critical_count += int((abs(right_reset - left) < TOL).sum())
            branches.append(select_reset.tobytes())
            jacobian[index] = np.where(select_reset[..., None], right_db[:, None, :], left_gradient)
        else:
            jacobian[index] = left_gradient
    if strict and critical_count:
        raise Nondifferentiable(f"Ordinary full Jacobian crosses {critical_count} critical/tied primal branches")
    return dict(jacobian=jacobian, left_jacobians=left_jacobians,
                critical_count=critical_count, branch_sha256=hashlib.sha256(b"".join(branches)).hexdigest())


def density_tangent(config, intervals, dt, nodes=8):
    h, width = (config["upper"] - config["lower"]) / intervals, config["upper"] - config["lower"]
    sd = config["sigma"] * np.sqrt(dt)
    offsets = np.arange(2 * intervals) * h
    offsets = np.where(offsets <= width, offsets, offsets - 2 * width)
    points, weights = leggauss(nodes)
    derivative = np.zeros(2 * intervals)
    for direction in (-1, 1):
        u = direction * (points + 1) * h / 2
        w = weights * h / 2 * (1 - abs(u) / h)
        for image in range(-2, 3):
            z = (offsets[:, None] + u[None, :] + 2 * image * width) / sd
            density = np.exp(-.5 * z ** 2) / (np.sqrt(2 * np.pi) * sd)
            derivative += (density * (z ** 2 - 1)) @ w
    return dict(fft=np.fft.rfft(derivative), weights=derivative)


def positive(solution, raw, strict=True):
    config, d, reward = differentials(raw, solution["x"], solution["config"])
    interpolation(solution["x"], config["reset_x"])
    values, lag, dt = solution["values"], solution["lag"], solution["dt"]
    jacobian = np.zeros(values.shape + (P,))
    jacobian[0] = np.moveaxis(d["reward"], 0, -1)
    dop = density_tangent(config, len(solution["x"]) - 1, dt)
    critical_count, branches = 0, []
    for index in range(1, len(values)):
        waiting = positive_reference.heat(values[index - 1], solution["operator"]) - config["wait_cost"] * dt
        dwaiting = np.moveaxis(positive_reference.heat(np.moveaxis(jacobian[index - 1], -1, 0), solution["operator"]), 0, -1)
        dwaiting -= dt * d["wait"][None, None, :]
        dwaiting[..., 0] += positive_reference.heat(values[index - 1], dop)
        db = np.zeros((2, P))
        if index >= lag:
            db = reset_jacobian(solution, values[index - lag], jacobian[index - lag], d)
        candidates = np.stack((reward, np.broadcast_to(solution["reset_values"][index, :, None], reward.shape), waiting))
        choices = candidates.argmax(0)
        sorted_values = np.sort(candidates, axis=0)
        critical_count += int((sorted_values[-1] - sorted_values[-2] < TOL).sum())
        branches.append(choices.tobytes())
        jacobian[index] = np.where((choices == 0)[..., None], np.moveaxis(d["reward"], 0, -1),
            np.where((choices == 1)[..., None], db[:, None, :], dwaiting))
    if strict and critical_count:
        raise Nondifferentiable(f"Ordinary reference Jacobian has {critical_count} max ties")
    return dict(jacobian=jacobian, critical_count=critical_count,
                branch_sha256=hashlib.sha256(b"".join(branches)).hexdigest(), kernel_mass_tangent=float(dop["weights"].sum()))


def signature(solution, reference=False):
    branches, critical_count = [], 0
    reward = payoff(solution["config"], solution["x"])
    for index in range(1, len(solution["values"])):
        if reference:
            waiting = positive_reference.heat(solution["values"][index - 1], solution["operator"]) - solution["config"]["wait_cost"] * solution["dt"]
            candidates = np.stack((reward, np.broadcast_to(solution["reset_values"][index, :, None], reward.shape), waiting))
            ordered = np.sort(candidates, axis=0)
            critical_count += int((ordered[-1] - ordered[-2] < TOL).sum())
            branches.append(candidates.argmax(0).tobytes())
        else:
            left, _, choices, critical, tie = left_info(solution, index)
            critical_count += int(critical.sum() + tie.sum())
            branches.append(choices.tobytes())
            if index % solution["lag"] == 0:
                reset = solution["reset_values"][index, :, None]
                critical_count += int((abs(reset - left) < TOL).sum())
                branches.append((reset > left).tobytes())
    return dict(branch_sha256=hashlib.sha256(b"".join(branches)).hexdigest(), critical_count=critical_count)
