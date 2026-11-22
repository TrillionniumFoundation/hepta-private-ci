"""Explicit physical interval laws for the finite population encoder.

An interval holds input, drift and boundary fixed after its initial boundary
projection. Event-mask writes occur once at that edge; continuous writes solve
p'=pG, q'=qG-kappa*qD+kappa*m*pD, where D selects active cells. These are
different processes. Subdivision invariance applies only when the physical
input/control path and the physical write events are unchanged. Projection of
a moving boundary and the spatial/Erlang approximations remain approximations.
"""

from dataclasses import dataclass
import math

import torch

from .finite_control import continuation_value, first_passage_channels


@dataclass(frozen=True)
class FlowSemantics:
    """A held-interval content law; continuous rates are per physical second."""

    write_law: str
    write_rate: float | None = None

    def __post_init__(self):
        if self.write_law == "continuous_write":
            if (
                type(self.write_rate) not in (int, float)
                or not math.isfinite(self.write_rate)
                or self.write_rate <= 0
            ):
                raise ValueError(
                    "continuous_write requires an explicit positive rate per second"
                )
        elif self.write_law != "event_mask" or self.write_rate is not None:
            raise ValueError(
                "declare event_mask without a rate, or continuous_write with a rate"
            )


@dataclass(frozen=True)
class FlowObservables:
    """Full starting population, over THIS interval including its initial edge.

    First-event quantities include starting active AND refractory mass, with an
    edge-hit cohort counted once at time zero and excluded from later first
    hits. First risk is at most one; expected count includes repeat events and
    may exceed one. First risks cannot be summed across successive intervals.
    Marked counts carry signed content, so they are not probabilities. Count and
    occupation integrals are additive along an unchanged physical trajectory.
    """

    expected_event_count: torch.Tensor
    marked_event_count: torch.Tensor
    first_event_probability: torch.Tensor
    discounted_first_event: torch.Tensor
    occupation_integral: torch.Tensor


def physical_feature_names(content_size):
    return (
        "expected_event_count",
        *[f"marked_event_count_{i}" for i in range(content_size)],
        "first_event_probability",
        "margin",
        "occupation_rate",
        "continuation_value",
    )


