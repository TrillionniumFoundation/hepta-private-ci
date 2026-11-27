"""Native Torch input graph over a costed, fixed-physics linear propagator.

Only active/phase probability and signed-content amplitudes are trainable.
Physics, geometry, phase support, delay and migration stay fixed. The existing
physical-only API remains separate and continues rejecting trainable priors.
"""

import torch
from torch.autograd.function import once_differentiable

from .linear_map import initial_map


class _InputMutationGuard(torch.autograd.Function):
    @staticmethod
    def forward(ctx, output, *inputs):
        ctx.count = len(inputs)
        ctx.save_for_backward(*inputs, *(value.detach().clone() for value in inputs))
        return output

    @staticmethod
    @once_differentiable
    def backward(ctx, gradient):
        saved = ctx.saved_tensors  # Also triggers ordinary Torch version checks.
        originals, clones = saved[: ctx.count], saved[ctx.count :]
        if any(not torch.equal(old, copy) for old, copy in zip(originals, clones)):
            raise RuntimeError("initial amplitude input changed after forward")
        return (gradient,) + (None,) * ctx.count


def amplitude_flow(
    model,
    query_times,
    active,
    content,
    phase_mass,
    phase_content,
    *,
    supports=(),
    **options,
):
    """Return (all-seven-field tensor, cost receipt) with live amplitude AD.

    Output shape is [query, N+5, C+1]; mark zero is probability. Active input
    shape [N] omits the fixed zero lower atom and includes upper escape. Phase
    inputs are [K] and [K,C]. Values are finite nonnegative probability
    amplitudes and arbitrary signed contents; total mass is not constrained
    to one. The ambient VJP is the signed-amplitude linear extension, with
    numerical two-sided tests at strictly positive probability amplitudes.
    It is not an independently constrained normalized-probability derivative.
    For a normalized physical law, construct joint active/phase probabilities
    by a client-side softmax; construct content as probability times signed
    conditional marks when that binding is intended. Both chains remain live.
    No input is normalized or silently projected by this API.
    """
    inputs = (active, content, phase_mass, phase_content)
    if any(
        not isinstance(value, torch.Tensor)
        or value.device.type != "cpu"
        or value.dtype != torch.float64
        or not bool(torch.isfinite(value).all())
        for value in inputs
    ):
        raise ValueError("finite CPU FP64 amplitude tensors are required")
    count = model.spatial.intervals
    if (
        active.shape != (count,)
        or content.ndim != 2
        or content.shape[0] != count
        or not 1 <= content.shape[1] <= 4
        or phase_mass.shape != (len(supports),)
        or phase_content.shape != (len(supports), content.shape[1])
        or bool((active < 0).any())
        or bool((phase_mass < 0).any())
        or any(bool((value.abs() > 1e6).any()) for value in inputs)
    ):
        raise ValueError(
            "bounded active/phase probability and signed-content shapes differ"
        )
    mapped = initial_map(model, query_times, supports, **options)
    operator = torch.tensor(mapped["operator"], dtype=torch.float64, device="cpu")
    amplitudes = torch.cat(
        [
            torch.cat([active[:, None], content], dim=1),
            torch.cat([phase_mass[:, None], phase_content], dim=1),
        ],
        dim=0,
    )
    output = torch.einsum("tsd,dc->tsc", operator, amplitudes)
    if not bool(torch.isfinite(output).all()):
        raise ArithmeticError("amplitude flow is nonfinite")
    output = _InputMutationGuard.apply(output, *inputs)
    receipt = {
        key: value
        for key, value in mapped.items()
        if key not in ("operator", "times", "fixed_supports")
    }
    receipt.update(
        optimizer_updates=0, all_four_inputs_guarded=True, first_order_only=True
    )
    return output, receipt
