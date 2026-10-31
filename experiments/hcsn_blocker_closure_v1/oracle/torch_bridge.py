"""CPU finite-QVI values with explicit first-order PyTorch differentiation.

This bridge demonstrates trainable task-aligned values. It is not an optimized
GPU kernel, and it does not replace the separately measured content network.
Active-set changes and reset/state interpolation knots are not globally smooth.
"""

import numpy as np
import torch

from .finite_qvi import action_values, implicit_gradient, interpolation, solve_policy
from .task_model import build_posterior_task


PARAMETERS = ("evidence", "rho", "cost", "fire_cost", "reset", "tau")
CHANNELS = ("total_value", "continue_value", "fire_class0", "fire_class1")


def value_jacobian(parameters, posterior, nodes):
    values = dict(zip(PARAMETERS, map(float, parameters)))
    problem, derivatives = build_posterior_task(nodes=nodes, **values)
    solved = solve_policy(problem)
    total = solved["value"]
    actions = action_values(problem, total)
    channels = np.vstack([total, actions])
    weights, dweights = interpolation(problem.grid, float(posterior))
    jacobian = np.empty((4, 6))
    rate, rho, delay = problem.rate, problem.rho, problem.delay_discount
    for column, key in enumerate(PARAMETERS):
        derivative = derivatives[key]
        dtotal = implicit_gradient(problem, solved, derivative)
        drho = derivative.get("rho", 0.)
        dtau = derivative.get("tau", 0.)
        drate = 2*rate/values["evidence"] if key == "evidence" else 0.
        dgenerator = derivative.get("generator", np.zeros_like(problem.generator))
        drunning = derivative.get("running", np.zeros_like(problem.running))
        dkeep = (drunning+drate*total+rate*dtotal+dgenerator@total+problem.generator@dtotal
                 -actions[0]*(drho+drate))/(rho+rate)
        ddelay = -delay*(problem.tau*drho+rho*dtau)/(1+rho*problem.tau/problem.phases)
        dreset = derivative.get("reset", np.zeros_like(problem.reset))
        drewards = derivative.get("rewards", np.zeros_like(problem.rewards))
        dfire = drewards+ddelay*(problem.reset@total)+delay*(dreset@total+problem.reset@dtotal)
        jacobian[:, column] = np.vstack([dtotal, dkeep, dfire])@weights
    return channels@weights, jacobian, channels@dweights


class _TaskValues(torch.autograd.Function):
    @staticmethod
    def forward(ctx, parameters, posterior, nodes):
        flat_parameters = parameters.detach().cpu().double().numpy().reshape(-1, 6)
        flat_posterior = posterior.detach().cpu().double().numpy().reshape(-1)
        result = [value_jacobian(p, x, nodes) for p, x in zip(flat_parameters, flat_posterior)]
        shape = parameters.shape[:-1]
        channel = parameters.new_tensor(np.stack([item[0] for item in result])).reshape(*shape, 4)
        jacobian = parameters.new_tensor(np.stack([item[1] for item in result])).reshape(*shape, 4, 6)
        state_jacobian = parameters.new_tensor(np.stack([item[2] for item in result])).reshape(*shape, 4)
        ctx.save_for_backward(jacobian, state_jacobian)
        return channel

    @staticmethod
    @torch.autograd.function.once_differentiable
    def backward(ctx, output_gradient):
        jacobian, state_jacobian = ctx.saved_tensors
        parameters_gradient = (output_gradient.unsqueeze(-1)*jacobian).sum(-2)
        state_gradient = (output_gradient*state_jacobian).sum(-1)
        return parameters_gradient, state_gradient, None


def task_values(parameters, posterior, nodes=33):
    """Return J, Q_KEEP, G_class0, G_class1 for broadcast parameter batches.

    Parameter order is PARAMETERS. Off-grid posterior values denote a mixture
    of the two neighboring observable grid states. The interpolation preserves
    the mean posterior; it is not a new continuous posterior diffusion solver.
    Float32 and float64 are accepted; only first derivatives are implemented.
    """
    if (parameters.shape[-1] != 6 or parameters.dtype not in (torch.float32, torch.float64)
            or posterior.dtype != parameters.dtype or posterior.device != parameters.device):
        raise ValueError("Require six floating parameters and matching state dtype/device")
    batch = torch.broadcast_shapes(parameters.shape[:-1], posterior.shape)
    return _TaskValues.apply(parameters.expand(*batch, 6), posterior.expand(batch), nodes)