def physical_step(
    flow,
    inputs,
    state=None,
    *,
    semantics,
    dt=None,
    write_mask=None,
    drift_override=None,
    boundary_override=None,
    reward_offset=None,
    feature_mask=None,
):
    """Execute one explicit finite-law interval; BatchedFlow.step is the legacy API.

    Returns (feature tensor, complete FlowState, diagnostics). The feature width
    matches legacy for integration; its first-risk meaning is deliberately
    broader and its names are explicit in diagnostics. This dense differentiable
    execution includes all reset/phase cycles. Persist/rebind semantics alongside
    model configuration when restoring state; FlowState records only population,
    boundary and clock, not external held controls or content-law choices.
    """
    from .batched_flow import FlowState

    if not isinstance(semantics, FlowSemantics):
        raise TypeError("explicit FlowSemantics required")
    c = flow.config
    if (
        inputs.ndim != 2
        or inputs.shape[1] != c.input_size
        or not 1 <= len(inputs) <= c.max_batch
        or inputs.dtype not in (torch.float32, torch.float64)
        or not bool(torch.isfinite(inputs).all())
        or inputs.dtype != flow.drive.weight.dtype
        or inputs.device != flow.drive.weight.device
    ):
        raise ValueError("finite matching FP32/FP64 [batch,input_size] required")
    duration = c.dt if dt is None else dt
    if (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("positive finite scalar dt required")
    micros = round(duration * 1_000_000)
    if not 1 <= micros <= 10**9 or not math.isclose(
        duration * 1_000_000, micros, rel_tol=0, abs_tol=1e-6
    ):
        raise ValueError("dt must be an integer number of microseconds")
    batch = len(inputs)
    state = flow.initial_state(batch, like=inputs) if state is None else state
    flow.validate_state(state, batch, inputs.dtype, inputs.device)
    if state.time_micros + micros >= 2**63:
        raise ValueError("adaptive clock capacity exceeded")
    work = inputs.to(dtype=flow.edges.dtype)
    boundary = (
        state.boundary
        if boundary_override is None
        else flow._batch_value(boundary_override, work, batch)
    )
    drift = (
        c.base_drift + c.drift_scale * flow.drive(inputs).squeeze(-1).tanh()
        if drift_override is None
        else flow._batch_value(drift_override, work, batch)
    ).to(work)
    if bool((boundary.abs() > c.boundary_limit).any()) or bool(
        (drift.abs() > c.drift_limit).any()
    ):
        raise ValueError("control exceeds the configured physical domain")
    density, _, jump, projected = flow._remap(state, boundary)
    mark = flow.writer(inputs).tanh().to(work)
    generator, event, _ = flow._generator(drift)
    size = event.shape[-1]
    active = torch.cat((work.new_ones(c.bins), work.new_zeros(c.stages + 1)))
    rewards = torch.stack((event, active.expand_as(event)), -1)
    augmented = torch.cat(
        (torch.cat((generator, rewards), -1), work.new_zeros(batch, 2, size + 2)), -2
    )
    action = torch.matrix_exp(augmented * duration)
    transition, integrals = action[:, :size, :size], action[:, :size, size:]
    if semantics.write_law == "continuous_write":
        if write_mask is not None:
            raise ValueError("continuous_write has no discrete write mask")
        killed = generator - semantics.write_rate * torch.diag(active)
        killed_augmented = torch.cat(
            (torch.cat((killed, rewards), -1), work.new_zeros(batch, 2, size + 2)), -2
        )
        killed_action = torch.matrix_exp(killed_augmented * duration)
        probability, content = density[:, :1], density[:, 1:]
        residual = content - mark[..., None] * probability
        next_p = probability @ transition
        next_q = mark[..., None] * next_p + residual @ killed_action[:, :size, :size]
        probability_integrals = probability @ integrals
        content_integrals = (
            mark[..., None] * probability_integrals
            + residual @ killed_action[:, :size, size:]
        )
        transitioned = torch.cat((next_p, next_q), 1)
        increments = torch.cat((probability_integrals, content_integrals), 1)
        content_write = -semantics.write_rate * (
            residual @ killed_action[:, :size, size + 1 :]
        ).squeeze(-1)
    else:
        if write_mask is None:
            raise ValueError(
                "event_mask requires one physical write decision per sample"
            )
        mask = torch.as_tensor(write_mask, device=inputs.device)
        if mask.shape != (batch,) or not bool(((mask == 0) | (mask == 1)).all()):
            raise ValueError("physical write mask must have binary shape [batch]")
        fraction = c.write_fraction * mask.to(work)[:, None, None]
        content = (1 - fraction) * density[:, 1:, : c.bins] + fraction * mark[
            ..., None
        ] * density[:, :1, : c.bins]
        written = torch.cat(
            (density[:, :1], torch.cat((content, density[:, 1:, c.bins :]), -1)), 1
        )
        content_write = (written[:, 1:] - density[:, 1:]).sum(-1)
        transitioned, increments = written @ transition, written @ integrals
    first = first_passage_channels(
        generator,
        event,
        discount=c.discount,
        duration=duration,
        event_destination=c.bins,
    )
    destination = torch.eye(size, dtype=work.dtype, device=work.device)[c.bins]
    # Remapped phases include both old refractory mass and new edge-hit mass.
    # Only the latter already had its first event in this interval.
    never_hit = density[:, 0] - jump[:, :1] * destination
    risk = jump[:, 0] + (never_hit * first["first_event_probability"]).sum(-1)
    discounted_first = jump[:, 0] + (never_hit * first["discounted_first_event"]).sum(
        -1
    )
    hits = jump + increments[..., 0]
    observables = FlowObservables(
        hits[:, 0], hits[:, 1:], risk, discounted_first, increments[:, 0, 1]
    )
    reward = (
        torch.cat(
            (
                c.gain * (boundary[:, None] + flow.centers) - c.maintenance,
                work.new_zeros(batch, c.stages + 1),
            ),
            -1,
        )
        - c.spike_cost * event
    )
    if reward_offset is not None:
        reward = (
            reward + flow._batch_value(reward_offset, work, batch)[:, None] * active
        )
    value = continuation_value(generator, reward, c.discount)
    p = transitioned[:, 0]
    margin = (p[:, : c.bins] * flow.centers).sum(-1) / c.extent
    call = (p * value).sum(-1)
    names = physical_feature_names(c.content_size)
    features = torch.cat(
        (
            hits,
            torch.stack(
                (risk, margin, observables.occupation_integral / duration, call), -1
            ),
        ),
        -1,
    ).to(inputs)
    if feature_mask is not None:
        mask = torch.as_tensor(feature_mask, dtype=inputs.dtype, device=inputs.device)
        if mask.shape != (len(names),) or not bool(((mask == 0) | (mask == 1)).all()):
            raise ValueError("feature mask must contain one zero/one per channel")
        features = features * mask
    updated = FlowState(transitioned, boundary, state.time_micros + micros, c)
    flow.validate_state(updated, batch, inputs.dtype, inputs.device)
    if not bool(torch.isfinite(features).all()) or not bool(
        torch.isfinite(discounted_first).all()
    ):
        raise FloatingPointError("nonfinite physical interval observables")
    diagnostics = {
        "observables": observables,
        "feature_names": names,
        "write_law": semantics.write_law,
        "write_rate": semantics.write_rate,
        "first_risk_population": "all starting active and refractory mass; edge hits once",
        "drift": drift,
        "boundary_jump_hits": jump[:, 0],
        "active_mass": p[:, : c.bins].sum(-1),
        "upper_projection_mass": projected[:, 0],
        "upper_projection_content": projected[:, 1:],
        "upper_projection_destination": "last_cell"
        if c.upper_mode == "reflecting"
        else "escape",
        "mass_error": p.sum(-1) - 1,
        "content_balance_error": transitioned[:, 1:].sum(-1)
        - state.density[:, 1:].sum(-1)
        - content_write,
        "generator_row_error": generator.sum(-1).abs().amax(-1),
        "transport_dtype": str(work.dtype),
        "output_dtype": str(inputs.dtype),
        "transport_backend": "dense_matrix_exp_physical",
        "refractory_variance": c.refractory**2 / c.stages,
        "call_kind": "frozen_finite_policy_continuation",
    }
    return features, updated, diagnostics
