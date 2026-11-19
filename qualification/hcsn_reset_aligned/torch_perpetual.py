"""First-order perpetual-value readout sharing the physical DDE generator."""

import torch
from torch.autograd.function import once_differentiable

from qualification.hcsn_reset_aligned.perpetual import perpetual_partials


class _Continuation(torch.autograd.Function):
    @staticmethod
    def forward(ctx, parameters, geometry):
        if (parameters.device.type != "cpu" or parameters.dtype != torch.float64 or
                parameters.shape != (5,) or not torch.isfinite(parameters).all()):
            raise ValueError("five finite CPU FP64 parameters required")
        values, jacobian = perpetual_partials(parameters.detach().numpy(), geometry)
        ctx.save_for_backward(torch.from_numpy(jacobian))
        return torch.from_numpy(values)

    @staticmethod
    @once_differentiable
    def backward(ctx, cotangent):
        (jacobian,) = ctx.saved_tensors
        return jacobian.T@cotangent, None


def perpetual_readout(parameters, states, *, geometry):
    """Undiscounted future U for each query/mark from aligned_flow's state.

    Refractory mass uses its discounted remaining-age channel Z_q, not just
    its total R. Gradients flow through both the full DDE state and closure.
    """
    values = _Continuation.apply(parameters, geometry)
    n = geometry["left_intervals"]+geometry["right_intervals"]
    if states.device.type != "cpu" or states.dtype != torch.float64 or states.ndim != 3 or states.shape[1] != n+5:
        raise ValueError("aligned_flow query/state/channel output required")
    return torch.einsum("tsc,s->tc", states[:, :n], values[:n])+states[:, n+4]*values[n]
