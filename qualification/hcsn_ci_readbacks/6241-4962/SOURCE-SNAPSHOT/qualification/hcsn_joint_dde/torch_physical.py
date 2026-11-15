"""CPU/FP64 first-order physical VJP for the fixed-prior variational DDE.

The SciPy forward and explicit variational Jacobian are evaluated anew for
every call. Conversion to host arrays is inside this custom autograd contract;
backward uses its independently checked physical Jacobian. Initial p/content
are fixed NumPy data, not trainable network state. No second derivatives,
episode-prior differentiation or GPU implementation is provided.
"""

from dataclasses import replace
import math

import numpy as np
import torch
from torch.autograd.function import once_differentiable

from qualification.hcsn_joint_dde.sensitivities import PARAMETERS, solve_partials


FIELDS = (
    "active",
    "upper",
    "refractory",
    "events",
    "discounted_events",
    "discounted_active_time",
    "discounted_remaining_phase",
)


class _PhysicalFlow(torch.autograd.Function):
    @staticmethod
    def forward(
        ctx, parameters, template, times, active, content, phase, options, solver
    ):
        if (
            parameters.device.type != "cpu"
            or parameters.dtype != torch.float64
            or parameters.shape != (5,)
            or not torch.isfinite(parameters).all()
        ):
            raise ValueError("five finite CPU FP64 physical parameters required")
        for initial in (active, content):
            if isinstance(initial, torch.Tensor):
                raise ValueError(
                    "initial laws must be fixed NumPy arrays; their gradients are unsupported"
                )
        boundary, drift, sigma, reset, discount = parameters.detach().numpy().tolist()
        if reset <= 0:
            raise ValueError("absolute reset must be positive")
        model = replace(
            template,
            spatial=replace(template.spatial, mu=drift, sigma=sigma),
            reset=math.log(reset) - boundary,
            discount=discount,
        )
        result = solver(
            model,
            times,
            active,
            content,
            phase,
            log_boundary=boundary,
            absolute_reset=reset,
            **options,
        )
        values, jacobian = [], []
        for row in result["rows"]:
            values.append(
                np.concatenate(
                    [np.asarray(row["primal"][field]).ravel() for field in FIELDS]
                )
            )
            jacobian.append(
                np.stack(
                    [
                        np.concatenate(
                            [
                                np.asarray(row["partials"][name][field]).ravel()
                                for field in FIELDS
                            ]
                        )
                        for name in PARAMETERS
                    ],
                    axis=-1,
                )
            )
        packed, derivative = np.stack(values), np.stack(jacobian)
        if not np.all(np.isfinite(packed)) or not np.all(np.isfinite(derivative)):
            raise ArithmeticError("nonfinite physical forward or Jacobian")
        ctx.save_for_backward(
            parameters, parameters.detach().clone(), torch.from_numpy(derivative)
        )
        return torch.from_numpy(packed)

    @staticmethod
    @once_differentiable
    def backward(ctx, gradient):
        parameters, original, jacobian = ctx.saved_tensors
        if not torch.equal(parameters, original):
            raise RuntimeError("physical parameters changed after forward")
        return (
            torch.einsum("tdp,td->p", jacobian, gradient),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )


def physical_flow(parameters, template, times, active, content, phase=(), **options):
    """Differentiable only with respect to B/mu/sigma/Vr/q, fixed initial law."""
    return _PhysicalFlow.apply(
        parameters, template, times, active, content, phase, options, solve_partials
    )


def graded_physical_flow(
    parameters, template, times, active, content, phase=(), **options
):
    """Explicitly selected graded-v2 physical VJP; no uniform admission transfer."""
    from qualification.hcsn_joint_dde.graded_sensitivities import solve_graded_partials

    return _PhysicalFlow.apply(
        parameters,
        template,
        times,
        active,
        content,
        phase,
        options,
        solve_graded_partials,
    )
