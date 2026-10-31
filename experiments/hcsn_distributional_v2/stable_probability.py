"""Roundoff-bounded unit-mass recurrence for a tagged regenerative kernel.

This is a separate numerical profile, not a modification of the frozen kernel.
It is only for ordinary probability-preserving regenerative transitions. A
killed/no-event/survival operator is substochastic by design and MUST NEVER be
passed to this function, even when its row deficit happens to be small.

The caller's explicit tag establishes operator semantics; near-unit row sums
alone cannot distinguish roundoff from a small, genuine killing probability.
No negative entry is clipped. Excess mass defects fail instead of being hidden.
The normalization denominator participates in autograd. Only diagnostics detach.
"""

import torch


PROFILE = "roundoff_unit_mass_v1"
REGENERATIVE_PROBABILITY = "regenerative_probability"


def probability_tolerances(dtype):
    """Fixed a priori guards; the step guard matches the original checked API.

    These are acceptance guards, not certified forward-error bounds. Analytic
    Poisson-tail certificates do not include floating-point arithmetic. Input
    states must already be normalized to a substantially tighter tolerance.
    """
    if dtype not in (torch.float32, torch.float64):
        raise TypeError("The stable profile supports float32 or float64 only")
    epsilon = torch.finfo(dtype).eps
    return dict(input_mass=max(1e-12, 8 * epsilon),
                single_step_mass=max(1e-12, 256 * epsilon),
                cast_roundoff=4 * epsilon)


def _require(condition, message):
    if not bool(torch.all(condition)):
        raise ValueError(message)


def advance_probability(probability, transition, *, operator_kind,
                        event_vector=None, reward_vector=None):
    """Apply one regenerative transition and repair only bounded mass roundoff.

    Args:
        probability: Row probabilities, shape (..., states).
        transition: Row-stochastic transition, shape (..., states, states).
        operator_kind: Must explicitly equal ``regenerative_probability``.
        event_vector: Optional per-start-state expected event count. Counts can
            exceed one. They are computed from the pre-transition probability.
        reward_vector: Optional per-start-state expected accumulated reward.

    Returns:
        Dictionary with ``probability``, ``events``, ``reward``, ``diagnostics``.
        Events/reward are None if their vectors were omitted. The probability
        has the original dtype; mass reduction/division use float64. The actual
        L1 correction and pre/post mass defects are always retained as tensors.

    For nonnegative raw state q of mass s, exact normalization changes its L1
    norm by |1-s|. Casting can add roundoff; the actual correction is measured
    and guarded. This identity is not a global accuracy guarantee for the
    underlying finite-volume model, transition construction, or gradients.
    """
    if operator_kind != REGENERATIVE_PROBABILITY:
        raise ValueError("Only tagged regenerative_probability operators may be normalized; "
                         "killed/no-event/survival operators must remain substochastic")
    if not isinstance(probability, torch.Tensor) or not isinstance(transition, torch.Tensor):
        raise TypeError("Probability and transition must be torch tensors")
    tolerances = probability_tolerances(probability.dtype)
    if transition.dtype != probability.dtype or transition.device != probability.device:
        raise TypeError("Probability and transition must have the same dtype and device")
    if probability.ndim < 1 or transition.ndim < 2:
        raise ValueError("Expected row probability and matrix transition")
    if transition.shape[-2:] != (probability.shape[-1], probability.shape[-1]):
        raise ValueError("Transition dimensions do not match probability states")
    _require(torch.isfinite(probability), "Nonfinite input probability")
    _require(probability >= 0, "Negative input probability; clipping is forbidden")
    _require(torch.isfinite(transition), "Nonfinite transition")
    _require(transition >= 0, "Negative transition entry; clipping is forbidden")

    input_mass = probability.sum(-1, dtype=torch.float64)
    row_mass = transition.sum(-1, dtype=torch.float64)
    _require(torch.abs(input_mass - 1) <= tolerances["input_mass"],
             "Input mass exceeds the roundoff profile input guard")
    _require(torch.abs(row_mass - 1) <= tolerances["single_step_mass"],
             "Transition row mass exceeds the roundoff profile single-step guard")

    raw = torch.matmul(probability.unsqueeze(-2), transition).squeeze(-2)
    raw_mass = raw.sum(-1, keepdim=True, dtype=torch.float64)
    _require(torch.isfinite(raw), "Nonfinite propagated probability")
    _require(raw >= 0, "Negative propagated probability; clipping is forbidden")
    _require(torch.abs(raw_mass - 1) <= tolerances["single_step_mass"],
             "Propagated mass exceeds the roundoff profile single-step guard")
    probability_next = (raw.to(torch.float64) / raw_mass).to(probability.dtype)
    correction = (probability_next.to(torch.float64) - raw.to(torch.float64)).abs().sum(-1)
    _require(correction <= tolerances["single_step_mass"] + tolerances["cast_roundoff"],
             "Actual probability correction exceeds the declared roundoff budget")
    post_mass = probability_next.sum(-1, dtype=torch.float64)
    _require(torch.abs(post_mass - 1) <= tolerances["input_mass"],
             "Normalized probability does not meet the next-step input guard")

    def functional(vector, name, nonnegative=False):
        if vector is None:
            return None
        if not isinstance(vector, torch.Tensor) or vector.dtype != probability.dtype or \
                vector.device != probability.device or vector.shape[-1] != probability.shape[-1]:
            raise TypeError(name + " must match probability dtype, device and state dimension")
        # Compare to the already computed state output shape, not merely the
        # last state dimension. A stray leading singleton dimension in a
        # vector can silently turn [batch] counts into [batch,batch] counts.
        # Use the broadcasted *pre-transition* state for event/reward, while
        # allowing a shared 1-D start across independently batched operators.
        try:
            shape = torch.broadcast_shapes(probability.shape, vector.shape,
                                           probability_next.shape)
        except RuntimeError as exc:
            raise ValueError(name + " has incompatible batch axes") from exc
        if shape != probability_next.shape:
            raise ValueError(name + " introduces unintended batch axes")
        _require(torch.isfinite(vector), "Nonfinite " + name)
        if nonnegative:
            _require(vector >= 0, "Negative " + name)
        # Finite entries do not guarantee finite accumulated counts/reward:
        # the permitted roundoff in input mass may push a near-max finite
        # vector expectation beyond the dtype range. Refuse instead of
        # returning infinity as a valid-looking physical observation.
        expectation=(probability.expand(shape) * vector).sum(-1)
        _require(torch.isfinite(expectation), "Nonfinite accumulated " + name)
        return expectation

    return dict(
        probability=probability_next,
        events=functional(event_vector, "event vector", nonnegative=True),
        reward=functional(reward_vector, "reward vector"),
        diagnostics=dict(
            profile=PROFILE, operator_kind=operator_kind,
            input_mass=input_mass.detach(),
            pre_projection_mass=raw_mass.squeeze(-1).detach(),
            post_projection_mass=post_mass.detach(),
            scale=(1 / raw_mass.squeeze(-1)).detach(),
            actual_l1_correction=correction.detach(),
            maximum_transition_row_mass_defect=(row_mass - 1).abs().amax(-1).detach(),
            tolerances=tolerances,
        ),
    )
