"""First-order physical/initial-law VJP for an exact moving-node reset."""

from fractions import Fraction

import numpy as np
import torch
from torch.autograd.function import once_differentiable

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_reset_aligned.mesh import aligned_model
from qualification.hcsn_reset_aligned.sensitivities import PARAMETERS, solve_aligned_partials


def _array(row):
    fields = ("upper", "refractory", "events", "discounted_events",
              "discounted_active_time", "discounted_remaining_phase")
    return np.concatenate([row["active"], *[np.asarray(row[k])[None] for k in fields]])


def _packets(supports, weights):
    return tuple(Packet(str(i), lo, hi, Fraction(float(row[0])),
                        tuple(Fraction(float(x)) for x in row[1:]))
                 for i, ((lo, hi), row) in enumerate(zip(supports, weights)))


class _AlignedFlow(torch.autograd.Function):
    @staticmethod
    def forward(ctx, parameters, law, times, supports, geometry, options):
        for value in (parameters, law):
            if value.device.type != "cpu" or value.dtype != torch.float64 or not torch.isfinite(value).all():
                raise ValueError("finite CPU FP64 tensors required")
        model, generator_partials = aligned_model(parameters.detach().numpy(), **geometry)
        n = model.spatial.intervals
        if (not isinstance(supports, tuple) or len(supports) > 8 or law.ndim != 2 or
                law.shape[0] != n+len(supports) or not 2 <= law.shape[1] <= 17 or n+len(supports) > 64):
            raise ValueError("bounded initial nodal/phase law required")
        if torch.any(law[:, 0] < 0) or torch.any(law[n:, 0] <= 0):
            raise ValueError("nonnegative nodal and positive packet probabilities required")
        initial = law.detach().numpy()
        active = np.r_[0., initial[:n, 0]]
        content = np.vstack((np.zeros((1, law.shape[1]-1)), initial[:n, 1:]))
        phase = _packets(supports, initial[n:])
        result = solve_aligned_partials(model, generator_partials, times, active, content, phase, **options)
        values = np.stack([_array(row["primal"]) for row in result["rows"]])
        jacobian = np.stack([np.stack([_array(row["partials"][name]) for name in PARAMETERS], -1)
                             for row in result["rows"]])
        kernels = []
        for start in range(0, len(initial), 16):
            count = min(16, len(initial)-start)
            basis = np.eye(len(initial))[:, start:start+count]
            marked = np.vstack((np.zeros((1, count)), basis[:n]))
            packets = _packets(supports, np.column_stack((np.ones(len(supports)), basis[n:])))
            propagated = model.solve(times, np.zeros(n+1), marked, packets, **options)
            kernels.append(np.stack([_array(row)[:, 1:] for row in propagated["rows"]]))
        ctx.save_for_backward(torch.from_numpy(jacobian), torch.from_numpy(np.concatenate(kernels, -1)))
        return torch.from_numpy(values)

    @staticmethod
    @once_differentiable
    def backward(ctx, cotangent):
        jacobian, kernel = ctx.saved_tensors
        return (torch.einsum("tscp,tsc->p", jacobian, cotangent),
                torch.einsum("tsb,tsc->bc", kernel, cotangent), None, None, None, None)


def aligned_flow(parameters, law, times, *, geometry, phase_supports=(), **options):
    """Same law/output axes as law_flow; mesh moves smoothly with B and Vr.

    geometry fixes left/right interval counts, endpoint, grading and delay.
    This derivative holds moving nodal weights fixed; a fixed physical prior
    must additionally differentiate its migration. First-order CPU FP64 only.
    """
    return _AlignedFlow.apply(parameters, law, times, phase_supports, geometry, options)
