"""Native first-order Torch first-hit readout, distinct from renewal count M."""

import torch
from torch.autograd.function import once_differentiable

from qualification.hcsn_reset_aligned.first_hit import first_hit_partials


class _FirstHit(torch.autograd.Function):
    @staticmethod
    def forward(ctx, parameters, times, geometry):
        if (parameters.device.type != "cpu" or parameters.dtype != torch.float64 or
                parameters.shape != (5,) or not torch.isfinite(parameters).all()):
            raise ValueError("five finite CPU FP64 parameters required")
        values, jacobian = first_hit_partials(parameters.detach().numpy(), times, geometry)
        ctx.save_for_backward(torch.from_numpy(jacobian))
        return torch.from_numpy(values)

    @staticmethod
    @once_differentiable
    def backward(ctx, cotangent):
        (jacobian,) = ctx.saved_tensors
        return torch.einsum("tnp,tn->p", jacobian, cotangent), None, None


def first_hit_readout(parameters, nodal_law, times, *, geometry):
    """Initial active-node mass/content mapped to finite first-hit totals.

    There are no phase rows. Column 0 is nonnegative probability; remaining
    columns may be signed. The output is unconditional hit mass when the
    supplied probability column has total mass below one.
    """
    values = _FirstHit.apply(parameters, times, geometry)
    if (nodal_law.device.type != "cpu" or nodal_law.dtype != torch.float64 or
            nodal_law.ndim != 2 or nodal_law.shape[0] != values.shape[1] or
            not 1 <= nodal_law.shape[1] <= 17 or not torch.isfinite(nodal_law).all() or
            torch.any(nodal_law[:, 0] < 0)):
        raise ValueError("finite nodal mass and optional signed content required; phase is unsupported")
    return values@nodal_law
