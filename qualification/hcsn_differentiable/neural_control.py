"""Optimal regenerative release for an affine neural retention objective.

Absolute log state follows dY=mu*dt+sigma*dW. While active it earns
gain*Y-maintenance; release costs spike_cost, waits refractory with zero
reward, then resets to the fixed log_reset. Discount is positive. This
task has a lower optimal boundary, unlike a terminal liquidation model.
All task parameters may receive first-order FP64 gradients.
"""

import torch
from torch.autograd.function import once_differentiable

from .contract import PhysicalParameters
from .operator import _check_parameters, _finite, _tensor
from .regenerative import _decay, first_hit_laplace


PARAMETER_NAMES = ("mu", "sigma", "discount", "log_reset", "refractory",
                   "gain", "maintenance", "spike_cost")


def physical_parameters(boundary, theta):
    """Connect the solved log boundary to the existing HCSN flow API."""
    return PhysicalParameters(boundary, theta[0], theta[1], theta[3].exp(), theta[2])


def _validate(theta):
    if not isinstance(theta, torch.Tensor) or theta.shape != (8,) or theta.dtype != torch.float64:
        raise ValueError("theta must be an eight-element FP64 tensor in PARAMETER_NAMES order")
    _finite("control parameters", theta)
    _check_parameters(physical_parameters(theta[3] - 1, theta))
    if not bool(0 < theta[4] <= 2) or not bool(theta[5] > 0):
        raise ValueError("require 0<refractory<=2 and gain>0")
    if not bool(theta[6] >= 0) or not bool(theta[7] > 0):
        raise ValueError("require maintenance>=0 and spike_cost>0")


def _terms(theta):
    mu, _, rho, reset, delay, gain, maintenance, cost = theta.unbind()
    decay = _decay(physical_parameters(reset - 1, theta))
    slope = gain / rho
    intercept = gain * mu / rho.square() - maintenance / rho
    return decay, slope, intercept, torch.exp(-rho * delay), cost


def boundary_residual(boundary, theta):
    """Regenerative matching with smooth-pasting amplitude gain/(rho*kappa)."""
    decay, slope, intercept, eta, cost = _terms(theta)
    amplitude = slope / decay
    reset = theta[3]
    return (slope * boundary + intercept + amplitude + cost
            - eta * (slope * reset + intercept
                     + amplitude * torch.exp(-decay * (reset - boundary))))


class _OptimalBoundary(torch.autograd.Function):
    @staticmethod
    def forward(ctx, theta):
        _validate(theta)
        low, high = theta[3] - 8.0, theta[3] - 1e-4
        if not bool(boundary_residual(low, theta) < 0 < boundary_residual(high, theta)):
            raise ValueError("interior optimum must have reset distance strictly in (1e-4,8)")
        for _ in range(64):
            middle = (low + high) / 2
            if bool(boundary_residual(middle, theta) < 0):
                low = middle
            else:
                high = middle
        boundary = (low + high) / 2
        ctx.save_for_backward(boundary, theta)
        return boundary

    @staticmethod
    @once_differentiable
    def backward(ctx, upstream):
        saved_boundary, saved_theta = ctx.saved_tensors
        with torch.enable_grad():
            boundary = saved_boundary.detach().requires_grad_()
            theta = saved_theta.detach().requires_grad_()
            residual = boundary_residual(boundary, theta)
            derivative_b, derivative_theta = torch.autograd.grad(residual, (boundary, theta))
        if not bool(derivative_b > 0):
            raise FloatingPointError("free-boundary implicit derivative is unresolved")
        gradient = -upstream * derivative_theta / derivative_b
        _finite("free-boundary gradient", gradient)
        return gradient


def optimal_boundary(theta):
    """Unique optimal release boundary; first-order implicit differentiation.

The residual derivative is gain/discount*(1-eta*exp(-kappa*(reset-b)))>0.
Forward bisection avoids a new runtime dependency on Lambert W. Backward
differentiates the smooth-pasting/matching system, not E(b)=0 divided by E'.
    """
    return _OptimalBoundary.apply(theta)


def policy_value(log_state, boundary, theta):
    """Perpetual task value for a fixed lower trigger and fixed absolute reset.

Release pays -spike_cost once. At or below the trigger the action is
immediate; remaining refractory time is valued separately below.
    """
    _validate(theta)
    boundary = _tensor(boundary, theta)
    if boundary.ndim != 0:
        raise ValueError("boundary must be scalar")
    params = physical_parameters(boundary, theta)
    _check_parameters(params)
    state = _tensor(log_state, theta)
    _finite("log_state", state)
    decay, slope, intercept, eta, cost = _terms(theta)
    distance_reset = theta[3] - boundary
    denominator = -torch.expm1(-theta[2] * theta[4] - decay * distance_reset)
    amplitude = (eta * (slope * theta[3] + intercept)
                 - cost - slope * boundary - intercept) / denominator
    # max implements the declared immediate-release region, not mass repair.
    active_state = torch.maximum(state, boundary)
    hit = first_hit_laplace(active_state - boundary, params)
    value = slope * active_state + intercept + amplitude * hit
    _finite("control policy value", value)
    return value


def optimal_value(log_state, theta):
    """Optimal continuation/release value, retaining the boundary gradient."""
    return policy_value(log_state, optimal_boundary(theta), theta)


def refractory_value(remaining, boundary, theta):
    """Value after release, with the already-paid event cost excluded."""
    _validate(theta)
    remaining = _tensor(remaining, theta)
    _finite("remaining", remaining)
    if bool(((remaining < 0) | (remaining > theta[4])).any()):
        raise ValueError("remaining must lie in [0,refractory]")
    return torch.exp(-theta[2] * remaining) * policy_value(theta[3], boundary, theta)
